import fnmatch
import hashlib
import math
import os
import shutil

from .common import CrucibleError, Root, is_secret_file, numbered, read_json, split_lines, stamp, write_json

DEFAULT_UNIT_BYTES = 92160
# Measured on real runs: a reader costs about 29 tokens per line, the verifier adds about 15% of that.
READER_TOKENS_PER_LINE = 29
VERIFIER_SHARE = 0.15
# Under the output cut of common agent shell tools, so no page is truncated.
PAGE_CHARS = 24000
ALWAYS_SKIP = {".git", "node_modules", "vendor", "third_party", "__pycache__"}


def is_skipped(rel, skip):
    name = rel.rsplit("/", 1)[-1]
    for pattern in skip:
        pattern = pattern.replace("\\", "/").rstrip("/")
        if fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(name, pattern) or rel.startswith(pattern + "/"):
            return True
    return False


def is_binary(path):
    with open(path, "rb") as fh:
        return b"\0" in fh.read(8192)


def walk_text_files(repo_path, skip=(), include=()):
    """Sorted (relative posix path, absolute path, size) of every text file the audit reads."""
    found = []
    for folder, dirs, names in os.walk(repo_path):
        rel_folder = os.path.relpath(folder, repo_path).replace(os.sep, "/")
        rel_folder = "" if rel_folder == "." else rel_folder
        dirs[:] = sorted(d for d in dirs if d not in ALWAYS_SKIP
                         and not is_skipped((rel_folder + "/" + d).lstrip("/"), skip))
        for name in names:
            rel = (rel_folder + "/" + name).lstrip("/")
            full = os.path.join(folder, name)
            if name.startswith(("EXPECTED", "NOTES")) or is_secret_file(name) or os.path.islink(full) or is_skipped(rel, skip):
                continue
            if include and not any(rel == i.rstrip("/") or rel.startswith(i.rstrip("/") + "/") for i in include):
                continue
            if is_binary(full):
                continue
            found.append((rel, full, os.path.getsize(full)))
    return sorted(found)


def pack(files, unit_bytes):
    """Group whole files into units of at most unit_bytes; a bigger file is its own unit."""
    groups, cur, cur_bytes = [], [], 0
    for item in files:
        size = item[2]
        if size > unit_bytes:
            if cur:
                groups.append(cur)
                cur, cur_bytes = [], 0
            groups.append([item])
            continue
        if cur and cur_bytes + size > unit_bytes:
            groups.append(cur)
            cur, cur_bytes = [], 0
        cur.append(item)
        cur_bytes += size
    if cur:
        groups.append(cur)
    return groups


def file_sha256(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def mark_coverage(root, unit, status):
    """Record a unit's outcome on its files in coverage.json, so a later --delta can carry them."""
    path = root.p("coverage.json")
    coverage = read_json(path)
    if coverage is None:
        return
    for entry in coverage["files"].values():
        if entry["unit"] == unit:
            entry["status"] = status
    write_json(path, coverage)


def load_old_coverage(path):
    old = read_json(path)
    if not isinstance(old, dict) or not isinstance(old.get("files"), dict):
        raise CrucibleError(f"{path} is not a coverage.json (no 'files' object)")
    return old["files"]


def cmd_inventory(args):
    root = Root(args.root)
    root.require_confirmed()
    cfg = root.config()
    state = root.state()
    if any(u.get("status") != "pending" for u in state["units"].values()):
        raise CrucibleError("inventory refused: units already have progress; start a new audit folder to re-inventory")
    old = load_old_coverage(args.delta) if args.delta else {}
    for folder in ("units", "snapshot"):
        if os.path.isdir(root.p(folder)):
            shutil.rmtree(root.p(folder))
    from .lessons import sized_unit_bytes
    unit_bytes = sized_unit_bytes(root, cfg)
    scope = cfg.get("scope", {})
    state["units"] = {}
    coverage = {"files": {}}
    total_units = total_lines = carried_files = carried_units = 0
    for repo in cfg["repos"]:
        files = walk_text_files(repo["path"], scope.get("skip", []), scope.get("include", []))
        hashes = {rel: file_sha256(full) for rel, full, size in files}
        carried, changed = [], []
        for item in files:
            before = old.get(f"{repo['name']}/{item[0]}")
            same = before and before.get("sha256") == hashes[item[0]] and before.get("status") in ("done", "carried")
            (carried if same else changed).append(item)
        groups = [(g, False) for g in pack(changed, unit_bytes)] + [(g, True) for g in pack(carried, unit_bytes)]
        for index, (group, is_carried) in enumerate(groups, 1):
            unit = f"{repo['name']}-u{index:02d}"
            paths, lines = [], 0
            origins = set()
            for rel, full, size in group:
                dest = root.p("snapshot", repo["name"], *rel.split("/"))
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                shutil.copyfile(full, dest)
                with open(dest, "rb") as fh:
                    lines += len(split_lines(fh.read()))
                paths.append(rel)
                entry = {"sha256": hashes[rel], "unit": unit, "status": "carried" if is_carried else "pending"}
                if is_carried:
                    before = old[f"{repo['name']}/{rel}"]
                    entry["from"] = before.get("from") or before["unit"]
                    origins.add(entry["from"])
                coverage["files"][f"{repo['name']}/{rel}"] = entry
            write_json(root.p("units", unit + ".json"), {
                "unit": unit, "repo": repo["name"], "files": paths, "lines": lines,
                "bytes": sum(g[2] for g in group), "parent": None})
            if is_carried:
                state["units"][unit] = {"status": "carried", "carried_from": sorted(origins)}
                carried_units += 1
                carried_files += len(paths)
            else:
                state["units"][unit] = {"status": "pending"}
                total_lines += lines
            total_units += 1
    root.save_state(state)
    write_json(root.p("coverage.json"), coverage)
    from .lessons import reader_addenda
    addenda = reader_addenda(root)
    for name in root.units() if addenda else []:
        write_json(root.p("units", name + ".json"), dict(root.unit(name), reader_addenda=addenda))
    from .system import apply_leads
    apply_leads(root)
    message = f"inventory: {total_units} units, {total_lines} lines, {len(cfg['repos'])} repos"
    if args.delta:
        message += f"; {carried_files} unchanged files carried in {carried_units} units"
    print(message)


def cmd_estimate(args):
    root = Root(args.root)
    root.require_confirmed()
    cfg = root.config()
    state = root.state()["units"]
    units = [root.unit(n) for n in root.units() if state.get(n, {}).get("status") not in ("split", "carried")]
    lines = sum(u["lines"] for u in units)
    budget = cfg["budget"]
    from .lessons import forecast_factor
    reader = round(lines * READER_TOKENS_PER_LINE * forecast_factor(root))
    verifier = math.ceil(reader * VERIFIER_SHARE)
    tokens = reader + verifier
    print(f"units: {len(units)}")
    print(f"lines: {lines}")
    print(f"reader tokens: {reader} ({READER_TOKENS_PER_LINE} per line)")
    print(f"verifier tokens: {verifier} ({int(VERIFIER_SHARE * 100)}% on top of the reader)")
    print(f"tokens: {tokens} (about {tokens / lines:.0f} per line)" if lines else f"tokens: {tokens}")
    from .models import plan_for, tier_lines
    plan = plan_for(root)
    for line in tier_lines(plan["estimate"]):
        print(line)
    print(f"judgment tokens: {plan['judgment_tokens']} (in the tiers above, not in the tokens total)")
    cap = budget["max_tokens"]
    print("cap: " + (f"{cap}" + (" (estimate is over the cap)" if tokens > cap else "") if cap else "none set"))


def page_ranges(lines):
    """[(a, b)] pages of one file; an empty file is the single page (0, 0)."""
    if not lines:
        return [(0, 0)]
    pages, start, size = [], 1, 0
    for i, line in enumerate(lines, 1):
        cost = len(line) + 8
        if size and size + cost > PAGE_CHARS:
            pages.append((start, i - 1))
            start, size = i, 0
        size += cost
    pages.append((start, len(lines)))
    return pages


def cmd_show(args):
    root = Root(args.root)
    root.require_confirmed()
    unit = root.unit(args.unit)
    if args.file not in unit["files"]:
        raise CrucibleError(f"{args.file} is not in unit {args.unit}")
    lines = root.snapshot_lines(unit["repo"], args.file)
    pages = page_ranges(lines)
    if not 1 <= args.page <= len(pages):
        raise CrucibleError(f"page {args.page} of {len(pages)}")
    a, b = pages[args.page - 1]
    body = numbered(lines, a, b)
    print(f"=== {args.file} {stamp(root.key(), args.file, a, b, len(lines), body)} {a}-{b}/{len(lines)} ===")
    if body:
        print(body)
    print(f"=== END {args.file} ===")
    if args.page < len(pages):
        print(f"=== NEXT: show {args.unit} {args.file} --page {args.page + 1} ===")


def register(sub):
    p = sub.add_parser("inventory", help="split the confirmed scope into units and snapshot the files")
    p.add_argument("--delta", metavar="OLD_COVERAGE_JSON",
                   help="carry files unchanged since that earlier audit's coverage.json instead of re-reading them")
    p.set_defaults(func=cmd_inventory)
    p = sub.add_parser("estimate", help="units, lines and estimated tokens")
    p.set_defaults(func=cmd_estimate)
    p = sub.add_parser("show", help="print a unit file with keyed stamps")
    p.add_argument("unit")
    p.add_argument("file")
    p.add_argument("--page", type=int, default=1)
    p.set_defaults(func=cmd_show)
