import os
import shutil

from .common import AssayError, Root, read_json, split_lines, write_json


def file_sizes(root, unit):
    repo = unit["repo"]
    return [(path, os.path.getsize(root.p("snapshot", repo, *path.split("/")))) for path in unit["files"]]


def balanced_cut(sizes):
    """Index that splits the files in two parts of the closest byte counts, both non-empty."""
    total, running, best, best_gap = sum(s for _, s in sizes), 0, 1, None
    for i in range(1, len(sizes)):
        running += sizes[i - 1][1]
        gap = abs(total - 2 * running)
        if best_gap is None or gap < best_gap:
            best, best_gap = i, gap
    return best


def park(root, relative):
    """Move a unit file into parked/, keeping its folder, so nothing is deleted."""
    source = root.p(*relative)
    if not os.path.exists(source):
        return
    target = root.p("parked", *relative)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    if os.path.exists(target):
        os.remove(target)
    shutil.move(source, target)


def cmd_split(args):
    root = Root(args.root)
    root.require_confirmed()
    name = args.unit
    unit = root.unit(name)
    state = root.state()
    status = state["units"].get(name, {}).get("status", "pending")
    if status in ("split", "done", "carried"):
        raise AssayError(f"split refused: {name} is {status}")
    if len(unit["files"]) < 2:
        raise AssayError(f"split refused: {name} holds one file and units are whole files; skip it with a reason or raise unit_bytes")
    parts = (name + "a", name + "b")
    if any(os.path.exists(root.p("units", p + ".json")) for p in parts):
        raise AssayError(f"split refused: {parts[0]} or {parts[1]} already exists")
    sizes = file_sizes(root, unit)
    cut = balanced_cut(sizes)
    for part, chosen in zip(parts, (sizes[:cut], sizes[cut:])):
        paths = [p for p, _ in chosen]
        lines = 0
        for path in paths:
            with open(root.p("snapshot", unit["repo"], *path.split("/")), "rb") as fh:
                lines += len(split_lines(fh.read()))
        write_json(root.p("units", part + ".json"), {
            "unit": part, "repo": unit["repo"], "files": paths, "lines": lines,
            "bytes": sum(s for _, s in chosen), "parent": name})
        state["units"][part] = {"status": "pending"}
    for relative in (("candidates", name + ".json"), ("ledger", name + ".json"),
                     ("review", f"verdicts-{name}.json")):
        park(root, relative)
    entry = state["units"].setdefault(name, {})
    entry["status"] = "split"
    entry["parts"] = list(parts)
    entry.pop("proof", None)
    root.save_state(state)
    coverage = read_json(root.p("coverage.json"))
    if coverage:
        member = {p: part for part in parts for p in read_json(root.p("units", part + ".json"))["files"]}
        for key, entry in coverage["files"].items():
            if entry["unit"] == name and key.split("/", 1)[1] in member:
                entry["unit"] = member[key.split("/", 1)[1]]
        write_json(root.p("coverage.json"), coverage)
    print(f"split {name} into {parts[0]} ({cut} files) and {parts[1]} ({len(sizes) - cut} files); old candidates parked")


def register(sub):
    p = sub.add_parser("split", help="split a unit too big for one reader into two parts")
    p.add_argument("unit")
    p.set_defaults(func=cmd_split)
