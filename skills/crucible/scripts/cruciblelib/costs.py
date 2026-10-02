import json
import os
import re
import time

from .backup import backup
from .common import CrucibleError, Root, read_json, write_json
from .permissions import authorize, run_action
from .repeats import shape_of, transcript_files
from .transcripts import SHELL_TOOLS, exit_status, inside, read_usage

CHARS_PER_TOKEN = 4
LARGE_OUTPUT_CHARS = 20000
SHORT_ANSWER_CHARS = 400
MIN_SECTION_TOKENS = 400
AGENT_TOOLS = ("Task", "Agent")
INSTRUCTION_FILES = ("CLAUDE.md", "AGENTS.md", os.path.join(".claude", "CLAUDE.md"))
MOVE_FOLDER = "docs/agent"
HEADING = re.compile(r"^#{1,6}\s+(.*?)\s*#*\s*$")

PROMPT_LINES = {
    "output": "Cap command output (head, tail, grep) and read only the part of a file you need.",
    "retries": "Run the project's scripts for repeated jobs instead of retyping the commands.",
    "agents": "Ask a script before sending an agent for a fact a command answers; give agents file paths, not contents.",
}


def tokens_of(text):
    return len(text) // CHARS_PER_TOKEN


def result_size(part):
    body = part.get("content")
    if isinstance(body, list):
        return sum(len(x.get("text", "")) for x in body if isinstance(x, dict))
    return len(body) if isinstance(body, str) else 0


def read_session(path, folders):
    """Numbers only from one transcript: whether it is in scope, the model of each turn, the size of each tool
    result, shell exit codes and command shapes. No message text and no tool output is kept."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            rows = fh.read().split("\n")
    except OSError as exc:
        raise CrucibleError(f"cannot read transcript {path}: {exc}")
    out = {"scoped": False, "sidechain": False, "models": {}, "calls": {}, "results": [], "shells": []}
    for raw in rows:
        try:
            row = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(row, dict):
            continue
        cwd = row.get("cwd")
        if isinstance(cwd, str) and any(inside(f, cwd) for f in folders):
            out["scoped"] = True
        message = row.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(message, dict) and isinstance(message.get("usage"), dict) and row.get("isSidechain"):
            out["sidechain"] = True
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "tool_use":
                command = (part.get("input") or {}).get("command")
                out["calls"][part.get("id")] = (part.get("name"), command if part.get("name") in SHELL_TOOLS else None)
            elif part.get("type") == "tool_result":
                name, command = out["calls"].get(part.get("tool_use_id"), (None, None))
                out["results"].append((name, result_size(part)))
                if isinstance(command, str):
                    out["shells"].append((shape_of(command), exit_status(part)))
    return out


def session_models(path):
    """{model: {"turns", "tokens"}} from the usage and model fields of each assistant message, folded by id."""
    seen = {}
    with open(path, encoding="utf-8", errors="replace") as fh:
        for index, raw in enumerate(fh.read().split("\n")):
            try:
                row = json.loads(raw)
            except ValueError:
                continue
            message = row.get("message") if isinstance(row, dict) else None
            usage = message.get("usage") if isinstance(message, dict) else None
            if isinstance(usage, dict) and isinstance(message.get("model"), str):
                entry = seen.setdefault(message.get("id") or f"row{index}", {"model": message["model"], "tokens": 0})
                total = sum(v for k, v in usage.items() if k.endswith("tokens") and isinstance(v, int))
                entry["tokens"] = max(entry["tokens"], total)
    return list(seen.values())


def sections(text):
    """[(heading, start, end)] cut at every markdown heading; a heading inside a code fence does not count."""
    found, fenced, offset = [], False, 0
    for line in text.splitlines(keepends=True):
        if line.lstrip().startswith("```"):
            fenced = not fenced
        match = None if fenced else HEADING.match(line.rstrip("\r\n"))
        if match:
            found.append([match.group(1), offset, len(text)])
            if len(found) > 1:
                found[-2][2] = offset
        offset += len(line)
    return [tuple(s) for s in found]


def slug(heading):
    return re.sub(r"[^a-z0-9]+", "-", heading.lower()).strip("-") or "section"


def read_text(path):
    try:
        with open(path, encoding="utf-8", errors="replace", newline="") as fh:
            return fh.read()
    except OSError as exc:
        raise CrucibleError(f"cannot read {path}: {exc}")


def weeks_spanned(paths):
    moments = [os.path.getmtime(p) for p in paths]
    return max((max(moments) - min(moments)) / (7 * 86400), 1) if moments else 1


def prompt_proposals(found):
    sessions = max(found["sessions"], 1)
    big, agents = found["large_outputs"], found["agents"]
    excess = big["tokens"] - big["count"] * LARGE_OUTPUT_CHARS // CHARS_PER_TOKEN
    per_turn = found["tokens"] / found["turns"] if found["turns"] else 0
    savings = {"output": excess,
               "retries": found["retried"] * per_turn,
               "agents": agents["short_answers"] * (agents["start_tokens"] or 0)}
    return [{"kind": "prompt_line", "line": PROMPT_LINES[key], "tokens_per_session": round(value / sessions),
             "tokens_per_week": round(value / sessions * found["sessions"] / found["weeks"])}
            for key, value in savings.items() if round(value / sessions) > 0]


def find_costs(root, folder, repo_names, user_file=None):
    """Where the tokens of the transcripts under `folder` go, for repos in scope, with the `transcripts` grant.
    Only usage numbers, tool names, command shapes and result sizes are read; the conversation never is."""
    authorize(root, "transcripts", f"costs from {os.path.basename(os.path.normpath(folder))}", repos=list(repo_names))
    paths = {r["name"]: r["path"] for r in root.config()["repos"]}
    unknown = [n for n in repo_names if n not in paths]
    if unknown:
        raise CrucibleError(f"{', '.join(unknown)} not in the config")
    folders = [paths[n] for n in repo_names]
    found = {"sessions": 0, "turns": 0, "tokens": 0, "failed": 0, "retried": 0, "models": {}, "weeks": 1,
             "large_outputs": {"count": 0, "tokens": 0}, "agents": {"starts": 0, "short_answers": 0, "start_tokens": None},
             "instructions": [], "user_file": None, "always_loaded": 0, "proposals": []}
    starts, session_paths = [], []

    def scan():
        for path in transcript_files(folder):
            session = read_session(path, folders)
            if not session["scoped"] and not session["sidechain"]:
                continue
            for row in session_models(path):
                entry = found["models"].setdefault(row["model"], {"turns": 0, "tokens": 0})
                entry["turns"] += 1
                entry["tokens"] += row["tokens"]
            if session["sidechain"]:
                starts.append(first_turn(path))
                continue
            usage = read_usage(path)
            found["sessions"] += 1
            found["turns"] += usage["turns"]
            found["tokens"] += usage["tokens"]
            session_paths.append(path)
            for name, size in session["results"]:
                if size >= LARGE_OUTPUT_CHARS:
                    found["large_outputs"]["count"] += 1
                    found["large_outputs"]["tokens"] += size // CHARS_PER_TOKEN
                if name in AGENT_TOOLS:
                    found["agents"]["starts"] += 1
                    found["agents"]["short_answers"] += size < SHORT_ANSWER_CHARS
            for position, (shape, status) in enumerate(session["shells"]):
                if status not in (0, None):
                    found["failed"] += 1
                    found["retried"] += any(later == shape for later, _ in session["shells"][position + 1:])

    run_action(root, "transcripts", f"read usage and sizes from {os.path.basename(os.path.normpath(folder))}", scan,
               repos=list(repo_names))
    found["weeks"] = weeks_spanned(session_paths)
    found["agents"]["start_tokens"] = round(sum(starts) / len(starts)) if starts else None
    texts = {}
    for name, repo in zip(repo_names, folders):
        for rel in INSTRUCTION_FILES:
            path = os.path.join(repo, rel)
            if os.path.isfile(path):
                texts[(name, rel)] = read_text(path)
                found["instructions"].append({"repo": name, "file": rel.replace(os.sep, "/"), "tokens": tokens_of(texts[(name, rel)])})
    if user_file:
        authorize(root, "user_instructions", f"measure {os.path.basename(user_file)}", targets=[os.path.normpath(user_file)])
        found["user_file"] = {"tokens": tokens_of(read_text(user_file))}
    loaded = sum(r["tokens"] for r in found["instructions"]) + (found["user_file"] or {"tokens": 0})["tokens"]
    found["always_loaded"] = loaded * found["sessions"]
    for (name, rel), text in texts.items():
        for heading, start, end in sections(text):
            size = tokens_of(text[start:end])
            if size >= MIN_SECTION_TOKENS:
                found["proposals"].append({"kind": "move_section", "repo": name, "file": rel.replace(os.sep, "/"),
                                           "heading": heading, "target": f"{MOVE_FOLDER}/{slug(heading)}.md",
                                           "tokens_per_session": size,
                                           "tokens_per_week": round(size * found["sessions"] / found["weeks"])})
    found["proposals"] += prompt_proposals(found)
    return found


def first_turn(path):
    """Tokens of the first message of an agent transcript: what starting that agent cost."""
    with open(path, encoding="utf-8", errors="replace") as fh:
        for raw in fh.read().split("\n"):
            try:
                usage = json.loads(raw)["message"]["usage"]
            except (ValueError, KeyError, TypeError):
                continue
            if isinstance(usage, dict):
                return sum(v for k, v in usage.items() if k.endswith("tokens") and isinstance(v, int))
    return 0


def apply_move(root, repo, rel, heading):
    """Move one section of an instruction file to an on-demand file, leaving the heading and a one-line pointer.
    The file is backed up first; the text is moved, never deleted."""
    path = os.path.join(repo, rel)
    if not inside(repo, path) or not os.path.isfile(path):
        raise CrucibleError(f"{rel} is not a file inside {repo}")
    text = read_text(path)
    chosen = [s for s in sections(text) if s[0] == heading]
    if len(chosen) != 1:
        raise CrucibleError(f"{rel} has {len(chosen)} sections called {heading!r}; name exactly one")
    _title, start, end = chosen[0]
    target = f"{MOVE_FOLDER}/{slug(heading)}.md"
    full = os.path.join(repo, *target.split("/"))
    if os.path.exists(full):
        raise CrucibleError(f"{target} already exists; nothing is moved")
    backup(root, f"instructions-{rel}", path)
    newline = "\r\n" if "\r\n" in text else "\n"
    pointer = f"{text[start:end].splitlines()[0]}{newline}{newline}Moved to {target}. Read it when the task needs it.{newline}{newline}"
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8", newline="") as fh:
        fh.write(text[start:end])
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text[:start] + pointer + text[end:])
    return target


def metrics(found):
    sessions = max(found["sessions"], 1)
    return {"sessions": found["sessions"], "tokens_per_session": round(found["tokens"] / sessions),
            "always_loaded_per_session": found["always_loaded"] // sessions}


def compare(before, after):
    """Lines that set an earlier measurement against this one, the same numbers both times."""
    lines = []
    for key, label in (("always_loaded_per_session", "always-loaded tokens per session"),
                       ("tokens_per_session", "tokens per session")):
        change = before[key] - after[key]
        lines.append(f"{label}: saved {change}" if change > 0 else f"{label}: {before[key]} before, {after[key]} now")
    if all(before[k] <= after[k] for k in ("always_loaded_per_session", "tokens_per_session")):
        lines.append("the change saved nothing")
    return lines


def record_run(root, found):
    path = root.p("costs.json")
    data = read_json(path, None)
    runs = data.get("runs", []) if isinstance(data, dict) else []
    now = metrics(found)
    write_json(path, {"runs": runs + [dict(now, at=time.strftime("%Y-%m-%dT%H:%M:%S"))]})
    return runs[-1] if runs else None


def cmd_costs(args):
    root = Root(args.root)
    root.require_confirmed()
    if args.costs_command == "move":
        paths = {r["name"]: r["path"] for r in root.config()["repos"]}
        if args.target_repo not in paths:
            raise CrucibleError(f"{args.target_repo} is not a repo in the config")
        print(f"moved to {apply_move(root, paths[args.target_repo], args.file, args.heading)}")
        return
    if not args.transcripts:
        raise CrucibleError("costs needs --transcripts DIR, or the move command")
    names = args.repo or [r["name"] for r in root.config()["repos"]]
    found = find_costs(root, args.transcripts, names, user_file=args.user_file)
    print(f"{found['sessions']} sessions, {found['tokens']} tokens, {found['failed']} failed commands, "
          f"{found['retried']} retried")
    print(f"always loaded: {found['always_loaded']} tokens over those sessions")
    print(f"large outputs: {found['large_outputs']['count']} holding about {found['large_outputs']['tokens']} tokens")
    agents = found["agents"]
    print(f"agents: {agents['starts']} started, {agents['short_answers']} with a one-line answer")
    for model, row in sorted(found["models"].items()):
        print(f"model {model}: {row['turns']} turns, {row['tokens']} tokens")
    for row in found["proposals"]:
        saving = f"saves {row['tokens_per_session']} tokens per session, {row['tokens_per_week']} per week"
        if row["kind"] == "move_section":
            print(f"move '{row['heading']}' of {row['file']} to {row['target']}: {saving}")
        else:
            print(f"add the line \"{row['line']}\": {saving}")
    before = record_run(root, found)
    if before:
        for line in compare(before, metrics(found)):
            print(line)


def register(sub):
    p = sub.add_parser("costs", help="measure where the user's tokens go and propose savings; needs the transcripts grant")
    p.add_argument("--transcripts", metavar="DIR", help="a folder of agent transcripts (JSONL)")
    p.add_argument("--repo", action="append", help="a repo name in scope (default: every repo in the config)")
    p.add_argument("--user-file", metavar="FILE", help="the user-wide instruction file; needs the user_instructions grant")
    p.set_defaults(func=cmd_costs, costs_command=None)
    move = p.add_subparsers(dest="costs_command").add_parser("move", help="move one section of an instruction file to an on-demand file")
    move.add_argument("--repo", dest="target_repo", required=True, help="the repo name")
    move.add_argument("--file", required=True, help="the instruction file, relative to the repo")
    move.add_argument("--heading", required=True, help="the exact heading text of the section")
