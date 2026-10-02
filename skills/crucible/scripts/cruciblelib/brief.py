import re

from .common import CrucibleError, Root, is_secret_file, read_json, write_json
from .inventory import walk_text_files
from .permissions import now

# The seven questions of the project brief, in the order the user is asked, each with the reason it is asked.
FIELDS = ("purpose", "good", "intentional", "must_never_change", "accepted_risks", "out_of_scope", "known_issues")
QUESTIONS = {
    "purpose": "What is the project for, and who uses it?",
    "good": "What does \"good\" mean for you: what must always work?",
    "intentional": "What is intentional, even if it looks odd (design choices, trade-offs, known limits)?",
    "must_never_change": "What must never change (public contracts, data formats, compatibility promises, "
                         "behaviour users rely on)?",
    "accepted_risks": "Which risks have you accepted on purpose?",
    "out_of_scope": "What is out of scope or not a goal?",
    "known_issues": "Known issues you already track or decided not to fix?",
}
NO_CONFLICT = "no conflict with the brief"
# How a finding relates to the brief: the routing decides what happens to it.
KINDS = ("conflicts_intent", "accepted_risk", "out_of_scope", "related")
KIND_FIELDS = {"accepted_risk": ("accepted_risks",), "out_of_scope": ("out_of_scope",),
               "conflicts_intent": ("purpose", "good", "intentional", "must_never_change")}
ROUTED_KINDS = ("conflicts_intent", "accepted_risk", "out_of_scope")
MANIFESTS = ("package.json", "pyproject.toml", "setup.py", "setup.cfg", "cargo.toml", "composer.json", "go.mod",
             "pom.xml", "build.gradle", "build.gradle.kts", "gemfile", "mix.exs", "pubspec.yaml")
DOC_FOLDERS = ("docs", "doc", "documentation")
ADR_FOLDERS = ("adr", "adrs", "decisions")
DOC_SUFFIXES = (".md", ".rst", ".txt", ".adoc")
NOTE_PREFIXES = {"contributing": "contributing", "security": "security", "architecture": "architecture",
                 "code_of_conduct": "contributing", "governance": "contributing"}
MAX_SOURCES_PER_REPO = 300
NO_BRIEF = ("no confirmed project brief: ask the user the seven questions (references/interview.md, section 0), "
            "record each with `crucible brief answer FIELD --words ...`, then run `crucible brief confirm`")


def path_of(root):
    return root.p("brief.json")


def load(root):
    data = read_json(path_of(root), None) or {}
    data.setdefault("sources", [])
    data.setdefault("answers", {})
    data.setdefault("summary", [])
    data.setdefault("confirmed", False)
    return data


def save(root, data):
    write_json(path_of(root), data)
    with open(root.p("project-brief.md"), "w", encoding="utf-8") as fh:
        fh.write(render(data))


def classify(rel):
    """The kind of self-description file at this relative path, or None."""
    parts = rel.lower().split("/")
    name = parts[-1]
    stem = name.rsplit(".", 1)[0]
    if len(parts) <= 3 and stem.startswith("readme"):
        return "readme"
    if len(parts) <= 3 and (name in MANIFESTS or name.endswith(".csproj")):
        return "manifest"
    if any(part in ADR_FOLDERS for part in parts[:-1]) and name.endswith(DOC_SUFFIXES):
        return "adr"
    if len(parts) <= 3 and name.endswith(DOC_SUFFIXES):
        for prefix, kind in NOTE_PREFIXES.items():
            if stem.startswith(prefix):
                return kind
    if parts[0] in DOC_FOLDERS and len(parts) > 1:
        return "docs"
    return None


def collect_sources(cfg):
    """[{repo, path, kind}]: the files a project describes itself with. Paths only; secret files never appear
    because the walk skips them and no file is opened here."""
    found = []
    skip = cfg.get("scope", {}).get("skip", [])
    for repo in cfg["repos"]:
        rows = []
        for rel, _full, _size in walk_text_files(repo["path"], skip=skip):
            kind = classify(rel)
            if kind and not is_secret_file(rel):
                rows.append({"repo": repo["name"], "path": rel, "kind": kind})
        found += rows[:MAX_SOURCES_PER_REPO]
    return found


def label(entry):
    return f"{entry['repo']}/{entry['path']}"


def is_confirmed(root):
    return bool(load(root)["confirmed"])


def require_confirmed(root):
    if not is_confirmed(root):
        raise CrucibleError(NO_BRIEF)


def norm(text):
    return " ".join(str(text).split()).lower()


def render(data):
    lines = ["# Project brief", ""]
    if data["confirmed"]:
        lines.append(f"Status: confirmed by the user at {data.get('confirmed_at', '')}.")
    else:
        lines.append("Status: not confirmed. The user has not confirmed this brief yet.")
    lines += ["", "## The user's answers, verbatim", ""]
    for field in FIELDS:
        row = data["answers"].get(field)
        lines += [f"### {field}", f"Question: {QUESTIONS[field]}", ""]
        lines.append(row["words"] if row else "(not answered)")
        lines.append("")
    lines += ["## Summary of what the project says about itself (agent-written, not confirmed)", ""]
    if data["summary"]:
        lines += [f"- {row['line']} ({row['source']})" for row in data["summary"]]
    else:
        lines.append("(no summary written)")
    lines += ["", "## Sources the project describes itself with (paths only)", ""]
    lines += [f"- {label(entry)} ({entry['kind']})" for entry in data["sources"]] or ["(not collected)"]
    return "\n".join(lines) + "\n"


def must_never_items(data):
    row = data["answers"].get("must_never_change")
    if not row:
        return []
    return [item.strip() for item in re.split(r"[\n;]+", row["words"]) if item.strip()]


def path_tokens(item):
    tokens = []
    for raw in item.split():
        tok = raw.strip(",;:()'\"`")
        if "/" in tok or re.search(r"\.\w+$", tok):
            tokens.append(tok)
    return tokens


def touches_item(touch, item):
    t = norm(touch).replace("\\", "/")
    if not t:
        return False
    if t in norm(item):
        return True
    for tok in path_tokens(item):
        tok = tok.lower().strip("/")
        if "/" in tok:
            if ("/" + tok) in ("/" + t):
                return True
        elif t.rsplit("/", 1)[-1] == tok:
            return True
    return False


def fix_plan_problems(root, plan):
    """Problems that stop a fix plan: a plan must list what it `touches`, and none of it may be an item
    the user said must never change. Empty list means the plan may go on."""
    touches = plan.get("touches") if isinstance(plan, dict) else None
    if not isinstance(touches, list) or not touches:
        return ["the fix plan has no `touches` list: name every file, setting or behaviour the fix changes, "
                "so it can be checked against the project brief"]
    items = must_never_items(load(root))
    problems = []
    for touch in touches:
        for item in items:
            if touches_item(str(touch), item):
                problems.append(f"refused: the fix touches {touch!r}, which the user said must never change "
                                f"({item!r}); ask the user instead of changing it")
    return problems


def intent_problems(root, finding):
    """Problems with the finding's intent fields; empty list means the finding states how it meets the brief."""
    problems = []
    intent = finding.get("intent")
    kind = finding.get("intent_kind")
    if not isinstance(intent, str) or not intent.strip():
        return [f"intent is empty: write '{NO_CONFLICT}' after checking the brief, or the brief line it relates to "
                "as 'FIELD: the line' with intent_kind"]
    if norm(intent) == NO_CONFLICT:
        if kind is not None:
            problems.append(f"intent_kind {kind!r} given with intent '{NO_CONFLICT}': drop intent_kind, or name "
                            "the brief line")
        return problems
    if kind not in KINDS:
        return [f"intent_kind must be one of {', '.join(KINDS)} when intent names a brief line"]
    field, _, line = intent.partition(":")
    field = field.strip()
    answers = load(root)["answers"]
    row = answers.get(field)
    if field not in FIELDS or not norm(line):
        return [f"intent must be '{NO_CONFLICT}' or 'FIELD: a line of the project brief' (FIELD is one of "
                f"{', '.join(FIELDS)})"]
    if not row or norm(line) not in norm(row["words"]):
        return [f"intent line is not in the project brief under {field}: quote what the user said"]
    if kind in KIND_FIELDS and field not in KIND_FIELDS[kind]:
        problems.append(f"intent_kind {kind} relates to {', '.join(KIND_FIELDS[kind])}, not {field}")
    return problems


def routed(root):
    return read_json(root.p("routing.json"), {})


def route_candidate(root, unit, source, finding):
    """Store a finding the brief says not to file; running it again changes nothing."""
    rows = routed(root)
    where = (finding.get("where") or [{}])[0].get("ref", "")
    rows[source] = {"unit": unit, "kind": finding["intent_kind"], "title": finding.get("title", ""),
                    "intent": finding["intent"], "where": where, "at": rows.get(source, {}).get("at") or now()}
    write_json(root.p("routing.json"), rows)


def routing_lines(root):
    """The report sections for findings that were not filed because of the brief."""
    rows = routed(root)
    by_kind = {kind: [(src, row) for src, row in sorted(rows.items()) if row["kind"] == kind]
               for kind in ROUTED_KINDS}
    lines = []
    questions = by_kind["conflicts_intent"]
    lines.append(f"questions for you: {len(questions)}")
    for src, row in questions:
        field, _, said = row["intent"].partition(":")
        lines.append(f"  you said {said.strip()!r} ({field.strip()}); {row['title']} at {row['where']}: "
                     f"is that still what you want? (nothing filed; {src})")
    lines.append(f"accepted by you, not filed: {len(by_kind['accepted_risk'])}")
    for src, row in by_kind["accepted_risk"]:
        lines.append(f"  {row['title']} at {row['where']} (accepted by you: {row['intent'].partition(':')[2].strip()!r}; "
                     f"{src})")
    lines.append(f"out of scope, listed not filed: {len(by_kind['out_of_scope'])}")
    for src, row in by_kind["out_of_scope"]:
        lines.append(f"  {row['title']} at {row['where']} ({src})")
    return lines


def cmd_collect(args):
    root = Root(args.root)
    cfg = root.config()
    data = load(root)
    data["sources"] = collect_sources(cfg)
    data["confirmed"] = False
    save(root, data)
    for entry in data["sources"]:
        print(f"{label(entry)}  {entry['kind']}")
    print(f"{len(data['sources'])} sources, paths only. Read them, then write the summary with "
          "`crucible brief summary FILE` and ask the user the seven questions.")


def cmd_show(args):
    root = Root(args.root)
    data = load(root)
    print(render(data), end="")


def cmd_answer(args):
    root = Root(args.root)
    if args.field not in FIELDS:
        raise CrucibleError(f"unknown brief field {args.field!r}: use one of {', '.join(FIELDS)}")
    if not (args.words or "").strip():
        raise CrucibleError(f"refused: {args.field} is the user's own statement: ask the user, then record their "
                            "own words with --words")
    data = load(root)
    data["answers"][args.field] = {"words": args.words.strip(), "at": now()}
    data["confirmed"] = False
    save(root, data)
    print(f"{args.field}: recorded; the brief needs `crucible brief confirm` again")


def cmd_summary(args):
    root = Root(args.root)
    rows = read_json(args.file, None)
    if not isinstance(rows, list) or not rows:
        raise CrucibleError(f"{args.file} must hold a JSON list of {{\"line\": ..., \"source\": ...}}")
    data = load(root)
    known = {}
    for entry in data["sources"]:
        known[entry["path"]] = entry
        known[label(entry)] = entry
    for row in rows:
        if not isinstance(row, dict) or not str(row.get("line", "")).strip() or not str(row.get("source", "")).strip():
            raise CrucibleError("every summary line needs a line and a source")
        if row["source"] not in known:
            raise CrucibleError(f"source {row['source']!r} is not in the collected sources: run `crucible brief "
                                "collect` and cite one of its paths")
    data["summary"] = [{"line": str(r["line"]).strip(), "source": r["source"]} for r in rows]
    data["confirmed"] = False
    save(root, data)
    print(f"summary: {len(rows)} lines, labelled agent-written, not confirmed")


def cmd_confirm(args):
    root = Root(args.root)
    data = load(root)
    missing = [f for f in FIELDS if f not in data["answers"]]
    if missing:
        raise CrucibleError("the brief is not complete; unanswered: " + ", ".join(missing)
                            + ". Ask the user, then `crucible brief answer FIELD --words ...`")
    data["confirmed"] = True
    data["confirmed_at"] = now()
    save(root, data)
    print("project brief confirmed by the user")


def register(sub):
    p = sub.add_parser("brief", help="the project brief: what the project is and what the user expects of it")
    inner = p.add_subparsers(dest="brief_command", metavar="step")
    q = inner.add_parser("collect", help="list the files the project describes itself with (paths only)")
    q.set_defaults(func=cmd_collect)
    q = inner.add_parser("show", help="print the brief, its answers and its status")
    q.set_defaults(func=cmd_show)
    q = inner.add_parser("answer", help="record one answer in the user's words: " + ", ".join(FIELDS))
    q.add_argument("field")
    q.add_argument("--words", help="the user's own words (required)")
    q.set_defaults(func=cmd_answer)
    q = inner.add_parser("summary", help="store the agent's summary (JSON list of line and source)")
    q.add_argument("file")
    q.set_defaults(func=cmd_summary)
    q = inner.add_parser("confirm", help="mark the brief as confirmed by the user")
    q.set_defaults(func=cmd_confirm)
    p.set_defaults(func=lambda args: p.print_help() or 2)
