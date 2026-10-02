"""The board plan, built from stored data only: areas from the system map and inventory units, stages from the
user's goals, blockers and root-cause groups, severity, priority, size and owner per finding. `board propose`
writes it for the user to approve; no tracker is called here."""
import fnmatch
import hashlib
import json
import os
import re
from collections import Counter

from . import blockers, rootcause
from . import visibility as vis
from .backup import backup
from .common import CrucibleError, Root, read_json, write_json
from .config import git
from .permissions import authorize, log_action, record_dryrun, refuse, run_action
from .trackers import get_adapter

BLOCKERS_STAGE = "Blockers"
CAUSES_STAGE = "Root causes that unblock other findings"
UNASSIGNED = "unassigned"
DATES_QUESTION = "Put dates on the stages? This needs your team speed; dates from estimates drift."
CODEOWNERS_PATHS = ("CODEOWNERS", ".github/CODEOWNERS", "docs/CODEOWNERS")
ITEM_VALUES = {"Area": "area", "Stage": "stage", "Severity": "severity", "Priority": "priority",
               "Size": "size", "Owner": "owner"}


def build_areas(root, cfg):
    """One area per repo of the system map and per inventory unit, each with the folder or file it came from."""
    paths = {r["name"]: r["path"] for r in cfg.get("repos", [])}
    graph = read_json(root.p("graph.json"), {"repos": [], "edges": []})
    areas = [{"name": name, "kind": "repo", "source": paths.get(name) or "graph.json"}
             for name in sorted(set(paths) | set(graph["repos"]))]
    for name in root.units():
        unit = root.unit(name)
        if unit["files"]:
            areas.append({"name": name, "kind": "unit", "source": f"{unit['repo']}/{unit['files'][0]}"})
    return areas


def goal_rank(cfg, goal):
    for rank, g in enumerate(cfg["goals"], 1):
        if g["id"] == goal:
            return rank
    return len(cfg["goals"]) + 1


def generated_stages(root, cfg, findings):
    """The ordered stages: blockers, then causes shared by several findings, then one stage per goal."""
    stages, reasons = [], {}
    open_blockers = [b["id"] for b in blockers.load(root) if b["status"] == "open"]
    if open_blockers:
        stages.append({"name": BLOCKERS_STAGE, "blockers": open_blockers, "findings": []})
    shared = [g for g in rootcause.group_by_root_cause(findings) if len(g["findings"]) > 1]
    shared.sort(key=lambda g: (-len(g["findings"]), g["findings"]))
    if shared:
        stages.append({"name": CAUSES_STAGE, "blockers": [], "findings": []})
    for group in shared:
        for fid in group["findings"]:
            stages[-1]["findings"].append(fid)
            reasons[fid] = (CAUSES_STAGE, f"blocks {len(group['findings'])} findings in {group['repo']}")
    for goal in sorted(cfg["goals"], key=lambda g: goal_rank(cfg, g["id"])):
        ids = [fid for fid, f in sorted(findings.items()) if f["goal"] == goal["id"] and fid not in reasons]
        if ids:
            name = f"Goal {goal_rank(cfg, goal['id'])}: {goal['name']}"
            stages.append({"name": name, "blockers": [], "findings": ids})
            for fid in ids:
                reasons[fid] = (name, f"goal {goal_rank(cfg, goal['id'])}: {goal['name']}")
    return stages, reasons


def map_to_roadmap(stages, reasons, roadmap):
    """Put the generated stages onto the user's stage names by order; every mapping is recorded."""
    last = len(roadmap) - 1
    mapping = [{"generated": s["name"], "roadmap": roadmap[min(i, last)],
                "why": f"generated stage {i + 1} of {len(stages)} onto the roadmap by order"}
               for i, s in enumerate(stages)]
    target = {m["generated"]: m["roadmap"] for m in mapping}
    mapped = [{"name": name, "blockers": [], "findings": []} for name in roadmap]
    for s in stages:
        home = mapped[roadmap.index(target[s["name"]])]
        home["blockers"] += s["blockers"]
        home["findings"] += s["findings"]
    return mapped, {fid: (target[stage], reason) for fid, (stage, reason) in reasons.items()}, mapping


def cited(f):
    """(file, first line, last line) of the finding's root cause, else of its first location; None if unparsable."""
    chain = f.get("chain") if isinstance(f.get("chain"), dict) else {}
    ref = (chain.get("root_cause") or {}).get("ref") or next((w.get("ref") for w in f.get("where") or []), "")
    return rootcause.ref_key(ref) if ref else None


def codeowners_match(pattern, rel):
    anchored = pattern.startswith("/") or "/" in pattern.rstrip("/")
    pattern = pattern.lstrip("/")
    if pattern.endswith("/") or "*" not in pattern and "." not in os.path.basename(pattern):
        pattern = pattern.rstrip("/")
        return rel.startswith(pattern + "/") if anchored else f"/{pattern}/" in f"/{rel}"
    return fnmatch.fnmatch(rel, pattern) if anchored else fnmatch.fnmatch(os.path.basename(rel), pattern)


def codeowners_owner(entry, rel):
    """(owners, CODEOWNERS file) of the last rule matching rel, or None. Rules are the simple glob form."""
    for name in CODEOWNERS_PATHS:
        full = os.path.join(entry["path"], *name.split("/"))
        if not os.path.isfile(full):
            continue
        found = None
        with open(full, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                parts = line.split("#", 1)[0].split()
                if len(parts) > 1 and codeowners_match(parts[0], rel):
                    found = ", ".join(parts[1:])
        return (found, name) if found else None
    return None


def history_owner(entry, key):
    """The author with most commits on the cited lines, or None when the repo is no git repo or has no history."""
    if not os.path.exists(os.path.join(entry["path"], ".git")):
        return None
    rel, a, b = key
    out = git(entry["path"], "log", "-L", f"{a},{b}:{rel}", "-s", "--format=%aN")
    authors = Counter(line for line in out.splitlines() if line.strip())
    return authors.most_common(1)[0][0] if authors else None


def resolve_owner(cfg, f):
    """-> (owner, source). CODEOWNERS, then git history of the cited lines, then the user's answer, else unassigned."""
    entry = next((r for r in cfg.get("repos", []) if r["name"] == f["repo"]), None)
    key = cited(f)
    if entry and key:
        rule = codeowners_owner(entry, key[0])
        if rule:
            return rule
        author = history_owner(entry, key)
        if author:
            return author, f"git log of {rootcause.ref_text(key)}"
    row = (cfg.get("owners") or {}).get(f["repo"])
    assignee = row.get("assignee") if isinstance(row, dict) else row
    if assignee:
        return assignee, "the user's owners answer"
    return UNASSIGNED, "none found"


def build_board(root, cfg=None, findings=None):
    """-> {areas, stages, mapping, items}; items is by finding id: stage, reason, severity, priority, area, size,
    owner with its source, and the finding's visibility."""
    cfg = cfg or root.config()
    findings = root.findings() if findings is None else findings
    stages, reasons = generated_stages(root, cfg, findings)
    mapping = []
    if cfg.get("stages"):
        stages, reasons, mapping = map_to_roadmap(stages, reasons, cfg["stages"])
    items = {}
    for fid, f in sorted(findings.items()):
        owner, owner_source = resolve_owner(cfg, f)
        items[fid] = {"stage": reasons[fid][0], "reason": reasons[fid][1], "severity": f["severity"],
                      "priority": goal_rank(cfg, f["goal"]), "area": f["repo"], "size": f["size"],
                      "owner": owner, "owner_source": owner_source, "visibility": f.get("visibility", "public")}
    return {"areas": build_areas(root, cfg), "stages": stages, "mapping": mapping, "items": items}


def research_problems(findings):
    if not findings:
        return ["no accepted findings: read and verify the units first, then propose the board"]
    return [f"{fid}: the root cause is not verified" for fid, f in sorted(findings.items())
            if f.get("root_cause_verified") is not True]


def dates_mode(cfg):
    return cfg.get("board_dates") or "none"


def wanted_fields(cfg, result):
    items = list(result["items"].values())
    stage_source = "your roadmap" if result["mapping"] else "blockers, shared root causes and your goal order"
    owners = {i["owner"]: i["owner_source"] for i in items}
    fields = [
        ("Area", [(a["name"], a["source"]) for a in result["areas"]]),
        ("Stage", [(s["name"], stage_source) for s in result["stages"]]),
        ("Severity", [(v, "the verified finding severity") for v in sorted({i["severity"] for i in items})]),
        ("Priority", [(v, "your goal order") for v in sorted({i["priority"] for i in items})]),
        ("Size", [(v, "the finding's fix size") for v in sorted({i["size"] for i in items})]),
        ("Owner", [(o, owners[o]) for o in sorted(owners)]),
    ]
    if dates_mode(cfg) == "estimates":
        fields.append(("Target date", []))
    return fields


def map_fields(cfg, wanted):
    """Keep every field the board already has: map onto it by name and propose only the missing options."""
    existing = (cfg.get("tracker") or {}).get("fields") or {}
    by_lower = {name.lower(): name for name in existing}
    fields, used = [], set()
    for name, values in wanted:
        values = [{"value": v, "source": source} for v, source in values]
        found = by_lower.get(name.lower())
        have = [str(o) for o in existing.get(found, [])] if found else []
        fields.append({"name": name, "values": values, "action": "map" if found else "add",
                       "existing": found or "",
                       "add_values": [v["value"] for v in values if str(v["value"]) not in have]})
        used.add(found)
    return fields, sorted(set(existing) - used)


def build_views(result, private_board):
    views = [{"name": "Start here", "group_by": "Stage", "filter": f"Stage = {result['stages'][0]['name']}",
              "layout": "BOARD_LAYOUT"},
             {"name": "By stage", "group_by": "Stage", "filter": "", "layout": "BOARD_LAYOUT"},
             {"name": "By repo", "group_by": "Area", "filter": "", "layout": "TABLE_LAYOUT"},
             {"name": "By owner", "group_by": "Owner", "filter": "", "layout": "TABLE_LAYOUT"}]
    if private_board:
        views.append({"name": "Security", "group_by": "Severity", "filter": "finding visibility = private",
                      "layout": "TABLE_LAYOUT"})
    return views


def proposal_hash(plan):
    text = json.dumps({k: v for k, v in plan.items() if k != "hash"}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def build_proposal(root, cfg=None, findings=None):
    cfg = cfg or root.config()
    findings = root.findings() if findings is None else findings
    problems = research_problems(findings)
    if problems:
        raise CrucibleError("refused: the board is proposed after the research (findings verified and grouped by "
                            "root cause): " + "; ".join(problems))
    result = build_board(root, cfg, findings)
    groups = rootcause.group_by_root_cause(findings)
    key = vis.board_key(cfg)
    fields, kept = map_fields(cfg, wanted_fields(cfg, result))
    plan = {"research": {"findings": len(findings), "root_causes": len(groups),
                         "shared": sum(1 for g in groups if len(g["findings"]) > 1),
                         "open_blockers": sum(1 for b in blockers.load(root) if b["status"] == "open")},
            "board": key, "dates": dates_mode(cfg), "fields": fields, "existing_kept": kept,
            "stages": result["stages"], "mapping": result["mapping"], "items": result["items"],
            "views": build_views(result, bool(key) and vis.confirmed(cfg, key) == "private")}
    plan["hash"] = proposal_hash(plan)
    return plan


def render_proposal(plan):
    r = plan["research"]
    lines = [f"research: {r['findings']} findings, every root cause verified, {r['root_causes']} root causes "
             f"({r['shared']} shared by several findings), {r['open_blockers']} open blockers"]
    for field in plan["fields"]:
        what = f"maps onto your field {field['existing']!r}" if field["action"] == "map" else "new field"
        lines.append(f"field {field['name']}: {what}; adds values: "
                     f"{', '.join(map(str, field['add_values'])) or 'none'}")
        lines += [f"  {v['value']} (source: {v['source']})" for v in field["values"]]
    if plan["existing_kept"]:
        lines.append("existing fields kept untouched: " + ", ".join(plan["existing_kept"]))
    for stage in plan["stages"]:
        lines.append(f"stage {stage['name']}: {len(stage['findings'])} findings, blockers: "
                     f"{', '.join(stage['blockers']) or 'none'}")
        lines += [f"  {fid}: {plan['items'][fid]['reason']}" for fid in stage["findings"]]
    lines += [f"roadmap: {m['generated']} -> {m['roadmap']} ({m['why']})" for m in plan["mapping"]]
    lines += [f"item {fid}: size {i['size']}, owner {i['owner']} ({i['owner_source']})"
              for fid, i in sorted(plan["items"].items())]
    lines += [f"view {v['name']}: group by {v['group_by']}" + (f", where {v['filter']}" if v["filter"] else "")
              for v in plan["views"]]
    lines += [f"dates: {plan['dates']}", DATES_QUESTION + " (`crucible answer board_dates none|estimates`)"]
    return "\n".join(lines)


def plan_path(root):
    return root.p("board", "plan.json")


def require_approved_plan(root, cfg):
    """The gate `file --apply` calls when the tracker is a board: the current board plan must be approved."""
    if not vis.board_key(cfg):
        return
    stored = read_json(plan_path(root))
    if not stored:
        refuse(root, "tracker_board", "apply", "no board plan: run `crucible board propose`, show it to the user, "
                                               "then `crucible approve HASH`")
    if proposal_hash(build_proposal(root, cfg)) != stored["hash"]:
        refuse(root, "tracker_board", "apply", "the board plan is out of date: run `crucible board propose` again")
    approved = read_json(root.p("approvals.json"), [])
    if stored["hash"] not in [row["hash"] for row in approved]:
        refuse(root, "tracker_board", "apply", "the board plan is not approved: show it to the user, then run "
                                               f"`crucible approve {stored['hash']}`")


def cmd_propose(args):
    root = Root(args.root)
    root.require_confirmed()
    plan = build_proposal(root)
    write_json(plan_path(root), plan)
    record_dryrun(root, plan["hash"], plan)
    print(render_proposal(plan))
    print(f"plan hash: {plan['hash']}")
    print(f"show this plan to the user; after their go run `crucible approve {plan['hash']}`; nothing is created "
          "on the board before that")


def board_ref(cfg):
    owner, _, number = vis.board_key(cfg)[len("board:"):].partition("/")
    return owner, number


def find_field(fields, name):
    return next((f for f in fields if f["name"].lower() == name.lower()), None)


def item_key(name):
    """The key gh gives a field in `item-list` output: the first word lower case, the others capitalized."""
    first, *rest = name.split()
    return first.lower() + "".join(w.capitalize() for w in rest)


def cmd_apply(args):
    root = Root(args.root)
    root.require_confirmed()
    cfg = root.config()
    if not vis.board_key(cfg):
        raise CrucibleError("no board is configured: tracker.kind is not github-project")
    require_approved_plan(root, cfg)
    plan = read_json(plan_path(root))
    owner, number = board_ref(cfg)
    repos = [vis.tracker_slug(cfg) or owner]
    authorize(root, "tracker_board", "board apply", repos=repos)
    adapter = get_adapter("github", root, cfg)
    live = adapter.list_fields(owner, number)
    missing = [f for f in plan["fields"] if not find_field(live, f["name"])]
    if missing:
        saved = backup(root, f"board-{owner}-{number}", json.dumps(
            {"fields": live, "items": adapter.list_items(owner, number)}, indent=2, ensure_ascii=False))
        print(f"board backed up before any change: {saved or 'backups are off'}")
    for field in missing:
        options = [str(v["value"]) for v in field["values"]] or None
        run_action(root, "tracker_board", f"create field {field['name']} on board:{owner}/{number}",
                   lambda f=field, o=options: adapter.create_field(owner, number, f["name"], o)["id"], repos=repos)
        print(f"field created: {field['name']}")
    for field in plan["fields"]:
        if field not in missing:
            print(f"field kept: {find_field(live, field['name'])['name']}")
            if field["add_values"]:
                print(f"options not added to {field['name']}: gh has no command to add options to an existing "
                      f"field; add by hand: {', '.join(map(str, field['add_values']))}")
    apply_views(root, plan, adapter, owner, number, repos)


def view_filter(view, plan_fields):
    """The board filter text for a plan view `Field = Value`; "" when the filter names no board field."""
    match = re.match(r"^(.+?) = (.+)$", view["filter"] or "")
    if not match or match.group(1) not in [f["name"] for f in plan_fields]:
        return ""
    return f'{match.group(1).lower().replace(" ", "-")}:"{match.group(2)}"'


def apply_views(root, plan, adapter, owner, number, repos):
    """Create the plan's views and set their filters (the API sets neither group by nor sort: those are listed)."""
    project = adapter.project_id(owner, number)
    live = adapter.list_fields(owner, number)
    field_ids = [f["id"] for f in live if f["name"] in ["Title"] + [p["name"] for p in plan["fields"]]]
    existing = {v["name"]: v for v in adapter.list_views(project)}
    expected = {}
    for view in plan["views"]:
        name, want = view["name"], view_filter(view, plan["fields"])
        found = existing.get(name)
        if found:
            print(f"view kept: {name}")
        else:
            found = run_action(root, "tracker_board", f"create view {name} on board:{owner}/{number}",
                               lambda v=view: adapter.create_view(project, v["name"], v["layout"], field_ids),
                               repos=repos)
            print(f"view created: {name} ({view['layout']})")
        if want and found.get("filter") != want:
            run_action(root, "tracker_board", f"update filter of view {name}",
                       lambda i=found["id"], f=want: adapter.set_view_filter(i, f), repos=repos)
            print(f"view filter set: {name} ({want})")
        elif view["filter"] and not want:
            print(f"view filter not set: {name}: {view['filter']!r} names no board field; set it on the board page")
        expected[name] = {"layout": view["layout"], "filter": want}
        print(f"view {name}: group by {view['group_by']} cannot be set through the API; set it on the board page")
    write_json(root.p("board", "views.json"), expected)


def view_problems(root, cfg, adapter):
    """Compare the views `board apply` made with what the board holds now."""
    expected = read_json(root.p("board", "views.json"))
    if not expected or not vis.board_key(cfg):
        return []
    owner, number = board_ref(cfg)
    try:
        live = {v["name"]: v for v in adapter.list_views(adapter.project_id(owner, number))}
    except CrucibleError as exc:
        return [f"cannot read the board views back: {exc}"]
    problems = []
    for name, want in sorted(expected.items()):
        if name not in live:
            problems.append(f"view {name} is not on the board")
            continue
        for key in ("layout", "filter"):
            if want[key] and (live[name].get(key) or "") != want[key]:
                problems.append(f"view {name}: {key} is {live[name].get(key)!r}, it was set to {want[key]!r}")
    return problems


def set_item_fields(root, cfg, adapter, fid, ref, repos, state):
    """Set the planned values on one filed item; -> {board field name: value} for the read-back at verify."""
    plan = read_json(plan_path(root))
    owner, number = board_ref(cfg)
    if not state:
        state.update(fields=adapter.list_fields(owner, number), project=adapter.project_id(owner, number))
    item = next((i for i in adapter.list_items(owner, number) if (i.get("content") or {}).get("url") == ref), None)
    if item is None:
        raise CrucibleError(f"{ref} is not on the board yet")
    written = {}
    for field in plan["fields"]:
        key = ITEM_VALUES.get(field["name"])
        if not key:
            continue
        live = find_field(state["fields"], field["name"])
        if not live:
            raise CrucibleError(f"the board has no field {field['name']}: run `crucible board apply` first")
        value = str(plan["items"][fid][key])
        run_action(root, "tracker_board", f"set {live['name']} on {ref}",
                   lambda f=live, v=value: adapter.set_item_field(state["project"], item["id"], f, v), repos=repos)
        written[live["name"]] = value
    return written


def read_back_problems(adapter, rows):
    """Compare the written field values of each (key, filed row) with what the board holds now."""
    problems, boards = [], {}
    for key, row in rows:
        if row["board"] not in boards:
            owner, _, number = row["board"][len("board:"):].partition("/")
            try:
                boards[row["board"]] = {(i.get("content") or {}).get("url"): i
                                        for i in adapter.list_items(owner, number)}
            except CrucibleError as exc:
                boards[row["board"]] = exc
        found = boards[row["board"]]
        if isinstance(found, CrucibleError):
            problems.append(f"{key}: cannot read the board back: {found}")
        elif row["ref"] not in found:
            problems.append(f"{key}: not on the board {row['board']}")
        else:
            for name, want in sorted(row["board_fields"].items()):
                got = found[row["ref"]].get(item_key(name))
                if str(got) != want:
                    problems.append(f"{key}: board field {name} is {got!r}, it was set to {want!r}")
    return problems


def cmd_board(args):
    return cmd_propose(args) if args.action == "propose" else cmd_apply(args)


def register(sub):
    p = sub.add_parser("board", help="propose the board from the research, or apply the approved plan")
    p.add_argument("action", choices=("propose", "apply"),
                   help="propose: write board/plan.json and print it; apply: create or map its fields")
    p.set_defaults(func=cmd_board)
