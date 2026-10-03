"""Never ask what is already answered: search the docs, Grimoira (if chosen) and, with its own grant, the
user's own past messages for an answer to each interview key."""
import datetime
import json
import os
import re

from . import brief
from .answer import INTERVIEW_ORDER, PREFIX, set_answer
from .config import grimoira_lookup
from .common import CrucibleError, Root, is_secret_file, mask_secrets, read_json, write_json
from .permissions import GROUPS, grant, now, run_action
from .transcripts import inside

# What each key is about, as the phrases that mark a line answering it. A key without phrases is never found.
PHRASES = {
    "purpose": ("purpose of", "is used by", "who uses", "is for "),
    "good": ("must always work", "good means", "what matters"),
    "intentional": ("intentional", "on purpose", "by design"),
    "must_never_change": ("never change", "must not change", "backward compat", "backwards compat", "public contract"),
    "accepted_risks": ("accepted risk", "we accept the risk", "risk accepted"),
    "out_of_scope": ("out of scope", "not a goal", "non-goal"),
    "known_issues": ("known issue", "won't fix", "wontfix"),
    "tracker": ("issue tracker", "report bugs", "report issues"),
    "advisories": ("security advisor", "report a vulnerab", "vulnerability report"),
    "owners": ("codeowners", "maintained by", "owned by"),
    "goals": ("priorities", "our goals"),
    "stages": ("release stage", "staging", "pre-release"),
    "scope": ("audit scope", "in scope"),
}
BRIEF_KEYS = tuple(brief.FIELDS)
ALL_KEYS = BRIEF_KEYS + tuple(k for k in INTERVIEW_ORDER if k not in BRIEF_KEYS)
MAX_QUOTE = 300
REFERENCE = re.compile(r"`([^`\s]+)`")
DOC_KINDS = ("readme", "docs", "adr", "contributing", "security", "architecture")


def is_permission_key(key):
    return key.startswith(PREFIX) or key in GROUPS


def phrases_for(key):
    return PHRASES.get(key, ())


def match_line(text, key):
    """The first line of text that carries a phrase of the key, else None."""
    words = phrases_for(key)
    for number, line in enumerate(text.split("\n"), 1):
        low = line.lower()
        if any(w in low for w in words):
            return number, line.strip()[:MAX_QUOTE]
    return None


def norm(text):
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", text.lower()).split())


def day(stamp):
    return datetime.datetime.fromtimestamp(stamp, datetime.timezone.utc).date().isoformat()


def newest_code_time(repo_path, skip):
    from .inventory import walk_text_files
    newest = 0.0
    for rel, full, _size in walk_text_files(repo_path, skip=skip):
        if brief.classify(rel) is None:
            newest = max(newest, os.path.getmtime(full))
    return newest


def missing_references(repo_path, rel, line):
    """The backticked file references of a line that no longer exist in the repo."""
    gone = []
    for token in REFERENCE.findall(line):
        if "://" in token or not ("/" in token or re.search(r"\.\w{1,5}$", token)):
            continue
        clean = token.strip(".,;:").lstrip("./")
        here = os.path.join(repo_path, os.path.dirname(rel))
        if not (os.path.exists(os.path.join(repo_path, clean)) or os.path.exists(os.path.join(here, clean))):
            gone.append(token)
    return gone


def doc_candidates(cfg, key):
    """One candidate per doc file: its first line that answers the key. Secret files are never opened."""
    found = []
    paths = {r["name"]: r["path"] for r in cfg["repos"]}
    skip = cfg.get("scope", {}).get("skip", [])
    newest = {}
    for entry in brief.collect_sources(cfg):
        if entry["kind"] not in DOC_KINDS or is_secret_file(entry["path"]):
            continue
        full = os.path.join(paths[entry["repo"]], *entry["path"].split("/"))
        try:
            with open(full, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            continue
        hit = match_line(text, key)
        if not hit:
            continue
        number, line = hit
        modified = os.path.getmtime(full)
        repo_path = paths[entry["repo"]]
        gone = missing_references(repo_path, entry["path"], line)
        if repo_path not in newest:
            newest[repo_path] = newest_code_time(repo_path, skip)
        row = {"source": f"{entry['repo']}/{entry['path']}:{number}", "quote": mask_secrets(line),
               "date": day(modified)}
        if gone and modified < newest[repo_path]:
            row["stale"] = f"{', '.join(gone)} does not exist in the code now"
        found.append(row)
    return found


def read_user_messages(root, history, phrases=None):
    """[{"text", "source", "date"}]: only the lines of the user's own messages that carry a phrase of an
    interview key, only from sessions run inside an in-scope repo, and only with the `history` grant. The
    assistant's text and every tool result are never read out; nothing else of a message is kept."""
    cfg = root.config()
    folders = [r["path"] for r in cfg["repos"]]
    names = [r["name"] for r in cfg["repos"]]
    words = phrases or tuple(w for key in PHRASES for w in PHRASES[key])
    files = []
    for item in history:
        if os.path.isdir(item):
            for folder, _dirs, names_ in os.walk(item):
                files += [os.path.join(folder, n) for n in sorted(names_) if n.endswith(".jsonl")]
        else:
            files.append(item)

    rows_out = []

    def action():
        rows_out.extend(_collect(files, folders, words))
        return f"{len(rows_out)} matching lines from {len(files)} files"

    run_action(root, "history", "read the user's own messages from " + ", ".join(os.path.basename(f) for f in files),
               action, repos=names)
    return rows_out


def _collect(files, folders, words):
    kept = []
    for path in files:
        session = os.path.splitext(os.path.basename(path))[0]
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                rows = fh.read().split("\n")
        except OSError as exc:
            raise CrucibleError(f"cannot read history {path}: {exc}")
        for raw in rows:
            try:
                row = json.loads(raw)
            except ValueError:
                continue
            message = row.get("message") if isinstance(row, dict) else None
            if not isinstance(message, dict) or message.get("role") != "user" or row.get("type") == "assistant":
                continue
            cwd = row.get("cwd")
            if not isinstance(cwd, str) or not any(inside(f, cwd) for f in folders):
                continue
            content = message.get("content")
            if isinstance(content, str):
                content = [{"type": "text", "text": content}]
            for part in content if isinstance(content, list) else []:
                if not isinstance(part, dict) or part.get("type") != "text" or not isinstance(part.get("text"), str):
                    continue
                for line in part["text"].split("\n"):
                    if any(w in line.lower() for w in words):
                        stamp = str(row.get("timestamp") or "")[:10]
                        kept.append({"text": mask_secrets(line.strip()[:MAX_QUOTE]),
                                     "source": f"session {session}, {stamp or 'date unknown'}", "date": stamp})
    return kept


def past_runs(root, explicit=None):
    """Earlier confirmed crucible folders: the explicit ones, else the siblings of this audit folder."""
    folders = list(explicit or [])
    parent = os.path.dirname(root.path)
    if not folders and os.path.isdir(parent):
        folders = [os.path.join(parent, n) for n in sorted(os.listdir(parent))]
    found = []
    for folder in folders:
        folder = os.path.abspath(folder)
        if folder == root.path:
            continue
        cfg = read_json(os.path.join(folder, "config.json"))
        if isinstance(cfg, dict) and (cfg.get("answers") or cfg.get("permissions")):
            found.append((folder, cfg))
    return found


def past_items(cfg):
    items = [(k, v["value"], v.get("at", "")) for k, v in cfg.get("answers", {}).items()]
    items += [(PREFIX + g, r["answer"], r.get("at", "")) for g, r in cfg.get("permissions", {}).items()]
    return items


def offer_lines(folder, cfg):
    items = past_items(cfg)
    when = max((i[2] for i in items), default="")[:10] or "an earlier date"
    lines = [f"Reuse your answers and permissions from {when}? (audit folder {folder})"]
    lines += [f"  {key} = {json.dumps(value)}" for key, value, _at in items]
    lines.append("  The user says yes, or names the keys to change: "
                 f"`crucible reuse --from {folder} --accept --words \"...\" [--except KEY ...]`")
    return lines


def decide(key, candidates):
    """(status, reason, answers) for one key from its candidates."""
    if is_permission_key(key):
        return "ask", "permission", []
    if not candidates:
        return "ask", "nothing found", []
    stale = [c for c in candidates if c.get("stale")]
    if stale:
        return "ask", "stale", stale
    distinct = {}
    for c in candidates:
        distinct.setdefault(norm(c["quote"]), c)
    if len(distinct) > 1:
        return "ask", "conflict", list(distinct.values())
    return "found", "", [candidates[0]]


def gather(root, cfg, key, history):
    if is_permission_key(key) or not phrases_for(key):
        return []
    found = doc_candidates(cfg, key)
    if (cfg.get("memory") or {}).get("kind") == "grimoira":
        found += [{"source": h["source"], "quote": h["quote"], "date": ""} for h in grimoira_lookup(phrases_for(key))]
    found += [{"source": m["source"], "quote": m["text"], "date": m["date"]} for m in history if match_line(m["text"], key)]
    return found


def render(key, status, reason, answers):
    if status == "found":
        head = f"{key}: found, not asked"
    else:
        head = f"{key}: ask ({reason})"
    lines = [head]
    for a in answers:
        extra = f" (older than the code: {a['stale']})" if a.get("stale") else ""
        lines.append(f"  source: {a['source']}" + (f", {a['date']}" if a.get("date") else ""))
        lines.append(f"  quote: {a['quote']}{extra}")
    return lines


def summary_lines(root):
    saved = read_json(root.p("prefill.json"), {}) or {}
    lines = []
    for key, row in saved.items():
        if row.get("status") == "found":
            a = row["answers"][0]
            lines.append(f"found, not asked: {key}: \"{a['quote']}\" ({a['source']})")
    return lines


def cmd_prefill(args):
    root = Root(args.root)
    cfg = root.config()
    if args.key and args.key not in ALL_KEYS:
        raise CrucibleError(f"unknown key {args.key!r}: `crucible next` prints the interview keys")
    keys = [args.key] if args.key else list(ALL_KEYS)
    history = read_user_messages(root, args.history) if args.history else []
    saved = read_json(root.p("prefill.json"), {}) or {}
    out = []
    for key in keys:
        status, reason, answers = decide(key, gather(root, cfg, key, history))
        saved[key] = {"status": status, "reason": reason, "answers": answers, "at": now()}
        out += render(key, status, reason, answers)
    write_json(root.p("prefill.json"), saved)
    for folder, past in past_runs(root, args.past):
        out += offer_lines(folder, past)
        break
    print("\n".join(out))


def cmd_reuse(args):
    root = Root(args.root)
    folder = os.path.abspath(args.source)
    cfg = read_json(os.path.join(folder, "config.json"))
    if not isinstance(cfg, dict):
        raise CrucibleError(f"no crucible config in {folder}")
    if not args.accept:
        print("\n".join(offer_lines(folder, cfg)))
        return
    if not (args.words or "").strip():
        raise CrucibleError("refused: reusing answers and permissions is the user's decision: ask the user, "
                            "then pass their own words with --words")
    skipped = set(args.skip or [])
    done, left = [], []
    for key, value, _at in past_items(cfg):
        if key in skipped:
            left.append(f"{key}: left for the user (named in --except)")
            continue
        try:
            if key.startswith(PREFIX):
                group = key[len(PREFIX):]
                row = cfg["permissions"][group]
                grant(root, group, row["answer"], args.words, bounds=row.get("bounds"))
            else:
                old = cfg["answers"][key]
                set_answer(root, key, old["value"], old.get("words") or args.words)
            done.append(key)
        except CrucibleError as exc:
            left.append(f"{key}: not reused ({exc})")
    print(f"reused {len(done)}: " + (", ".join(done) or "none"))
    for line in left:
        print(line)


def register(sub):
    p = sub.add_parser("prefill", help="find answers already given in docs, Grimoira or the user's own history")
    p.add_argument("--key", help="one interview key; default is every key")
    p.add_argument("--history", action="append", help="a transcript file or folder to read (needs the history grant)")
    p.add_argument("--past", action="append", help="an earlier audit folder to offer for reuse")
    p.set_defaults(func=cmd_prefill)
    p = sub.add_parser("reuse", help="offer, or with --accept apply, the answers and permissions of an earlier run")
    p.add_argument("--from", dest="source", required=True, help="the earlier audit folder")
    p.add_argument("--accept", action="store_true", help="apply them (the user said yes)")
    p.add_argument("--words", help="the user's own words")
    p.add_argument("--except", dest="skip", action="append", help="a key to leave for the user (repeatable)")
    p.set_defaults(func=cmd_reuse)
