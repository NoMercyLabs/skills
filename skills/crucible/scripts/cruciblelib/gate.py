import glob
import os
import re

from . import brief
from .common import CrucibleError, Root, has_key_like, read_json
from .visibility import visibility_problems

SEVERITIES = ("critical", "high", "medium", "low")
SIZES = ("S", "M", "L")
KINDS = ("file", "route", "screen", "workflow", "config", "other")
FREQUENCIES = ("always", "often", "sometimes", "once", "unknown")
EVIDENCE_KINDS = ("file_line", "command")
PLACEHOLDERS = {"tbd", "?", "n/a", "na", "same as above", "todo", "-", "...", "…"}
BEFORE_YOU_FIX = ("current_behaviour", "callers", "consumers", "earlier_fixes", "instances")
MASKED_LINE = re.compile(r"^<[^<>]*masked>$", re.I)

def walk(node, path=""):
    """Every (path, string) leaf; `commit` fields hold SHAs and are skipped for key checks by the caller."""
    if isinstance(node, str):
        yield path, node
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from walk(value, f"{path}[{i}]")
    elif isinstance(node, dict):
        for key, value in node.items():
            if str(key).startswith("_"):
                continue
            yield from walk(value, f"{path}.{key}" if path else str(key))


def normalise(text):
    return " ".join(text.split())


def parse_ref(ref):
    """'path:12' or 'path:12-15' -> (path, a, b) or None."""
    m = re.match(r"^(.+?):(\d+)(?:-(\d+))?$", ref.strip())
    if not m:
        return None
    a = int(m.group(2))
    return m.group(1), a, int(m.group(3) or a)


def snapshot_range(root, repo, path, a, b):
    """Text of lines a..b of the snapshot, or None when the file or lines do not exist."""
    try:
        lines = root.snapshot_lines(repo, path)
    except CrucibleError:
        return None
    if a < 1 or b < a or b > len(lines):
        return None
    return normalise(" ".join(lines[a - 1:b]))


def quote_found(quote, text):
    for line in str(quote).split("\n"):
        line = normalise(line)
        if not line or MASKED_LINE.match(line):
            continue
        if line not in text:
            return False
    return True


def need_text(problems, value, name):
    if not isinstance(value, str) or not value.strip():
        problems.append(f"{name} is empty")
        return False
    return True


def need_group(problems, f, name, fields):
    group = f.get(name)
    if not isinstance(group, dict):
        problems.append(f"{name} is missing")
        return {}
    for field in fields:
        need_text(problems, group.get(field), f"{name}.{field}")
    return group


def need_list(problems, value, name, minimum=1):
    if not isinstance(value, list) or len(value) < minimum:
        problems.append(f"{name} needs at least {minimum} entry")
        return []
    return value


def check_evidence(root, f, problems, cited=None):
    """-> number of file_line evidence entries whose quote exists at the cited snapshot lines.
    `cited` collects the repos that have at least one good entry (an entry names its repo, default the finding's)."""
    good = 0
    for i, ev in enumerate(need_list(problems, f.get("evidence"), "evidence")):
        name = f"evidence[{i}]"
        if not isinstance(ev, dict):
            problems.append(f"{name} is not an object")
            continue
        if ev.get("kind") not in EVIDENCE_KINDS:
            problems.append(f"{name}.kind must be one of {', '.join(EVIDENCE_KINDS)}")
        ok_ref, ok_quote = need_text(problems, ev.get("ref"), f"{name}.ref"), need_text(problems, ev.get("quote"), f"{name}.quote")
        if ev.get("kind") != "file_line" or not (ok_ref and ok_quote):
            continue
        parsed = parse_ref(ev["ref"])
        if not parsed:
            problems.append(f"{name}.ref {ev['ref']!r} is not path:line")
            continue
        repo = ev.get("repo") or f.get("repo", "")
        text = snapshot_range(root, repo, *parsed)
        if text is None:
            problems.append(f"{name}: {ev['ref']} is not in the snapshot (file missing or line past the end)")
        elif not quote_found(ev["quote"], text):
            problems.append(f"{name}: the quote is not at {ev['ref']} in the snapshot")
        else:
            good += 1
            if cited is not None:
                cited.add(repo)
    return good


def cross_repo_problems(f, cfg, cited):
    """A finding about a contract between repos cites both sides: good evidence from its own repo and from every
    other repo it names (`cross_repo`) or cites."""
    problems = []
    declared = f.get("cross_repo")
    if declared is not None and (not isinstance(declared, list) or not declared
                                 or not all(isinstance(n, str) and n.strip() for n in declared)):
        return ["cross_repo is a list of repo names"]
    declared = list(declared or [])
    known = {r["name"] for r in cfg.get("repos", [])}
    for name in declared:
        if name not in known:
            problems.append(f"cross_repo: {name} is not a repo of this audit")
    cited_in_evidence = {ev.get("repo") for ev in f.get("evidence", []) if isinstance(ev, dict) and ev.get("repo")}
    for name in sorted(cited_in_evidence - {f.get("repo")} - set(declared)):
        problems.append(f"cross_repo: evidence cites {name} but it is not listed in cross_repo")
    if declared or cited_in_evidence - {f.get("repo")}:
        for name in [f.get("repo")] + sorted((set(declared) | cited_in_evidence) - {f.get("repo")}):
            if name in known and name not in cited:
                problems.append(f"cross_repo: no evidence from {name} (a quote at a real line of that repo is required)")
    return problems


def check_finding(root, f, cfg=None):
    """-> list of problems; empty means PASS."""
    cfg = cfg or root.config()
    problems = []
    if not isinstance(f, dict):
        return ["finding is not an object"]
    for field in ("id", "repo", "area"):
        need_text(problems, f.get(field), field)
    title = f.get("title")
    if need_text(problems, title, "title") and not 10 <= len(title) <= 120:
        problems.append("title must be 10-120 characters")
    goals = {g["id"] for g in cfg.get("goals", [])}
    if f.get("goal") not in goals:
        problems.append(f"goal must be one of the config goal ids {sorted(goals)}")
    if f.get("severity") not in SEVERITIES:
        problems.append(f"severity must be one of {', '.join(SEVERITIES)}")
    if f.get("size") not in SIZES:
        problems.append("size must be S, M or L")
    stages = list(cfg.get("stages", [])) + ["none"]
    if f.get("stage") not in stages:
        problems.append(f"stage must be one of {', '.join(stages)}")
    need_group(problems, f, "who", ("affected", "owner"))
    need_group(problems, f, "what", ("summary", "observed", "expected"))
    for i, w in enumerate(need_list(problems, f.get("where"), "where")):
        if not isinstance(w, dict) or w.get("kind") not in KINDS:
            problems.append(f"where[{i}].kind must be one of {', '.join(KINDS)}")
        else:
            need_text(problems, w.get("ref"), f"where[{i}].ref")
    when = need_group(problems, f, "when", ("trigger",))
    if when and when.get("frequency") not in FREQUENCIES:
        problems.append(f"when.frequency must be one of {', '.join(FREQUENCIES)}")
    why = need_group(problems, f, "why", ("cause",))
    if why and not isinstance(why.get("verified"), bool):
        problems.append("why.verified must be true or false")
    how = need_group(problems, f, "how", ("fix", "prove"))
    for i, step in enumerate(need_list(problems, how.get("reproduce") if how else None, "how.reproduce")):
        need_text(problems, step, f"how.reproduce[{i}]")
    cited = set()
    good_evidence = check_evidence(root, f, problems, cited)
    problems += cross_repo_problems(f, cfg, cited)
    for i, s in enumerate(need_list(problems, f.get("siblings"), "siblings")):
        need_text(problems, s, f"siblings[{i}]")
    not_checked = f.get("not_checked")
    if not isinstance(not_checked, list):
        problems.append("not_checked must be a list (empty when everything was checked)")
        not_checked = []
    if why and why.get("verified") is True and good_evidence == 0:
        problems.append("why.verified is true but no file_line evidence quote exists at real lines")
    if why and why.get("verified") is False and not any(str(n).startswith("cause:") for n in not_checked):
        problems.append("why.verified is false: not_checked needs an entry starting 'cause:'")
    if "before_you_fix" in f:
        block = f["before_you_fix"]
        for field in BEFORE_YOU_FIX:
            need_text(problems, block.get(field) if isinstance(block, dict) else None, f"before_you_fix.{field}")
    from . import rootcause  # imported here: rootcause borrows this module's helpers
    problems += rootcause.check_chain(root, f, cfg)
    problems += brief.intent_problems(root, f)
    problems += visibility_problems(f)
    problems += text_problems(f, cfg)
    return problems


def has_privacy_word(text, words):
    """True when any of the lowercased privacy words stands alone in the text."""
    lowered = text.lower()
    return any(re.search(r"(?<![a-z0-9])" + re.escape(word) + r"(?![a-z0-9])", lowered) for word in words)


def text_problems(f, cfg):
    problems = []
    words = [w.lower() for w in cfg.get("privacy_words", []) if str(w).strip()]
    for path, text in walk(f):
        if normalise(text).lower() in PLACEHOLDERS:
            problems.append(f"{path} is a placeholder ({text.strip()!r}); write the fact or 'not checked'")
        if has_privacy_word(text, words):
            problems.append(f"{path} holds a privacy word")
        if path.rsplit(".", 1)[-1] == "commit":
            continue
        masked = "\n".join(ln for ln in text.split("\n") if not MASKED_LINE.match(ln.strip()))
        if has_key_like(masked):
            problems.append(f"{path} holds a key-like string; replace it with a line '<token, masked>'")
    return problems


def finding_files(root, explicit, candidates):
    """[(label, finding)] for the gate to judge."""
    out = []
    if explicit:
        for path in explicit:
            data = read_json(path)
            if data is None:
                raise CrucibleError(f"no such file: {path}")
            for i, item in enumerate(data if isinstance(data, list) else [data]):
                out.append((f"{path}#{i}" if isinstance(data, list) else path, item))
        return out
    if candidates:
        for path in sorted(glob.glob(root.p("candidates", "*.json"))):
            unit = os.path.basename(path)[:-5]
            for i, item in enumerate(read_json(path, [])):
                title = item.get("title", "") if isinstance(item, dict) else ""
                out.append((f"{unit}[{i}] {title[:40]}", item))
        return out
    return [(fid, f) for fid, f in root.findings().items()]


def run_gate(root, items):
    """Print PASS or FAIL per item; -> number of failures."""
    cfg = root.config()
    failed = 0
    for label, f in items:
        problems = check_finding(root, f, cfg)
        if problems:
            failed += 1
            print(f"FAIL {label}")
            for p in problems:
                print(f"  {p}")
        else:
            print(f"PASS {label}")
    return failed


def cmd_gate(args):
    root = Root(args.root)
    root.require_confirmed()
    items = finding_files(root, args.finding, args.candidates)
    if not items:
        print("gate: nothing to check")
        return 0
    failed = run_gate(root, items)
    print(f"gate: {len(items) - failed} of {len(items)} pass")
    return 1 if failed else 0


def register(sub):
    p = sub.add_parser("gate", help="check findings against the schema, privacy words and key-like strings")
    p.add_argument("finding", nargs="*", help="finding JSON files (default: every accepted finding)")
    p.add_argument("--candidates", action="store_true", help="check every candidate instead")
    p.set_defaults(func=cmd_gate)
