"""`file --dry-run`, `file --apply`, `file --verify`: findings go to the tracker the user chose, nowhere else.

Every write is authorized by a grant (permissions.run_action) and logged. A private finding, or any text from
it, never reaches a public destination; a public pointer says only that a private report exists.
"""
import hashlib
import json

from . import board, rootcause
from . import visibility as vis
from .common import CrucibleError, Root, read_json, write_json
from .permissions import (authorize, dryrun_hashes, log_action, record_dryrun, refuse, require_approved,
                          run_action)
from .trackers import get_adapter
from .trackers.base import text_digest

POINTER_TITLE = "A private report exists"
POINTER_BODY = "A private report exists for this repository. Details are not public."
GROUP_OF = {"issue": "tracker_issues", "pointer": "tracker_issues", "advisory": "tracker_advisories"}
MIN_LEAK_TOKEN = 8


def render_body(f):
    where = "\n".join(f"- {w['kind']}: {w['ref']}" for w in f["where"])
    evidence = "\n".join(f"- `{e['ref']}`: {e['quote']}" for e in f["evidence"])
    steps = "\n".join(f"{i}. {s}" for i, s in enumerate(f["how"]["reproduce"], 1))
    sections = [
        ("Summary", f["what"]["summary"]), ("Observed", f["what"]["observed"]),
        ("Expected", f["what"]["expected"]), ("Where", where),
        ("When", f"{f['when']['trigger']} ({f['when']['frequency']})"),
        ("Cause", f["why"]["cause"] + (" (verified)" if f["why"]["verified"] else " (not verified)")),
        ("Root cause", rootcause.render_chain(f)), ("Do not fix by", rootcause.render_do_not_fix_by(f)),
        ("Reproduce", steps), ("Fix", f["how"]["fix"]), ("Prove", f["how"]["prove"]),
        ("Evidence", evidence), ("Siblings", "\n".join(f"- {s}" for s in f["siblings"])),
        ("Not checked", "\n".join(f"- {s}" for s in f["not_checked"]) or "nothing"),
        ("Affected", f"{f['who']['affected']}; owner: {f['who']['owner']}"),
        ("Severity", f"{f['severity']}, size {f['size']}"),
    ]
    return "\n\n".join(f"## {name}\n{text}" for name, text in sections)


def repo_entry(cfg, name):
    for entry in cfg.get("repos", []):
        if entry["name"] == name:
            return entry
    raise CrucibleError(f"finding repo {name!r} is not in the config repos")


def github_target(cfg, entry):
    slug = vis.tracker_slug(cfg) or vis.repo_slug(entry)
    if "/" not in slug:
        raise CrucibleError(f"repo {entry['name']} has no remote owner/name: name the tracker repo in "
                            "tracker.owner and tracker.repo")
    return slug


def make_action(kind, fid, f, target, destination, board=None, **extra):
    key = f"{kind}:{target}:{fid}"
    action = {"kind": kind, "key": key, "finding": fid, "target": target, "destination": destination,
              "visibility": f["visibility"] if f else "pointer", "title": "", "body": "", "labels": [],
              "assignee": "", "board": board or ""}
    if f:
        action.update(title=f["title"], body=render_body(f), labels=list(f.get("labels") or []))
    action.update(extra)
    return action


def build_plan(root, cfg=None, findings=None):
    """The deterministic list of writes for the accepted findings, from the user's confirmed answers only."""
    cfg = cfg or root.config()
    findings = root.findings() if findings is None else findings
    sec = vis.section(cfg)
    actions, pointers = [], set()
    github = vis.is_github_tracker(cfg)
    for fid, f in sorted(findings.items()):
        problems = vis.visibility_problems(f)
        if problems:
            raise CrucibleError(f"refused: finding {fid}: {problems[0]}")
        private = f["visibility"] == "private"
        if not github:
            actions.append(make_action("markdown", fid, f, "local", "local"))
            continue
        entry = repo_entry(cfg, f["repo"])
        target = github_target(cfg, entry)
        target_vis = vis.need_confirmed(cfg, target)
        board = vis.board_key(cfg)
        board_vis = vis.need_confirmed(cfg, board) if board else ""
        owner_row = (cfg.get("owners") or {}).get(f["repo"]) or {}
        assignee = owner_row.get("assignee", "") if isinstance(owner_row, dict) else ""
        exploitable = any(r.startswith("exploitable") for r in vis.forced_private_reasons(f))
        needs_private_place = private and (target_vis == "public" or (
            exploitable and sec.get("collaborators_see_security") is False))
        if not needs_private_place:
            use_board = board if board and not (private and board_vis == "public") and not (
                board_vis == "public" and sec.get("public_board_items") is not True) else ""
            actions.append(make_action("issue", fid, f, target, target_vis, board=use_board, assignee=assignee))
            continue
        dest = cfg.get("private_destination") or {}
        if not vis.private_destination_answered(cfg):
            raise CrucibleError("refused: the user has not said where private findings go: ask, then "
                                "`crucible answer private_destination ... --words`")
        if dest["kind"] == "local_report":
            actions.append(make_action("markdown", fid, f, "local", "local"))
        elif dest["kind"] == "advisory":
            repo_target = vis.repo_slug(entry)
            if "/" not in repo_target:
                raise CrucibleError(f"repo {entry['name']} has no remote owner/name for an advisory")
            actions.append(make_action("advisory", fid, f, repo_target, vis.need_confirmed(cfg, repo_target)))
        else:
            repo = dest.get("repo") or ""
            if vis.need_confirmed(cfg, repo) != "private":
                raise CrucibleError(f"refused: the private destination {repo} is not confirmed private")
            actions.append(make_action("issue", fid, f, repo, "private", assignee=assignee))
        if sec.get("pointers") is True and target_vis == "public" and target not in pointers:
            pointers.add(target)
            actions.append(make_action("pointer", "pointer", None, target, "public", title=POINTER_TITLE,
                                       body=POINTER_BODY))
    return actions


def plan_hash(actions):
    text = json.dumps(actions, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def render_plan(actions):
    lines = [f"{len(actions)} writes planned"]
    for a in actions:
        label = a["finding"] if a["kind"] != "pointer" else "pointer"
        lines.append(f"  {a['kind']} {label} -> {a['target']} ({a['destination']}, "
                     f"{a['visibility']} finding): {a['title']}")
    return "\n".join(lines)


def cmd_dry_run(root):
    root.require_confirmed()
    actions = build_plan(root)
    digest = plan_hash(actions)
    record_dryrun(root, digest, actions)
    print(render_plan(actions))
    print(f"plan hash: {digest}")
    if root.config().get("auto_file") is True:
        print("auto_file is on: `file --apply` runs this plan within the granted bounds without asking again")
    else:
        print(f"show this list to the user; after their go run `crucible approve {digest}`, then `file --apply`")


def adapters(root, cfg):
    cache = {}

    def get(kind):
        name = "markdown" if kind == "markdown" else "github"
        if name not in cache:
            cache[name] = get_adapter(name, root, cfg)
        return cache[name]
    return get


def recheck_visibility(root, cfg, adapter, action):
    """Right before a write: the destination may have turned public since the interview; never write then."""
    group = GROUP_OF.get(action["kind"], "tracker_issues")
    if action["kind"] == "markdown":
        return
    confirmed = vis.need_confirmed(cfg, action["target"])
    if action["visibility"] == "private" and confirmed == "public":
        refuse(root, group, action["key"], "a private finding may never go to a public destination")
    live = adapter.visibility(action["target"])
    if live != confirmed and live == "public":
        refuse(root, group, action["key"], f"{action['target']} is now public (confirmed {confirmed}): filing "
                                           "stops; ask the user and confirm the visibility again")
    if action["board"]:
        board_live = adapter.board_visibility(*action["board"][len("board:"):].split("/", 1))
        if board_live == "public" and action["visibility"] != "public":
            refuse(root, "tracker_board", action["key"], "private findings never go on a public board")
        if vis.need_confirmed(cfg, action["board"]) == "private" and board_live == "public":
            refuse(root, "tracker_board", action["key"], f"{action['board']} is now public")


def quota(actions):
    """group -> (repos, count) so the grant bounds are checked for the whole plan before the first write."""
    need = {}
    for a in actions:
        if a["kind"] == "markdown":
            continue
        group = GROUP_OF[a["kind"]]
        repos, count = need.setdefault(group, ([], 0))
        need[group] = (repos + [a["target"]], count + 1)
        if a["board"]:
            repos, count = need.setdefault("tracker_board", ([], 0))
            need["tracker_board"] = (repos + [a["target"]], count + 1)
    return need


def cmd_apply(root):
    root.require_confirmed()
    cfg = root.config()
    board.require_approved_plan(root, cfg)
    actions = build_plan(root, cfg)
    digest = plan_hash(actions)
    if digest not in dryrun_hashes(root):
        refuse(root, "tracker_issues", f"apply plan {digest}",
               "no dry run of this exact plan: the plan is new or changed since the dry run; run "
               "`file --dry-run`, show the list to the user, then apply")
    require_approved(root, digest)
    for group, (repos, count) in quota(actions).items():
        authorize(root, group, f"apply plan {digest}", repos=sorted(set(repos)), count=count)
    get = adapters(root, cfg)
    filed = read_json(root.p("filed.json"), {})
    board_state = {}
    done = 0
    for action in actions:
        if action["key"] in filed:
            continue
        adapter = get(action["kind"])
        if action["kind"] == "markdown":
            ref = adapter.create(action)
            log_action(root, "tracker_issues", f"write {action['key']}", ref, "ok")
        else:
            recheck_visibility(root, cfg, adapter, action)
            target = action["target"]
            for label in action["labels"] if action["kind"] == "issue" else []:
                run_action(root, "tracker_labels", f"label {label} on {target}",
                           lambda l=label: adapter.create_label(target, l), repos=[target], labels=[label])
            group = GROUP_OF[action["kind"]]
            want = {"repos": [target]}
            if action["assignee"]:
                authorize(root, "tracker_assignees", action["key"], assignees=[action["assignee"]])
            ref = run_action(root, group, f"create {action['kind']} on {target} for {action['finding']}",
                             lambda a=action: adapter.create(a), **want)
            if action["board"]:
                run_action(root, "tracker_board", f"add {ref} to {action['board']}",
                           lambda a=action, r=ref: adapter.add_to_board(a, r), repos=[target])
                board_fields = board.set_item_fields(root, cfg, adapter, action["finding"], ref, [target],
                                                     board_state)
        stored = adapter.read(action["kind"], action["target"], ref)
        filed[action["key"]] = {"kind": action["kind"], "finding": action["finding"], "target": action["target"],
                                "ref": ref, "destination": action["destination"],
                                "visibility": action["visibility"],
                                "digest": text_digest(action["title"], action["body"]),
                                "stored_digest": text_digest(stored["title"], stored["body"])}
        if action["kind"] != "markdown" and action["board"]:
            filed[action["key"]].update(board=action["board"], board_fields=board_fields)
        write_json(root.p("filed.json"), filed)
        done += 1
        print(f"filed {action['kind']} {action['finding']} -> {action['target']}: {ref}")
    print(f"{done} writes done, {len(actions) - done} already filed")


def leak_tokens(finding):
    tokens = [finding.get("title", ""), finding.get("what", {}).get("summary", "")]
    tokens += [w.get("ref", "") for w in finding.get("where", []) if isinstance(w, dict)]
    return [t for t in tokens if len(t) >= MIN_LEAK_TOKEN]


def cmd_verify(root):
    root.require_confirmed()
    cfg = root.config()
    filed = read_json(root.p("filed.json"), {})
    if not filed:
        raise CrucibleError("nothing is filed yet: run `file --apply` first")
    get = adapters(root, cfg)
    private_findings = {fid: f for fid, f in root.findings().items() if f.get("visibility") == "private"}
    problems, public_texts = [], []
    for key, row in sorted(filed.items()):
        adapter = get(row["kind"])
        try:
            read = adapter.read(row["kind"], row["target"], row["ref"])
        except CrucibleError as exc:
            problems.append(f"{key}: cannot read back: {exc}")
            continue
        if text_digest(read["title"], read["body"]) != row["stored_digest"]:
            problems.append(f"{key}: the stored text changed since it was written")
        if text_digest(read["title"], read["body"]) != row["digest"]:
            problems.append(f"{key}: the stored text is not what was planned")
        live = "local" if row["kind"] == "markdown" else adapter.visibility(row["target"])
        if row["visibility"] == "private" and live == "public":
            problems.append(f"{key}: a private finding sits in a public destination ({row['target']})")
        if live == "public":
            public_texts.append((key, row["kind"], read["title"] + "\n" + read["body"]))
    on_board = [(key, row) for key, row in sorted(filed.items()) if row.get("board_fields")]
    if on_board:
        problems += board.read_back_problems(get("issue"), on_board)
        problems += board.view_problems(root, cfg, get("issue"))
    for key, kind, text in public_texts:
        lowered = text.lower()
        for fid, f in sorted(private_findings.items()):
            if any(t.lower() in lowered for t in leak_tokens(f)):
                problems.append(f"{key}: text of private finding {fid} is in a public place")
        if kind == "pointer" and text != POINTER_TITLE + "\n" + POINTER_BODY:
            problems.append(f"{key}: a public pointer says more than that a private report exists")
    if problems:
        for p in problems:
            print("VERIFY FAIL: " + p)
        return 1
    print(f"VERIFY PASS: {len(filed)} filed items read back; every destination matches its finding")
    return 0


def counts(root):
    """-> ({visibility: n}, {destination: n}) of what was filed."""
    by_vis, by_dest = {}, {}
    for row in read_json(root.p("filed.json"), {}).values():
        by_vis[row["visibility"]] = by_vis.get(row["visibility"], 0) + 1
        by_dest[row["target"]] = by_dest.get(row["target"], 0) + 1
    return by_vis, by_dest


def cmd_file(args):
    root = Root(args.root)
    if args.dry_run:
        return cmd_dry_run(root)
    if args.apply:
        return cmd_apply(root)
    return cmd_verify(root)


def register(sub):
    p = sub.add_parser("file", help="plan, apply or verify the filing of accepted findings")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="list every write and print the plan hash")
    mode.add_argument("--apply", action="store_true", help="write the dry-run plan (needs approval unless auto_file)")
    mode.add_argument("--verify", action="store_true", help="read every filed item back and check it")
    p.set_defaults(func=cmd_file)
