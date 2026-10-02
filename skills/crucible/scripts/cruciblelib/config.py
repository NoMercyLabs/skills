import glob
import os
import re
import secrets
import shutil
import subprocess

from .answer import missing_for_confirm
from .common import CrucibleError, Root, split_lines, write_json
from .inventory import walk_text_files

LANGUAGES = {
    ".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript", ".mjs": "JavaScript", ".ts": "TypeScript",
    ".tsx": "TypeScript", ".vue": "Vue", ".go": "Go", ".rs": "Rust", ".java": "Java", ".kt": "Kotlin",
    ".cs": "C#", ".php": "PHP", ".rb": "Ruby", ".swift": "Swift", ".c": "C", ".h": "C", ".cpp": "C++",
    ".sh": "Shell", ".ps1": "PowerShell", ".sql": "SQL", ".yml": "YAML", ".yaml": "YAML", ".json": "JSON",
    ".toml": "TOML", ".html": "HTML", ".css": "CSS", ".md": "Markdown",
}
CI_FILES = [".gitlab-ci.yml", "Jenkinsfile", ".circleci/config.yml", "azure-pipelines.yml",
            ".travis.yml", "bitbucket-pipelines.yml"]
SUGGEST_SKIP = ["dist", "build", "out", "generated", "fixtures", "coverage", "target", "bin", "obj"]

# Hooks filled by tracker adapters: each takes a repo entry and returns a list of strings.
TRACKER_DETECTORS = []

DEFAULT_GOALS = ["users can use the product without help", "security", "stability", "features"]


def default_config():
    return {
        "version": 1,
        "confirmed": False,
        "repos": [],
        "scope": {"include": [], "skip": []},
        "goals": [{"id": i, "name": name} for i, name in enumerate(DEFAULT_GOALS, 1)],
        "stages": [],
        "tracker": {"kind": "markdown", "owner": "", "repo": "", "project_number": 0, "fields": {}},
        "advisories": "draft",
        "owners": {},
        "privacy_words": [],
        "memory": None,
        "auto_file": None,
        "blocker_fixes": {"mode": None, "landing": "pr", "branch": None, "live_changes": "never"},
        "backups": {"enabled": True, "path": None},
        "knowledge_sources": [],
        "visibility": {"pointers": None, "public_board_items": None, "collaborators_see_security": None,
                       "destinations": {}},
        "private_destination": None,
        "permissions": {},
        "answers": {},
        "budget": {"max_tokens": 0, "tokens_per_line": 34},
        "models": {"reader": "balanced", "verifier": "balanced", "check": "fast", "judge": "strong"},
        "live_checks": {"enabled": False, "targets": []},
        "unit_bytes": 92160,
    }


def git(path, *args):
    try:
        done = subprocess.run(["git", "-C", path, *args], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def remote_owner(remote):
    match = re.search(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?/?$", remote)
    return match.group(1) if match else ""


def detect_repo(name, path):
    remote = git(path, "remote", "get-url", "origin") if os.path.exists(os.path.join(path, ".git")) else ""
    languages, total = {}, 0
    for rel, full, size in walk_text_files(path):
        language = LANGUAGES.get(os.path.splitext(rel)[1].lower())
        if not language:
            continue
        with open(full, "rb") as fh:
            count = len(split_lines(fh.read()))
        languages[language] = languages.get(language, 0) + count
        total += count
    ci = sorted(os.path.relpath(f, path).replace(os.sep, "/")
                for f in glob.glob(os.path.join(path, ".github", "workflows", "*.y*ml")))
    ci += [c for c in CI_FILES if os.path.exists(os.path.join(path, *c.split("/")))]
    entry = {"name": name, "path": path, "remote": remote, "owner": remote_owner(remote),
             "public": None, "instances": []}
    entry["detected"] = {
        "languages": dict(sorted(languages.items(), key=lambda kv: -kv[1])),
        "lines": total,
        "ci": ci,
        "suggested_skip": [d for d in SUGGEST_SKIP if os.path.isdir(os.path.join(path, d))],
        "trackers": [t for detector in TRACKER_DETECTORS for t in detector(entry)],
    }
    return entry


def grimoira_status():
    """'command', 'plugin' or '' : how the grimoira integration answers on this machine (best effort)."""
    exe = shutil.which("grimoira")
    if exe:
        try:
            done = subprocess.run([exe, "help"], capture_output=True, text=True, timeout=20)
            if done.returncode == 0:
                return "command"
        except (OSError, subprocess.SubprocessError):
            pass
    home = os.path.expanduser("~")
    for pattern in ("plugins/*grimoira*", "plugins/*/*grimoira*", "plugins/cache/*/*grimoira*"):
        if glob.glob(os.path.join(home, ".claude", *pattern.split("/"))):
            return "plugin"
    return ""


def render_memory():
    found = grimoira_status()
    if found == "command":
        return "memory: the grimoira command answers"
    if found == "plugin":
        return "memory: a grimoira plugin folder exists (the command did not answer)"
    return "memory: grimoira not found"


def render(entry):
    d = entry["detected"]
    langs = ", ".join(f"{k} {v}" for k, v in d["languages"].items()) or "none"
    remote = entry["remote"] or "no git remote"
    if entry["owner"]:
        remote += f" ({entry['owner']}/{entry['name']})"
    lines = [f"repo {entry['name']}: {entry['path']}", f"  remote: {remote}",
             f"  lines: {d['lines']} ({langs})", f"  ci: {', '.join(d['ci']) or 'none found'}",
             "  public or private: unknown (ask the user)"]
    if d["suggested_skip"]:
        lines.append(f"  suggested skip: {', '.join(d['suggested_skip'])}")
    if d["trackers"]:
        lines.append(f"  existing trackers: {', '.join(d['trackers'])}")
    return "\n".join(lines)


def unique_names(paths):
    seen, names = {}, []
    for path in paths:
        base = re.sub(r"[^A-Za-z0-9._-]", "-", os.path.basename(os.path.normpath(path))) or "repo"
        seen[base] = seen.get(base, 0) + 1
        names.append(base if seen[base] == 1 else f"{base}-{seen[base]}")
    return names


def cmd_init(args):
    root = Root(args.root)
    if os.path.exists(root.p("config.json")):
        raise CrucibleError(f"already initialised: {root.p('config.json')} exists")
    paths = [os.path.abspath(r) for r in args.repo]
    for path in paths:
        if not os.path.isdir(path):
            raise CrucibleError(f"{path} is not a folder")
    os.makedirs(root.p("private"), exist_ok=True)
    with open(root.p("private", "key"), "w", encoding="utf-8") as fh:
        fh.write(secrets.token_hex(32) + "\n")
    # The audit folder may sit inside a repo; the key must never be committed.
    with open(root.p("private", ".gitignore"), "w", encoding="utf-8") as fh:
        fh.write("*\n")
    cfg = default_config()
    cfg["repos"] = [detect_repo(n, p) for n, p in zip(unique_names(paths), paths)]
    root.save_config(cfg)
    print("\n".join(render(e) for e in cfg["repos"]))
    print(render_memory())
    print("config written, not confirmed: ask the user the interview questions, then run `crucible confirm`")


def cmd_detect(args):
    cfg = Root(args.root).config()
    print("\n".join(render(detect_repo(r["name"], r["path"])) for r in cfg["repos"]))
    print(render_memory())


def cmd_summary(args):
    cfg = Root(args.root).config()
    lines = [f"confirmed: {cfg['confirmed']}"]
    lines += [render(r) for r in cfg["repos"]]
    lines.append("scope include: " + (", ".join(cfg["scope"]["include"]) or "everything"))
    lines.append("scope skip: " + (", ".join(cfg["scope"]["skip"]) or "nothing beyond vendored folders"))
    lines.append("goals: " + "; ".join(f"{g['id']} {g['name']}" for g in cfg["goals"]))
    lines.append("stages: " + (", ".join(cfg["stages"]) or "none"))
    lines.append(f"tracker: {cfg['tracker']['kind']}")
    lines.append(f"security advisories: {cfg['advisories']}")
    lines.append("privacy words: " + (", ".join(cfg["privacy_words"]) or "none"))
    cap = cfg["budget"]["max_tokens"]
    lines.append(f"token cap: {cap or 'none'}")
    lines.append("models: " + ", ".join(f"{k} {v}" for k, v in cfg["models"].items()))
    lines.append("permanent memory: " + describe_memory(cfg.get("memory")))
    lines.append(f"live checks: {'on' if cfg['live_checks']['enabled'] else 'off'}")
    auto = cfg.get("auto_file")
    lines.append("file findings automatically: " + ("not answered" if auto is None else "yes" if auto else "no"))
    lines.append("backups: " + ("on" if cfg.get("backups", {}).get("enabled", True) else "off"))
    lines.append("permissions: " + ", ".join(f"{g} {r['answer']}" for g, r in cfg.get("permissions", {}).items()))
    print("\n".join(lines))


def describe_memory(memory):
    if not memory:
        return "not chosen yet (ask the user: set up grimoira, use an installed store, or none)"
    if memory.get("kind") == "grimoira":
        return f"grimoira, instance {memory.get('instance') or 'default'}"
    return "none (the next session re-learns the system; the next audit cannot skip files already read)"


def cmd_memory(args):
    root = Root(args.root)
    cfg = root.config()
    if not (args.words or "").strip():
        raise CrucibleError("refused: the memory choice is the user's decision: ask the user, then record their "
                            "own words with --words")
    if args.kind == "grimoira":
        cfg["memory"] = {"kind": "grimoira", "instance": args.instance or "default"}
    else:
        cfg["memory"] = {"kind": "none"}
    root.save_config(cfg)
    print("memory: " + describe_memory(cfg["memory"]))


def cmd_confirm(args):
    root = Root(args.root)
    cfg = root.config()
    if not cfg.get("memory"):
        raise CrucibleError("memory not chosen: ask the user the permanent memory question "
                         "(references/interview.md, item 11), then run `crucible memory grimoira --instance NAME` "
                         "or `crucible memory none`")
    missing = missing_for_confirm(cfg)
    if missing:
        raise CrucibleError("not every question is answered; missing: " + ", ".join(missing)
                         + ". Ask the user, then record each with `crucible answer KEY VALUE --words ...` "
                         "or `crucible grant GROUP yes|no --words ...` for permissions.GROUP (`crucible next` shows the next one)")
    cfg["confirmed"] = True
    root.save_config(cfg)
    print("config confirmed")


def register(sub):
    p = sub.add_parser("init", help="create the audit folder and detect repos")
    p.add_argument("--repo", action="append", required=True, help="repo folder (repeatable)")
    p.set_defaults(func=cmd_init)
    p = sub.add_parser("detect", help="print what the scripts detect")
    p.set_defaults(func=cmd_detect)
    p = sub.add_parser("summary", help="print the config for the user to approve")
    p.set_defaults(func=cmd_summary)
    p = sub.add_parser("memory", help="record the user's permanent memory choice")
    p.add_argument("kind", choices=["grimoira", "none"])
    p.add_argument("--instance", help="grimoira instance name")
    p.add_argument("--words", help="the user's own words (required)")
    p.set_defaults(func=cmd_memory)
    p = sub.add_parser("confirm", help="mark the config as approved by the user")
    p.set_defaults(func=cmd_confirm)
