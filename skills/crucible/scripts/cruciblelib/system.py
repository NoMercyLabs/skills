"""The system around the audited repo: layout, related repos, the base folder and the repo graph.

Facts come from files, by script. A related repo or an edge is listed only with the file and line that point to it.
"""
import hashlib
import json
import os
import re
import shutil
import stat

from .common import CrucibleError, Root, is_secret_file, mask_secrets, read_json, split_lines, write_json
from . import clones
from .config import detect_repo, git, remote_owner, unique_names
from .inventory import ALWAYS_SKIP, walk_text_files
from .trackers import github as gh_adapter

LAYOUTS = ("single", "monorepo", "multi-repo")
MODES = ("base_folder", "existing_checkouts", "this_repo")
MODE_WORDS = {"base_folder": "a new base folder", "existing_checkouts": "existing checkouts, read-only",
              "this_repo": "this repo only"}
LOST_DEPTH = ("the other side of each contract", "consumers in other repos", "fixes that need both sides")
WORKSPACE_MARKERS = ("pnpm-workspace.yaml", "lerna.json", "nx.json", "turbo.json", "go.work", "rush.json")
MANIFESTS = ("package.json", "pyproject.toml", "go.mod", "Cargo.toml", "composer.json", "pom.xml", "build.gradle",
             "build.gradle.kts")
LOCK_FILES = ("package-lock.json", "yarn.lock", "pnpm-lock.yaml", "composer.lock", "Cargo.lock", "poetry.lock")
MAX_SCAN_BYTES = 1024 * 1024


def is_repo(path):
    return os.path.exists(os.path.join(path, ".git"))


def rel_lines(full):
    with open(full, "rb") as fh:
        return split_lines(fh.read())


# ---------------------------------------------------------------- layout

def find_manifests(path):
    found = []
    for folder, dirs, names in os.walk(path):
        rel_folder = os.path.relpath(folder, path).replace(os.sep, "/")
        depth = 0 if rel_folder == "." else rel_folder.count("/") + 1
        dirs[:] = sorted(d for d in dirs if d not in ALWAYS_SKIP and not d.startswith(".") and depth < 3)
        if depth == 0:
            continue
        if any(n in MANIFESTS or n.endswith(".csproj") for n in names):
            found.append(rel_folder)
    return found


def has_workspace_marker(path):
    if any(os.path.exists(os.path.join(path, m)) for m in WORKSPACE_MARKERS):
        return True
    package = os.path.join(path, "package.json")
    if os.path.isfile(package):
        try:
            if "workspaces" in json.loads("\n".join(rel_lines(package))):
                return True
        except ValueError:
            pass
    cargo = os.path.join(path, "Cargo.toml")
    return os.path.isfile(cargo) and any(ln.strip() == "[workspace]" for ln in rel_lines(cargo))


def detect_layout(path):
    path = os.path.abspath(path)
    if not os.path.isdir(path):
        raise CrucibleError(f"{path} is not a folder")
    if is_repo(path):
        packages = find_manifests(path)
        mono = has_workspace_marker(path) or len(packages) >= 2
        return {"layout": "monorepo" if mono else "single", "path": path, "packages": packages,
                "repos": [{"name": os.path.basename(path), "path": path}]}
    children = sorted(d for d in os.listdir(path) if os.path.isdir(os.path.join(path, d)) and is_repo(os.path.join(path, d)))
    if not children:
        raise CrucibleError(f"no git repo at {path} and none in the folders below it")
    repos = [{"name": d, "path": os.path.join(path, d)} for d in children]
    return {"layout": "multi-repo" if len(children) > 1 else "single", "path": path, "packages": [], "repos": repos}


def cmd_layout(args):
    found = detect_layout(args.path)
    print(f"layout: {found['layout']}")
    print(f"path: {found['path']}")
    print("repos: " + ", ".join(r["name"] for r in found["repos"]))
    if found["packages"]:
        print("packages: " + ", ".join(found["packages"]))
    print("next: `crucible init --repo PATH` for each repo, then `crucible related` to find the rest of the system")
    print("base folder: offered for every layout (a fresh folder outside your repos holding read-only clones and "
          "the audit files): `crucible workspace plan --base PATH`")


# ---------------------------------------------------------------- evidence in the code

API_LINE = re.compile(r"(?i)(base[_-]?url|api[_-]?(url|host|base)|server[_-]?url|endpoint|backend[_-]?url|service[_-]?url)")
URL = re.compile(r"https?://([A-Za-z0-9][A-Za-z0-9._-]*)(?::\d+)?[^\s'\"`)>,]*")
LOCAL_HOSTS = ("localhost", "127.0.0.1", "0.0.0.0", "w3.org", "www.w3.org", "schema.org", "json-schema.org")
CODE_SUFFIXES = (".py", ".js", ".jsx", ".mjs", ".ts", ".tsx", ".vue", ".go", ".rs", ".java", ".kt", ".cs", ".php",
                 ".rb", ".swift", ".json", ".yml", ".yaml", ".toml", ".env.example", ".ini", ".cfg", ".properties")
SCHEMA_SUFFIXES = (".proto", ".graphql", ".gql", ".avsc")
OPENAPI_NAME = re.compile(r"^(openapi|swagger)[\w.-]*\.(json|ya?ml)$", re.I)
COMPOSE_NAME = re.compile(r"^(docker-)?compose[\w.-]*\.ya?ml$", re.I)
COMPOSE_BUILD = re.compile(r"^\s*(?:build|context)\s*:\s*['\"]?(\.\.[^\s'\"#]*)")
COMPOSE_IMAGE = re.compile(r"^\s*image\s*:\s*['\"]?([^\s'\"#]+)")
CI_REFS = (re.compile(r"\brepository\s*:\s*['\"]?([\w.-]+)/([\w.-]+)"),
           re.compile(r"\brepos/([\w.-]+)/([\w.-]+)/(?:dispatches|actions|releases|deployments)"),
           re.compile(r"(?:\s-R|\s--repo)[ =]([\w.-]+)/([\w.-]+)"))
GIT_URL = re.compile(r"git\+?(?:https?|ssh)://(?:[^/\s@]+@)?[^/\s]+/([\w.-]+)/([\w.-]+?)(?:\.git)?(?=[\s@#'\"]|$)")
GIT_FILES = ("requirements.txt", "pyproject.toml", "Cargo.toml")
CARGO_PATH = re.compile(r"\bpath\s*=\s*['\"](\.\.[^'\"]*)")
LOCAL_VERSION = re.compile(r"^(workspace:|file:|link:)")


def hit(kind, target, path, line, text, detail=""):
    return {"kind": kind, "target": target, "ref": f"{path}:{line}", "quote": mask_secrets(text.strip())[:200],
            "detail": detail}


def line_of(lines, needle):
    for number, text in enumerate(lines, 1):
        if needle in text:
            return number
    return 1


def package_hits(rel, lines, all_deps):
    try:
        data = json.loads("\n".join(lines))
    except ValueError:
        return []
    if not isinstance(data, dict):
        return []
    own = str(data.get("name") or "")
    scope = own.split("/")[0] + "/" if own.startswith("@") else None
    out = []
    for section in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        for name, version in (data.get(section) or {}).items():
            same_scope = bool(scope) and name.startswith(scope) and name != own
            local = bool(LOCAL_VERSION.match(str(version)))
            if same_scope or local or all_deps:
                number = line_of(lines, f'"{name}"')
                out.append(hit("dependency", name, rel, number, lines[number - 1], "package"))
    return out


def composer_hits(rel, lines, all_deps):
    try:
        data = json.loads("\n".join(lines))
    except ValueError:
        return []
    own = str(data.get("name") or "") if isinstance(data, dict) else ""
    vendor = own.split("/")[0] + "/" if "/" in own else None
    out = []
    for name in ((data.get("require") or {}) if isinstance(data, dict) else {}):
        if name != own and "/" in name and (all_deps or (vendor and name.startswith(vendor))):
            number = line_of(lines, f'"{name}"')
            out.append(hit("dependency", name, rel, number, lines[number - 1], "composer"))
    return out


def gomod_hits(rel, lines, all_deps):
    module = next((ln.split()[1] for ln in lines if ln.startswith("module ") and len(ln.split()) > 1), "")
    prefix = "/".join(module.split("/")[:2]) + "/" if module.count("/") >= 2 else None
    out = []
    for number, text in enumerate(lines, 1):
        parts = text.replace("require ", "", 1).split()
        if "=>" in parts:
            local = parts[parts.index("=>") + 1]
            if local.startswith(".."):
                out.append(hit("dependency", os.path.basename(local.rstrip("/")), rel, number, text, "go replace"))
            continue
        if len(parts) >= 2 and "/" in parts[0] and re.match(r"v\d", parts[1]) and parts[0] != module:
            if all_deps or (prefix and parts[0].startswith(prefix)):
                out.append(hit("dependency", parts[0], rel, number, text, "go module"))
    return out


def url_hits(rel, lines):
    out = []
    for number, text in enumerate(lines, 1):
        if not API_LINE.search(text):
            continue
        for match in URL.finditer(text):
            host = match.group(1).lower()
            if host not in LOCAL_HOSTS:
                out.append(hit("api_url", host, rel, number, text))
                break
    return out


def openapi_hits(rel, lines):
    number = next((n for n, t in enumerate(lines, 1) if re.search(r"\"?url\"?\s*:", t)), 0)
    host = None
    if number:
        match = URL.search(lines[number - 1])
        host = match.group(1).lower() if match else None
    return [hit("openapi", host or rel, rel, number or 1, lines[(number or 1) - 1] if lines else "")]


def compose_hits(rel, lines):
    out = []
    for number, text in enumerate(lines, 1):
        match = COMPOSE_BUILD.match(text)
        if match:
            name = os.path.basename(match.group(1).replace("\\", "/").rstrip("/"))
            if name and name != "..":
                out.append(hit("compose", name, rel, number, text, "build context"))
            continue
        match = COMPOSE_IMAGE.match(text)
        if match and "${" not in match.group(1) and "/" in match.group(1):
            image = re.sub(r"[@:][^/]*$", "", match.group(1))
            parts = image.split("/")
            out.append(hit("compose", parts[-1], rel, number, text, "/".join(parts[-2:])))
    return out


def ci_hits(rel, lines, own_slug):
    out = []
    for number, text in enumerate(lines, 1):
        for pattern in CI_REFS:
            for owner, name in pattern.findall(text):
                if f"{owner}/{name}".lower() != own_slug:
                    out.append(hit("ci_deploy", name, rel, number, text, f"{owner}/{name}"))
    return out


def git_ref_hits(rel, lines):
    out = []
    for number, text in enumerate(lines, 1):
        for owner, name in GIT_URL.findall(text):
            out.append(hit("git_dependency", name, rel, number, text, f"{owner}/{name}"))
        match = CARGO_PATH.search(text) if rel.endswith("Cargo.toml") else None
        if match:
            out.append(hit("dependency", os.path.basename(match.group(1).rstrip("/")), rel, number, text, "cargo path"))
    return out


def submodule_hits(rel, lines):
    out = []
    for number, text in enumerate(lines, 1):
        match = re.match(r"^\s*url\s*=\s*(\S+)", text)
        if match:
            name = re.sub(r"\.git$", "", match.group(1).rstrip("/").replace("\\", "/").rsplit("/", 1)[-1].rsplit(":", 1)[-1])
            out.append(hit("submodule", name, rel, number, text, match.group(1)))
    return out


def own_slug(path):
    remote = git(path, "remote", "get-url", "origin") if is_repo(path) else ""
    match = re.search(r"[:/]([^/:]+/[^/]+?)(?:\.git)?/?$", remote)
    return match.group(1).lower() if match else ""


def scan_evidence(path, all_deps=False):
    """Every pointer from this repo to something outside it: -> list of hit dicts with kind, target, ref, quote."""
    slug = own_slug(path)
    hits = []
    for rel, full, size in walk_text_files(path):
        name = rel.rsplit("/", 1)[-1]
        lowered = rel.lower()
        if size > MAX_SCAN_BYTES or name in LOCK_FILES:
            continue
        if name.endswith(SCHEMA_SUFFIXES) or name == "schema.json" or name.endswith(".schema.json"):
            hits.append(hit("shared_schema", name, rel, 1, rel_lines(full)[0] if size else rel))
            continue
        lines = rel_lines(full)
        if name == ".gitmodules":
            hits += submodule_hits(rel, lines)
        elif name == "package.json":
            hits += package_hits(rel, lines, all_deps)
        elif name == "composer.json":
            hits += composer_hits(rel, lines, all_deps)
        elif name == "go.mod":
            hits += gomod_hits(rel, lines, all_deps)
        elif OPENAPI_NAME.match(name):
            hits += openapi_hits(rel, lines)
        elif COMPOSE_NAME.match(name):
            hits += compose_hits(rel, lines)
        if lowered.startswith(".github/workflows/") or name in (".gitlab-ci.yml", "Jenkinsfile", "azure-pipelines.yml"):
            hits += ci_hits(rel, lines, slug)
        if name in GIT_FILES or (name.startswith("requirements") and name.endswith(".txt")):
            hits += git_ref_hits(rel, lines)
        if name.endswith(CODE_SUFFIXES) and name not in ("package.json", "composer.json") and not OPENAPI_NAME.match(name):
            hits += url_hits(rel, lines)
    seen, unique = set(), []
    for item in hits:
        key = (item["kind"], item["target"], item["ref"])
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def same_owner_hits(entry, repos):
    """Read-only `gh` listing (through the adapter) turned into candidates; each points at the origin line in .git/config."""
    config = os.path.join(entry["path"], ".git", "config")
    number, text = 1, entry["remote"]
    if os.path.isfile(config):
        for n, line in enumerate(rel_lines(config), 1):
            if line.strip().startswith("url") and entry["remote"] in line:
                number, text = n, line
                break
    out = []
    for row in repos:
        if row["name"].lower() == entry["name"].lower() or row["name"].lower() == own_slug(entry["path"]).split("/")[-1]:
            continue
        item = hit("same_owner", row["name"], ".git/config", number, text, f"{entry['owner']}/{row['name']}")
        item["info"] = {k: row.get(k) for k in ("visibility", "branch", "size_kb")}
        out.append(item)
    return out


def cmd_related(args):
    root = Root(args.root)
    cfg = root.config()
    lines, rows = [], []
    for entry in cfg["repos"]:
        if args.repo and entry["name"] != args.repo:
            continue
        found = scan_evidence(entry["path"])
        if args.same_owner:
            if not entry["owner"]:
                lines.append(f"same-owner repos: not checked for {entry['name']} (no git remote owner)")
            else:
                try:
                    found += same_owner_hits(entry, gh_adapter.owner_repos(entry["owner"]))
                except CrucibleError as exc:
                    lines.append(f"same-owner repos: not checked ({exc})")
        for item in found:
            item["repo"] = entry["name"]
            rows.append(item)
            lines.append(f"{entry['name']}: {item['target']} ({item['kind']}) {item['ref']}: {item['quote']}")
    write_json(root.p("related.json"), {"candidates": rows})
    targets = {(r["kind"], r["target"]) for r in rows}
    print(f"related repos: {len(rows)} pointers to {len(targets)} targets, each with file:line")
    print("\n".join(lines))
    print("ask the user which belong to the system; a pointer is evidence, not proof that the target is a repo")


# ---------------------------------------------------------------- the base folder

def norm(path):
    return os.path.normcase(os.path.realpath(os.path.abspath(path)))


def inside(child, parent):
    child, parent = norm(child), norm(parent)
    return child == parent or child.startswith(parent.rstrip(os.sep) + os.sep)


def human(size):
    if size is None:
        return "unknown"
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{size} B"
        size /= 1024.0
    return "unknown"


def dir_size(path):
    total = 0
    for folder, dirs, names in os.walk(path):
        for name in names:
            try:
                total += os.path.getsize(os.path.join(folder, name))
            except OSError:
                pass
    return total


def source_branch(root, source):
    if os.path.isdir(source):
        return git(source, "symbolic-ref", "--short", "HEAD") or "detached"
    return clones.ls_remote_branch(root, source)


def check_base(base, user_paths):
    base = os.path.abspath(base)
    for path in user_paths:
        if inside(base, path):
            raise CrucibleError(f"refused: {base} is inside your repo {path}; the base folder is outside your repos")
    if os.path.exists(base) and (not os.path.isdir(base) or os.listdir(base)):
        raise CrucibleError(f"refused: {base} is not empty; the base folder is a fresh folder")
    return base


def clone_plan(root, cfg, base, sources):
    paths = [os.path.abspath(s) if os.path.isdir(s) else s for s in sources]
    known = {norm(r["path"]): r["name"] for r in cfg["repos"]}
    taken = {r["name"] for r in cfg["repos"]}
    rows = []
    for source in paths:
        if os.path.isdir(source) and norm(source) in known:
            name = known[norm(source)]
        else:
            tail = re.sub(r"\.git$", "", source.rstrip("/\\").replace("\\", "/").rsplit("/", 1)[-1].rsplit(":", 1)[-1])
            name = unique_names([tail])[0]
            while name in taken:
                name += "-2"
            taken.add(name)
        size = dir_size(source) if os.path.isdir(source) else None
        rows.append({"name": name, "source": source, "branch": source_branch(root, source), "size_bytes": size,
                     "dest": os.path.join(base, name)})
    return rows


def default_sources(cfg, args):
    return list(args.repo or [r["path"] for r in cfg["repos"]])


def cmd_ws_plan(args):
    root = Root(args.root)
    cfg = root.config()
    sources = default_sources(cfg, args)
    base = check_base(args.base, [r["path"] for r in cfg["repos"]] + [s for s in sources if os.path.isdir(s)])
    rows = clone_plan(root, cfg, base, sources)
    print(f"base folder: {base} (fresh, outside your repos)")
    for row in rows:
        print(f"  {row['name']}: branch {row['branch']}, disk {human(row['size_bytes'])}, from {row['source']}")
    known = [r["size_bytes"] for r in rows if r["size_bytes"] is not None]
    print(f"total disk: {human(sum(known))}" + ("" if len(known) == len(rows) else " (some sizes unknown)"))
    print("your own checkouts are never touched, switched or written; each clone is a separate read-only copy")
    print(f"audit folder inside it: {os.path.join(base, 'crucible-audit')} (use it as --root)")
    names = ",".join(r["name"] for r in rows)
    print(f"cloning needs a grant: `crucible workspace choose base_folder --base {base} --words \"...\"`, then "
          f"`crucible grant workspace_clones yes --bound repos={names} --words \"...\"`")


def lost_depth_text():
    return ("this repo only loses: " + "; ".join(LOST_DEPTH)
            + ". A base folder or the existing checkouts of the other repos keep that depth.")


def read_only(path):
    for folder, dirs, names in os.walk(path):
        dirs[:] = [d for d in dirs if d != ".git"]
        for name in names:
            full = os.path.join(folder, name)
            if not os.path.islink(full):
                os.chmod(full, stat.S_IMODE(os.stat(full).st_mode) & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))


def workspace_summary(cfg):
    ws = cfg.get("workspace")
    if not ws:
        return "workspace: not answered (ask the user: a new base folder, existing checkouts, or this repo only)"
    if ws["mode"] == "this_repo":
        return "workspace: this repo only; " + lost_depth_text()
    if ws["mode"] == "existing_checkouts":
        return "workspace: existing checkouts, read-only (never switched or written)"
    return f"workspace: a new base folder {ws.get('base') or '(not set)'}, read-only clones"


def check_workspace(value):
    if not isinstance(value, dict) or value.get("mode") not in MODES:
        raise CrucibleError("workspace is an object: mode is one of " + ", ".join(MODES))
    if value["mode"] == "base_folder" and not str(value.get("base") or "").strip():
        raise CrucibleError("workspace base_folder needs base (the folder)")


def cmd_ws_choose(args):
    from .answer import set_answer
    root = Root(args.root)
    cfg = root.config()
    if not (args.words or "").strip():
        raise CrucibleError("refused: the workspace choice is the user's decision: ask the user, then record their "
                            "own words with --words")
    args.mode = "existing_checkouts" if args.mode == "existing" else args.mode
    value = {"mode": args.mode}
    if args.mode == "base_folder":
        if not args.base:
            raise CrucibleError("refused: base_folder needs --base FOLDER")
        value["base"] = check_base(args.base, [r["path"] for r in cfg["repos"]])
    elif args.mode == "existing_checkouts":
        value["repos"] = [os.path.abspath(p) for p in args.repo or []]
        for path in value["repos"]:
            if not os.path.isdir(path):
                raise CrucibleError(f"{path} is not a folder")
    cfg["workspace"] = None
    root.save_config(cfg)
    set_answer(root, "workspace", value, args.words or "")
    cfg = root.config()
    if args.mode == "existing_checkouts":
        names = {norm(r["path"]) for r in cfg["repos"]}
        have = {r["name"] for r in cfg["repos"]}
        for path in value["repos"]:
            if norm(path) in names:
                continue
            name = unique_names([path])[0]
            while name in have:
                name += "-2"
            have.add(name)
            cfg["repos"].append(detect_repo(name, path))
        root.save_config(cfg)
    print(workspace_summary(cfg))
    if args.mode == "existing_checkouts":
        print("the checkouts are read-only for the audit: readers use snapshots, nothing is switched or written, "
              "uncommitted work stays as it is")


def finish_clone(row):
    read_only(row["dest"])
    row["commit"] = git(row["dest"], "rev-parse", "HEAD")


def cmd_ws_clone(args):
    root = Root(args.root)
    cfg = root.config()
    ws = cfg.get("workspace") or {}
    base = os.path.abspath(args.base)
    if ws.get("mode") != "base_folder" or norm(ws.get("base", "")) != norm(base):
        raise CrucibleError("refused: the user has not chosen this base folder: run `crucible workspace choose "
                            "base_folder --base FOLDER --words \"...\"` first")
    sources = default_sources(cfg, args)
    user_paths = [r["path"] for r in cfg["repos"]] + [s for s in sources if os.path.isdir(s)]
    check_base(base, user_paths)
    rows = clone_plan(root, cfg, base, sources)
    clones.clone_repos(root, rows, base, finish_clone)
    by_source = {norm(r["path"]): r for r in cfg["repos"] if os.path.isdir(r["path"])}
    for row in rows:
        old = by_source.get(norm(row["source"])) if os.path.isdir(row["source"]) else None
        entry = detect_repo(row["name"], row["dest"])
        remote = git(row["source"], "remote", "get-url", "origin") if os.path.isdir(row["source"]) else row["source"]
        entry["remote"], entry["owner"] = remote or entry["remote"], remote_owner(remote or "")
        entry["source"] = row["source"]
        if old:
            entry["public"], entry["instances"] = old.get("public"), old.get("instances", [])
            cfg["repos"][cfg["repos"].index(old)] = entry
        else:
            cfg["repos"].append(entry)
        print(f"{row['name']}: branch {row['branch']}, commit {row['commit'][:10]}, disk {human(row['size_bytes'])}, "
              f"read-only clone at {row['dest']}")
    cfg["confirmed"] = False
    root.save_config(cfg)
    write_json(root.p("workspace.json"), {"base": base, "repos": rows})
    print("your own checkouts were not touched; the repos now point at the clones; run `crucible summary` and "
          "`crucible confirm` again")


# ---------------------------------------------------------------- the graph

def identities(entry):
    names = {entry["name"].lower(), os.path.basename(os.path.normpath(entry.get("source") or entry["path"])).lower()}
    remote = entry.get("remote", "")
    tail = re.sub(r"\.git$", "", remote.rstrip("/").replace("\\", "/").rsplit("/", 1)[-1])
    if tail:
        names.add(tail.lower())
    path = entry["path"]
    for rel, key in (("package.json", "name"), ("composer.json", "name")):
        data = read_json(os.path.join(path, rel), {}) if os.path.isfile(os.path.join(path, rel)) else {}
        value = str(data.get(key) or "") if isinstance(data, dict) else ""
        if value:
            names.add(value.lower())
            names.add(value.split("/")[-1].lower())
    gomod = os.path.join(path, "go.mod")
    if os.path.isfile(gomod):
        for line in rel_lines(gomod):
            if line.startswith("module "):
                module = line.split()[1].lower()
                names.update({module, module.split("/")[-1]})
    for rel, pattern in (("Cargo.toml", r'^name\s*=\s*"([^"]+)"'), ("pyproject.toml", r'^name\s*=\s*"([^"]+)"')):
        if os.path.isfile(os.path.join(path, rel)):
            for line in rel_lines(os.path.join(path, rel)):
                match = re.match(pattern, line.strip())
                if match:
                    names.add(match.group(1).lower())
    return {n for n in names if n}


EDGE_KINDS = {"dependency": "dependency", "git_dependency": "dependency", "submodule": "submodule",
              "compose": "compose", "ci_deploy": "ci_deploy", "api_url": "api_url"}


def resolve(item, targets):
    """-> repo names whose identity the pointer names exactly; a host matches by one of its dot-separated labels."""
    target = item["target"].lower()
    if item["kind"] == "api_url":
        labels = set(target.split("."))
        return [name for name, ids in targets.items() if any(len(i) >= 4 and i in labels for i in ids)]
    return [name for name, ids in targets.items() if target in ids]


def schema_hashes(path):
    out = {}
    for rel, full, size in walk_text_files(path):
        name = rel.rsplit("/", 1)[-1]
        if name.endswith(SCHEMA_SUFFIXES):
            with open(full, "rb") as fh:
                out[rel] = (hashlib.sha256(fh.read()).hexdigest(), full)
    return out


def build_graph(cfg):
    repos = cfg["repos"]
    ids = {r["name"]: identities(r) for r in repos}
    edges, seen = [], set()

    def add(src, dst, kind, evidence):
        key = (src, dst, kind, tuple(e["ref"] + e["repo"] for e in evidence))
        if src != dst and key not in seen:
            seen.add(key)
            edges.append({"from": src, "to": dst, "kind": kind, "evidence": evidence})

    for entry in repos:
        others = {n: v for n, v in ids.items() if n != entry["name"]}
        for item in scan_evidence(entry["path"], all_deps=True):
            if item["kind"] not in EDGE_KINDS:
                continue
            for target in resolve(item, others):
                add(entry["name"], target, EDGE_KINDS[item["kind"]],
                    [{"repo": entry["name"], "ref": item["ref"], "quote": item["quote"]}])
    hashes = {r["name"]: schema_hashes(r["path"]) for r in repos}
    names = sorted(hashes)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            for rel_a, (sha_a, _) in sorted(hashes[a].items()):
                for rel_b, (sha_b, _) in sorted(hashes[b].items()):
                    if sha_a == sha_b and rel_a.rsplit("/", 1)[-1] == rel_b.rsplit("/", 1)[-1]:
                        add(a, b, "shared_schema",
                            [{"repo": a, "ref": f"{rel_a}:1", "quote": rel_lines(hashes[a][rel_a][1])[0] if rel_lines(hashes[a][rel_a][1]) else rel_a},
                             {"repo": b, "ref": f"{rel_b}:1", "quote": rel_lines(hashes[b][rel_b][1])[0] if rel_lines(hashes[b][rel_b][1]) else rel_b}])
    edges.sort(key=lambda e: (e["from"], e["to"], e["kind"], e["evidence"][0]["ref"]))
    return {"repos": [r["name"] for r in repos], "edges": edges}


def apply_leads(root):
    """Write each unit's cross-repo leads (the edges that touch its repo) into the unit file the reader opens."""
    graph = read_json(root.p("graph.json"))
    if not graph:
        return 0
    count = 0
    for name in root.units():
        unit = root.unit(name)
        leads = []
        for edge in graph["edges"]:
            if edge["from"] == unit["repo"]:
                leads.append({"other_repo": edge["to"], "direction": "uses", "kind": edge["kind"],
                              "evidence": edge["evidence"]})
            elif edge["to"] == unit["repo"]:
                leads.append({"other_repo": edge["from"], "direction": "used_by", "kind": edge["kind"],
                              "evidence": edge["evidence"]})
        unit.pop("cross_repo", None)
        if leads:
            unit["cross_repo"] = leads
            count += 1
        write_json(root.p("units", name + ".json"), unit)
    return count


def cmd_graph(args):
    root = Root(args.root)
    root.require_confirmed()
    graph = build_graph(root.config())
    write_json(root.p("graph.json"), graph)
    print(f"graph: {len(graph['repos'])} repos, {len(graph['edges'])} edges, each with file:line evidence")
    for edge in graph["edges"]:
        first = edge["evidence"][0]
        print(f"{edge['from']} -> {edge['to']} {edge['kind']} {first['ref']}: {first['quote']}")
    units = apply_leads(root)
    if units:
        print(f"cross-repo leads written into {units} units")
    print("a finding about a contract between two repos cites both sides (`cross_repo` and evidence with `repo`)")


def register(sub):
    p = sub.add_parser("layout", help="single repo, monorepo or a folder holding many repos")
    p.add_argument("path", nargs="?", default=".")
    p.set_defaults(func=cmd_layout)
    p = sub.add_parser("related", help="repos the code points to, each with file:line")
    p.add_argument("--repo", help="only this repo of the config")
    p.add_argument("--same-owner", action="store_true", help="also list other repos of the same owner (read-only gh)")
    p.set_defaults(func=cmd_related)
    p = sub.add_parser("workspace", help="the base folder, existing checkouts or this repo only")
    wsub = p.add_subparsers(dest="workspace_command", metavar="step")
    q = wsub.add_parser("plan", help="show the clones: branch and disk size per repo")
    q.add_argument("--base", required=True)
    q.add_argument("--repo", action="append", help="repo folder or URL (default: the config repos)")
    q.set_defaults(func=cmd_ws_plan)
    q = wsub.add_parser("choose", help="record the user's choice")
    q.add_argument("mode", choices=MODES + ("existing", ))
    q.add_argument("--base", help="the fresh base folder")
    q.add_argument("--repo", action="append", help="an existing checkout (existing_checkouts)")
    q.add_argument("--words", help="the user's own words (required)")
    q.set_defaults(func=cmd_ws_choose)
    q = wsub.add_parser("clone", help="clone the repos read-only into the base folder (needs a grant)")
    q.add_argument("--base", required=True)
    q.add_argument("--repo", action="append", help="repo folder or URL (default: the config repos)")
    q.set_defaults(func=cmd_ws_clone)
    p = sub.add_parser("graph", help="edges between repos with file:line evidence; cross-repo leads for readers")
    p.set_defaults(func=cmd_graph)
