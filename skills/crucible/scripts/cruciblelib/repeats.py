import os
import re

from .common import CrucibleError, Root, read_json
from .permissions import authorize
from .transcripts import read_usage, scoped_commands

MIN_RUNS = 3

QUOTED = re.compile(r"\"[^\"]*\"|'[^']*'")
URL = re.compile(r"\b[a-z][a-z0-9+.-]*://\S+", re.IGNORECASE)
UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.IGNORECASE)
HEX_ID = re.compile(r"\b(?=[0-9a-f]*\d)[0-9a-f]{7,}\b", re.IGNORECASE)
NUMBER = re.compile(r"\d+")


def shape_of(command):
    """The command with every quoted text, url, path, id and number replaced, so runs that differ only in
    those compare equal. A here-document body is dropped."""
    text = str(command).split("<<", 1)[0]
    text = QUOTED.sub("<str>", text)
    text = URL.sub("<url>", text)
    text = UUID.sub("<id>", text)
    words = []
    for word in text.split():
        if "/" in word or "\\" in word or word.startswith("~") or re.match(r"^[A-Za-z]:", word):
            word = "<path>"
        words.append(NUMBER.sub("<n>", HEX_ID.sub("<id>", word)))
    return " ".join(words)


# What a script a repeated job gets must follow (design 4c, step 3): one trigger and one command, no questions
# at run time, a dry-run mode for anything that writes, a backup of what it changes, its own PASS or FAIL,
# and a test that fails before the script exists.
QUESTIONS = re.compile(r"(?m)(?:^|[;&|])\s*read\s+[-\w]|\binput\s*\(|\bPause\b|\bRead-Host\b|\bGet-Credential\b")
WRITES = re.compile(r"\b(rm|mv|cp|tee|sed\s+-i|Set-Content|Remove-Item|Copy-Item|Move-Item)\b|[^>]>[^>&]|>>|"
                    r"open\([^)]*['\"][wax]|write_text|\.write\(")
DRY_RUN = re.compile(r"dry[-_ ]?run", re.IGNORECASE)
BACKUP = re.compile(r"backup|\.bak\b|\.orig\b", re.IGNORECASE)
ABSOLUTE = re.compile(r"(?<![\w.:~$/\"'-])/(?:[A-Za-z]+/)[\w./-]+|\b[A-Za-z]:[\\/][\w\\/.-]+")


def script_standard_checked(script, test=None):
    """The ways a proposed script misses the standard; an empty list means it meets it."""
    try:
        with open(script, encoding="utf-8", errors="replace") as fh:
            lines = [ln for ln in fh.read().split("\n") if not ln.lstrip().startswith("#")]
    except OSError as exc:
        raise CrucibleError(f"cannot read script {script}: {exc}")
    body = re.sub(r"\d?>>?\s*/dev/null", "", "\n".join(lines))
    problems = []
    if not (re.search(r"\bPASS\b", body) and re.search(r"\bFAIL\b", body)):
        problems.append("it does not print PASS or FAIL with its own check of the result")
    if QUESTIONS.search(body):
        problems.append("it asks a question at run time")
    if WRITES.search(body):
        if not DRY_RUN.search(body):
            problems.append("it writes but has no dry-run mode")
        if not BACKUP.search(body):
            problems.append("it writes but makes no backup of what it changes")
    if ABSOLUTE.search(body):
        problems.append("it holds an absolute path")
    if not (test and os.path.isfile(test)):
        problems.append("it has no test that fails before the script exists")
    return problems


def transcript_files(folder):
    if not os.path.isdir(folder):
        raise CrucibleError(f"{folder} is not a folder of transcripts")
    found = []
    for base, _dirs, names in os.walk(folder):
        found += [os.path.join(base, n) for n in sorted(names) if n.endswith(".jsonl")]
    return sorted(found)


def tokens_per_turn(path):
    try:
        usage = read_usage(path)
    except CrucibleError:
        return None
    return usage["tokens"] / usage["turns"]


def load_index(path):
    data = read_json(path, None)
    rows = data.get("scripts") if isinstance(data, dict) else None
    if not isinstance(rows, list) or not all(isinstance(r, dict) and r.get("script") and r.get("shape") for r in rows):
        raise CrucibleError(f"{path} is not a script index: it holds {{\"scripts\": [{{\"script\": PATH, \"shape\": COMMAND}}]}}")
    return rows


def find_repeats(root, folder, repo_names, minimum=MIN_RUNS, index=None):
    """Counts per command shape from the shell commands of the transcripts under `folder`, only for repos in
    scope and only with the `transcripts` grant. Only command text and exit status are read."""
    authorize(root, "transcripts", f"repeats from {os.path.basename(os.path.normpath(folder))}", repos=list(repo_names))
    shapes, total = {}, 0
    commands = []
    for path in transcript_files(folder):
        found = scoped_commands(root, path, repo_names)
        cost = tokens_per_turn(path) if found else None
        total += len(found)
        for row in found:
            row["shape"] = shape_of(row["command"])
        for position, row in enumerate(found):
            commands.append(row["command"])
            entry = shapes.setdefault(row["shape"], {"shape": row["shape"], "runs": 0, "failed": 0, "retried": 0, "tokens": None})
            entry["runs"] += 1
            if row["exit"] not in (0, None):
                entry["failed"] += 1
                if any(later["shape"] == row["shape"] for later in found[position + 1:]):
                    entry["retried"] += 1
            if cost is not None:
                entry["tokens"] = round((entry["tokens"] or 0) + cost)
    repeats = sorted((e for e in shapes.values() if e["runs"] >= minimum), key=lambda e: (-e["runs"], e["shape"]))
    out = {"commands": total, "repeats": repeats, "scripts": []}
    for row in load_index(index) if index else []:
        name, shape = row["script"], shape_of(row["shape"])
        used = sum(1 for c in commands if os.path.basename(name) in c)
        hand = sum(1 for c in commands if shape_of(c) == shape and os.path.basename(name) not in c)
        out["scripts"].append({"script": name, "used": used, "hand": hand, "unused": used == 0 and hand > 0})
    return out


def cmd_repeats(args):
    root = Root(args.root)
    root.require_confirmed()
    names = args.repo or [r["name"] for r in root.config()["repos"]]
    found = find_repeats(root, args.transcripts, names, minimum=args.min, index=args.scripts)
    print(f"{found['commands']} shell commands in scope; {len(found['repeats'])} shapes run {args.min} or more times")
    for row in found["repeats"]:
        cost = "tokens not measured" if row["tokens"] is None else f"about {row['tokens']} tokens"
        print(f"{row['runs']} runs, {row['failed']} failed, {row['retried']} retried, {cost}: {row['shape']}")
    for row in found["scripts"]:
        print(f"script {row['script']}: used {row['used']}, hand commands of its shape {row['hand']}")
        if row["unused"]:
            print(f"unused script: {row['script']}")


def register(sub):
    p = sub.add_parser("repeats", help="find shell commands the user's agents repeat; needs the transcripts grant")
    p.add_argument("--transcripts", required=True, metavar="DIR", help="a folder of agent transcripts (JSONL)")
    p.add_argument("--repo", action="append", help="a repo name in scope (default: every repo in the config)")
    p.add_argument("--min", type=int, default=MIN_RUNS, help=f"fewest runs of a shape to list (default {MIN_RUNS})")
    p.add_argument("--scripts", metavar="INDEX", help="the script index: show each script's use against hand commands")
    p.set_defaults(func=cmd_repeats)
