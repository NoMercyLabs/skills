"""`crucible explore FILE:LINE`: the facts a reader or verifier needs to find a root cause, from a static search.

Callers and callees, the parameters and assignments that feed the code, the config keys and environment names it
reads and where they are set, the git history of its lines, earlier fixes on the same lines, and the same pattern
elsewhere. Every fact is printed with file:line. Secret files are never opened (the walker skips them). The search is
textual: what it cannot follow it says so, and "not checked" stays visible.
"""

import os
import re

from .common import CrucibleError, Root, is_secret_file, split_lines
from .config import git
from .inventory import walk_text_files

KEYWORDS = {"if", "for", "while", "switch", "catch", "return", "def", "function", "func", "fn", "class", "elif", "else",
            "with", "and", "or", "not", "in", "is", "await", "async", "new", "throw", "lambda", "yield", "assert",
            "except", "try", "match", "case", "sizeof", "typeof", "using", "foreach", "when"}
DEF_PATTERNS = (
    r"^\s*(?:export\s+|async\s+|public\s+|private\s+|protected\s+|static\s+|final\s+|abstract\s+|override\s+|open\s+|internal\s+|suspend\s+)*"
    r"(?:def|function\*?|func|fun|fn|class|sub|proc)\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)",
    r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_]\w*)\s*=\s*(?:async\s*)?(?:\([^)]*\)\s*=>|function\b|[A-Za-z_]\w*\s*=>)",
    r"^\s*(?!(?:return|else|new|throw|await|yield|print|elif|del|raise|assert|case)\b)"
    r"(?:(?:public|private|protected|static|final|async|override|virtual|internal)\s+)*"
    r"(?:[\w<>\[\],.?]+\s+)+([A-Za-z_]\w*)\s*\([^;]*\)\s*(?:\{|=>|:)?\s*$",
)
DEF_RES = [re.compile(p) for p in DEF_PATTERNS]
ENV_RES = [re.compile(p) for p in (
    r"os\.environ(?:\.get)?\s*[\[(]\s*[\"'](\w+)", r"getenv\(\s*[\"'](\w+)", r"process\.env\.(\w+)",
    r"process\.env\[\s*[\"'](\w+)", r"\benv\(\s*[\"'](\w+)", r"GetEnvironmentVariable\(\s*\"(\w+)",
    r"ENV\[\s*[\"'](\w+)")]
KEY_RES = [re.compile(p) for p in (
    r"\bconfig\(\s*[\"']([\w.\-]+)", r"\b(?:config|cfg|conf|settings|options)(?:\.get)?\s*[\[(]\s*[\"']([\w.\-]+)[\"']")]
STRING_RE = re.compile(r"([\"'])(?:\\.|(?!\1).)*\1")
FIX_RE = re.compile(r"\b(fix\w*|revert\w*|hotfix|bug)\b", re.IGNORECASE)
CALL_RE = re.compile(r"\b([A-Za-z_]\w*)\s*\(")
ASSIGN_RE = re.compile(r"^\s*(?:(?:const|let|var|final|val)\s+)?([A-Za-z_][\w.]*)\s*(?::=|=)(?!=)\s*(.+)$")
SYMBOL_EXTENSIONS = {".py", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".cs", ".java", ".kt", ".kts", ".php", ".go",
                     ".rs", ".rb"}  # the languages with a tested fixture; any other extension gets no caller list
LIMIT = 30


def shape(line):
    """The line with string literals and numbers replaced: two lines of one pattern share a shape."""
    text = STRING_RE.sub("S", line.strip())
    text = re.sub(r"\b\d+(?:\.\d+)?\b", "N", text)
    return re.sub(r"\s+", " ", text)


def indent_of(line):
    return len(line) - len(line.lstrip())


def find_def(lines, line_no):
    """(line number, name) of the nearest definition at or above line_no, or None."""
    for i in range(line_no, 0, -1):
        for rx in DEF_RES:
            match = rx.match(lines[i - 1])
            if match and match.group(1) not in KEYWORDS:
                return i, match.group(1)
    return None


def span_end(lines, start):
    base = indent_of(lines[start - 1])
    end = start
    for i in range(start + 1, min(len(lines), start + 300) + 1):
        text = lines[i - 1]
        if not text.strip():
            continue
        if indent_of(text) <= base and not text.strip().startswith(("}", ")", "]", "end")):
            break
        end = i
    return end


def is_def_of(line, name):
    for rx in DEF_RES:
        match = rx.match(line)
        if match and match.group(1) == name:
            return True
    return False


class Corpus:
    def __init__(self, cfg):
        self.multi = len(cfg["repos"]) > 1
        self.repos = cfg["repos"]
        self.files = []  # (repo name, repo path, rel, lines)
        for repo in cfg["repos"]:
            for rel, full, _size in walk_text_files(repo["path"]):
                with open(full, "rb") as fh:
                    self.files.append((repo["name"], repo["path"], rel, split_lines(fh.read())))

    def ref(self, repo, rel, no):
        return f"{repo}/{rel}:{no}" if self.multi else f"{rel}:{no}"

    def grep(self, rx, skip=None):
        """[(ref, line text)] for every line the pattern matches, never inside the span `skip` (repo, rel, a, b)."""
        found = []
        for repo, _path, rel, lines in self.files:
            for no, text in enumerate(lines, 1):
                if skip and (repo, rel) == skip[:2] and skip[2] <= no <= skip[3]:
                    continue
                if rx.search(text):
                    found.append((self.ref(repo, rel, no), text.strip()[:160]))
        return found


def resolve(cfg, target):
    """(repo entry, relative path, line number) for FILE:LINE; a leading repo name is accepted."""
    match = re.match(r"^(.+):(\d+)$", target)
    if not match:
        raise CrucibleError("give the target as FILE:LINE")
    path, line_no = match.group(1).replace("\\", "/"), int(match.group(2))
    if is_secret_file(path):
        raise CrucibleError(f"{path} is a secret file: it is never read or shown")
    for repo in cfg["repos"]:
        for rel in (path, path[len(repo["name"]) + 1:] if path.startswith(repo["name"] + "/") else None):
            if rel and os.path.isfile(os.path.join(repo["path"], *rel.split("/"))):
                return repo, rel, line_no
    raise CrucibleError(f"{path} is not in any repo of this audit")


def section(title, rows, empty):
    print(f"{title}:" if rows else f"{title}: {empty}")
    for row in rows[:LIMIT]:
        print(f"  {row}")
    if len(rows) > LIMIT:
        print(f"  ... {len(rows) - LIMIT} more not shown")


def history(repo, rel, a, b):
    if not os.path.exists(os.path.join(repo["path"], ".git")):
        return None
    out = git(repo["path"], "log", "-L", f"{a},{b}:{rel}", "-s", "--date=short", "--format=%h|%ad|%s")
    commits = [row.split("|", 2) for row in out.splitlines() if row.count("|") >= 2]
    return commits


def cmd_explore(args):
    root = Root(args.root)
    cfg = root.config()
    repo, rel, line_no = resolve(cfg, args.target)
    with open(os.path.join(repo["path"], *rel.split("/")), "rb") as fh:
        lines = split_lines(fh.read())
    if not 1 <= line_no <= len(lines):
        raise CrucibleError(f"{rel} has no line {line_no} (it has {len(lines)} lines)")
    corpus = Corpus(cfg)
    here = corpus.ref(repo["name"], rel, line_no)
    ext = os.path.splitext(rel)[1].lower()
    supported = ext in SYMBOL_EXTENSIONS
    found = find_def(lines, line_no) if supported else None
    if found:
        start, name = found
        end = max(span_end(lines, start), line_no)
    else:
        start, name, end = line_no, None, line_no
    skip = (repo["name"], rel, start, end)
    print(f"explore {here}: {lines[line_no - 1].strip()[:160]}")
    if name:
        print(f"symbol: {name} ({corpus.ref(repo['name'], rel, start)}) lines {start}-{end}")
    elif not supported:
        print(f"symbol: not detected: symbol detection not supported for {ext or rel}: callers not listed")
    else:
        print("symbol: none found above this line (no definition pattern matched); facts below use the line only")
    span = [(no, lines[no - 1]) for no in range(start, end + 1)]

    callers = []
    if name:
        rx = re.compile(r"\b" + re.escape(name) + r"\s*\(")
        callers = [(ref, text) for ref, text in corpus.grep(rx) if not is_def_of(text, name)]
    if supported:
        section("callers", [f"{ref}: {text}" for ref, text in callers], "none found by search")
    else:
        print(f"callers: symbol detection not supported for {ext or rel}: callers not listed")
    for ref, _text in callers[:5]:
        print(f"  next: crucible explore {ref}")

    callees, seen = [], set()
    for no, text in span[1:] if name else span:
        for called in CALL_RE.findall(text):
            if called in KEYWORDS or called == name or called in seen:
                continue
            seen.add(called)
            where = [ref for ref, row in corpus.grep(re.compile(r"\b" + re.escape(called) + r"\b")) if is_def_of(row, called)]
            callees.append(f"{called} at {corpus.ref(repo['name'], rel, no)} -> " + (where[0] if where else "not defined in the audited repos"))
    section("callees", callees, "none")

    inputs = []
    if name:
        params = re.search(r"\(([^)]*)\)", lines[start - 1])
        if params and params.group(1).strip():
            inputs.append(f"parameters of {name}: {params.group(1).strip()[:120]}")
            inputs += [f"passed at {ref}: {text}" for ref, text in callers[:10]]
    for no, text in span:
        match = ASSIGN_RE.match(text)
        if match and no != start:
            inputs.append(f"{corpus.ref(repo['name'], rel, no)}: {text.strip()[:140]}")
    section("inputs", inputs, "no parameters or assignments found")
    print("  not followed beyond the callers above: run explore on a caller to go one step up")

    names = {}
    for no, text in span:
        for kind, rxs in (("env", ENV_RES), ("config key", KEY_RES)):
            for rx in rxs:
                for key in rx.findall(text):
                    names.setdefault((kind, key), corpus.ref(repo["name"], rel, no))
    reads = []
    for (kind, key), read_at in sorted(names.items()):
        reads.append(f"{kind} {key} read at {read_at}")
        short = re.escape(key.split(".")[-1])
        setter = re.compile(r"\b" + short + r"[\"']?\s*[:=](?!=)")
        for ref, text in corpus.grep(setter, skip):
            reads.append(f"  set at {ref}: {text}")
        if not any(row.startswith("  set") for row in reads[-1:]):
            reads.append(f"  set: no assignment of {key} found in the audited files (secret files are not searched)")
    section("config and environment", reads, "none read in these lines")

    commits = history(repo, rel, start, end)
    if commits is None:
        print("history: not a git repo (not checked)")
        print("earlier fix or revert on these lines: not checked")
    else:
        section("history", [f"{c[0]} {c[1]} {c[2]}" for c in commits], "no commits found for these lines")
        fixes = [c for c in commits if FIX_RE.search(c[2])]
        section("earlier fix or revert on these lines", [f"{c[0]} {c[1]} {c[2]}" for c in fixes], "none in the history")

    target_shape = shape(lines[line_no - 1])
    siblings = []
    if len(target_shape) >= 8:
        for r, _path, srel, slines in corpus.files:
            for no, text in enumerate(slines, 1):
                if (r, srel) == (repo["name"], rel) and start <= no <= end:
                    continue
                if shape(text) == target_shape:
                    siblings.append(f"{corpus.ref(r, srel, no)}: {text.strip()[:160]}")
    section("siblings", siblings, "no other line with this shape")
    print("a finding cites the explore runs it used and says which callers and sources it did not follow")
    return 0


def register(sub):
    p = sub.add_parser("explore", help="callers, sources, config, history and siblings of the code at FILE:LINE")
    p.add_argument("target", help="FILE:LINE (a leading repo name is accepted)")
    p.set_defaults(func=cmd_explore)
