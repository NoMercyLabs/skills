import copy
import glob
import re

from . import brief, rootcause
from .common import CrucibleError, Root, read_json, source_id, write_json
from .gate import check_finding
from .inventory import mark_coverage

# A reject must leave no defect: a reason that calls the defect real, latent or "a different bug" is a fix.
REAL_DEFECT = re.compile(r"\b(?:is|are|remains?) (?:still )?real\b|\blatent\b|\breal (?:defect|bug|issue|consequence)\b"
                         r"|\b(?:different|separate|another) (?:finding|defect|bug|issue)\b|\bthe opposite\b", re.I)
CHECKED = re.compile(r"^(?:(?P<pin>[\w.-]+@[0-9a-f]{6,40}):)?(?P<path>[^\s:]+?):(?P<nums>\d+(?:[-,]\d+)*)"
                     r"(?:\s*\(.*\))?$")
VERDICTS = ("accept", "reject", "fix")
LEAD_VERDICTS = ("real", "cleared")
ADDABLE = {"before_you_fix", "labels", "not_checked", "siblings"}


def cand_source(unit, cand):
    # a fix may change the title; the verifier judged the candidate under its first id
    return cand.get("_source") or source_id(unit, cand)


def load_verdicts(root, unit):
    merged = dict(root.verdicts(unit))
    for path in sorted(glob.glob(root.p("review", f"verdicts-{unit}-*.json"))):
        merged.update(read_json(path, {}))
    return merged


def path_keys(dotted):
    keys = [int(k) if k.isdigit() else k for k in re.findall(r"[^.\[\]]+", dotted)]
    if not keys:
        raise CrucibleError(f"fix path {dotted!r} is empty")
    return keys


def set_path(obj, dotted, value):
    """Set a dotted path (a.b, a.0.b or a[0].b). The path must exist; only a few fields may be added."""
    keys = path_keys(dotted)
    node = obj
    for k in keys[:-1]:
        try:
            node = node[k]
        except (KeyError, IndexError, TypeError):
            raise CrucibleError(f"fix path {dotted!r}: {k!r} does not exist in the candidate")
    last = keys[-1]
    if isinstance(node, list):
        if not isinstance(last, int) or not 0 <= last < len(node):
            raise CrucibleError(f"fix path {dotted!r}: no entry {last!r}")
    elif isinstance(node, dict):
        if last not in node and not (len(keys) == 1 and last in ADDABLE) and keys[0] != "before_you_fix":
            raise CrucibleError(f"fix path {dotted!r}: the candidate has no field {last!r}")
    else:
        raise CrucibleError(f"fix path {dotted!r}: cannot set a field inside a text value")
    node[last] = value


def checked_problems(root, repo, entries):
    bad = []
    for entry in entries:
        m = CHECKED.match(str(entry).strip())
        if not m:
            bad.append(f"checked entry {entry!r} is not path:line")
            continue
        if m.group("pin"):
            continue
        path = m.group("path")
        number = max(int(n) for n in re.findall(r"\d+", m.group("nums")))
        for candidate_path in (path, path[len(repo) + 1:] if path.startswith(repo + "/") else path):
            try:
                total = len(root.snapshot_lines(repo, candidate_path))
            except CrucibleError:
                continue
            if not 1 <= number <= total:
                bad.append(f"checked {entry} is past the end of the file ({total} lines)")
            break
    return bad


def check_verdicts(root, unit, only=None):
    """-> (problems, judged, total) for the unit's candidates and dropped leads."""
    repo = root.unit(unit)["repo"]
    cands = root.candidates(unit)
    by_src = {cand_source(unit, c): c for c in cands}
    verdicts = load_verdicts(root, unit)
    sources = list(only or by_src)
    bad = []
    for s in sources:
        v = verdicts.get(s)
        if s not in by_src:
            bad.append(f"{s}: no such candidate")
            continue
        if not isinstance(v, dict) or v.get("verdict") not in VERDICTS or not str(v.get("reason", "")).strip() \
                or not v.get("checked"):
            bad.append(f"{s}: no final verdict with reason and checked lines")
            continue
        if v["verdict"] == "reject":
            if str(v.get("other_defect", "")).strip().lower() != "none":
                bad.append(f"{s}: a reject needs \"other_defect\": \"none\"; a different real defect in the same code is a fix")
                continue
            if REAL_DEFECT.search(str(v["reason"])):
                bad.append(f"{s}: a reject whose reason says the defect is real; a real but overstated defect is a fix")
                continue
        if v["verdict"] == "fix":
            fix = v.get("fix")
            if not isinstance(fix, dict) or not fix:
                bad.append(f"{s}: a fix needs a 'fix' object of dotted field paths")
                continue
            trial = copy.deepcopy(by_src[s])
            try:
                for field, value in fix.items():
                    set_path(trial, field, value)
            except CrucibleError as exc:
                bad.append(f"{s}: {exc}")
                continue
        found = checked_problems(root, repo, v["checked"] if isinstance(v["checked"], list) else [v["checked"]])
        bad += [f"{s}: {b}" for b in found]
        if v["verdict"] != "reject":
            final = trial if v["verdict"] == "fix" else by_src[s]
            bad += [f"{s}: {b}" for b in rootcause.verdict_link_problems(final, v)]
    ledger = root.ledger(unit) or {}
    seen = verdicts.get("_leads", {})
    leads = ledger.get("leads") or []
    for lead in leads:
        ref = str(lead.get("ref"))
        v = seen.get(ref)
        if not isinstance(v, dict) or v.get("verdict") not in LEAD_VERDICTS or not str(v.get("reason", "")).strip():
            bad.append(f"lead {ref}: no verdict (real or cleared) with a reason in _leads")
            continue
        checked = v.get("checked") or []
        bad += [f"lead {ref}: {b}" for b in checked_problems(root, repo, checked if isinstance(checked, list) else [checked])]
    failed = {b.split(":")[0] for b in bad}
    total = len(sources) + len(leads)
    return bad, total - len(failed), total


def cmd_verdict_check(args):
    root = Root(args.root)
    root.require_confirmed()
    bad, judged, total = check_verdicts(root, args.unit)
    for b in bad:
        print("  " + b)
    print(f"{'FAIL' if bad else 'PASS'} {args.unit}: {judged} of {total} judged")
    return 1 if bad else 0


def next_finding_id(root, state):
    taken = set(root.findings()) | set(state["accepted"].values())
    # max + 1, never a gap: an id once given belongs to its filed copy even if the file is gone
    highest = max((int(t[2:]) for t in taken if re.fullmatch(r"F-\d+", t)), default=0)
    return f"F-{highest + 1:04d}"


def apply_fixes(root, unit):
    """Store every verifier fix in the candidate file; running it again changes nothing."""
    cands = root.candidates(unit)
    verdicts = load_verdicts(root, unit)
    changed = False
    for c in cands:
        src = cand_source(unit, c)
        v = verdicts.get(src, {})
        if v.get("verdict") != "fix":
            continue
        c.setdefault("_source", src)
        before = copy.deepcopy(c)
        for field, value in v["fix"].items():
            set_path(c, field, value)
        changed = changed or c != before
    if changed:
        write_json(root.p("candidates", unit + ".json"), cands)
    return cands


def cmd_accept(args):
    root = Root(args.root)
    root.require_confirmed()
    unit = args.unit
    root.unit(unit)
    state = root.state()
    entry = state["units"].setdefault(unit, {"status": "pending"})
    if entry.get("status") == "done":
        print(f"ACCEPT {unit}: already done")
        return 0
    if entry.get("proof") != "pass":
        print(f"ACCEPT REFUSED {unit}: proof has not passed for this unit; run `crucible proof {unit} TRANSCRIPT` first")
        return 1
    bad, judged, total = check_verdicts(root, unit)
    if bad:
        for b in bad:
            print("  " + b)
        print(f"ACCEPT REFUSED {unit}: verdict-check FAIL, {judged} of {total} judged")
        return 1
    cands = apply_fixes(root, unit)
    verdicts = load_verdicts(root, unit)
    promoted, routed, failed, route_failed = [], [], 0, 0
    cfg = root.config()
    for c in cands:
        src = cand_source(unit, c)
        if verdicts[src]["verdict"] == "reject":
            continue
        kind = c.get("intent_kind")
        if kind in brief.ROUTED_KINDS and not (kind == "accepted_risk" and args.file_accepted_risks):
            # The brief says not to file it: the gate still judges it, then it goes to the report.
            problems = check_finding(root, {k: v for k, v in c.items() if not k.startswith("_")}, cfg)
            if problems:
                failed += 1
                route_failed += 1
                print(f"FAIL {src}")
                for p in problems:
                    print(f"  {p}")
            else:
                brief.route_candidate(root, unit, src, c)
                routed.append(src)
            continue
        fid = state["accepted"].get(src) or next_finding_id(root, state)
        finding = {k: v for k, v in c.items() if not k.startswith("_")}
        finding["id"] = fid
        finding["source"] = src
        write_json(root.p("findings", fid + ".json"), finding)
        state["accepted"][src] = fid
        root.save_state(state)
        promoted.append(fid)
    for fid in promoted:
        problems = check_finding(root, root.findings()[fid], cfg)
        if problems:
            failed += 1
            print(f"FAIL {fid}")
            for p in problems:
                print(f"  {p}")
    if failed:
        print(f"ACCEPT REFUSED {unit}: the gate failed {failed} of {len(promoted) + route_failed} findings; "
              f"fix the candidates and run accept again")
        return 1
    rejected = sum(1 for c in cands if verdicts[cand_source(unit, c)]["verdict"] == "reject")
    routed_note = f", {len(routed)} not filed because of the brief (see `crucible report`)" if routed else ""
    entry["status"] = "done"
    entry["reason"] = f"{len(promoted)} accepted, {rejected} rejected" + (f", {len(routed)} routed" if routed else "")
    root.save_state(state)
    mark_coverage(root, unit, "done")
    print(f"ACCEPT {unit}: {len(promoted)} findings promoted ({', '.join(promoted) or 'none'}), {rejected} rejected{routed_note}")
    return 0


def register(sub):
    p = sub.add_parser("verdict-check", help="check the verifier's verdicts for a unit")
    p.add_argument("unit")
    p.set_defaults(func=cmd_verdict_check)
    p = sub.add_parser("accept", help="promote accepted candidates of a unit to findings")
    p.add_argument("unit")
    p.add_argument("--file-accepted-risks", action="store_true",
                   help="file findings that match a risk the user accepted (the user asked for them)")
    p.set_defaults(func=cmd_accept)
