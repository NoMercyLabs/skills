#!/usr/bin/env python3
"""Mechanical gates for the atlas skill.

Every check here fails loudly on a condition the skill would otherwise only
promise to honor. Nothing in it knows anything about a particular project.

    check_docs.py status   --map docs-work/map.md --reviews docs-work/reviews
    check_docs.py coverage --slices docs-work/slices --src src
    check_docs.py map     --map docs-work/map.md --src src
    check_docs.py reviews --map docs-work/map.md --reviews docs-work/reviews
    check_docs.py links   --map docs-work/map.md --docs docs
    check_docs.py mermaid --map docs-work/map.md
    check_docs.py all      --map docs-work/map.md --src src --docs docs

Exit code 0 means the gate passed. Anything else means it did not.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys

TIERS = {"introduce", "quickstart", "examples", "reference", "catalog"}
STATUSES = {"planned", "drafted", "reviewed"}
COLUMNS = ["page", "tier", "job", "owns", "assumes", "links to", "covers", "status"]

# Named the other way round on purpose. An allow-list of source extensions makes
# every language nobody thought of invisible, which is a silent hole in the
# denominator. Anything not named here counts as source, so an unfamiliar file
# type shows up as unread rather than as covered.
NON_SOURCE_SUFFIXES = (
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".bmp", ".ico", ".svg",
    ".mp3", ".mp4", ".wav", ".flac", ".ogg", ".webm", ".mov", ".avi", ".mkv",
    ".ttf", ".otf", ".woff", ".woff2", ".eot",
    ".zip", ".gz", ".tar", ".bz2", ".xz", ".7z", ".rar", ".jar", ".war",
    ".pdf", ".psd", ".ai", ".sketch", ".fig", ".blend", ".fbx", ".glb", ".gltf",
    ".exe", ".dll", ".so", ".dylib", ".a", ".o", ".class", ".pyc", ".pdb", ".bin",
    ".lock", ".map", ".min.js", ".min.css", ".snap", ".log", ".csv", ".tsv",
    ".db", ".sqlite", ".sqlite3", ".pack", ".idx", ".meta", ".asset", ".unity",
)
SKIP_DIRS = {
    "node_modules", ".git", ".svn", "venv", ".venv", "dist", "build", "out",
    "target", "bin", "obj", "Library", "coverage", "__pycache__", ".next",
    ".nuxt", ".astro", "vendor", "Pods", "DerivedData",
}
# Never counted, never handed to a scanning agent, never quoted on a page. An
# example file carries the same variable names with none of the values, so it is
# the one that gets read.
SECRET_FILES = {".netrc", ".npmrc", ".pypirc", "credentials", "id_rsa", "id_ed25519", "secring.gpg"}
SECRET_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".keystore", ".jks", ".kdbx", ".ppk")
SECRET_NAME = re.compile(r"(^|[._-])(secret|secrets|credentials|password|token)s?([._-]|$)", re.IGNORECASE)
ENV_FILE = re.compile(r"^\.?env(\.|$)", re.IGNORECASE)
ENV_SAFE = re.compile(r"^\.?env\.(example|sample|template|dist|defaults)$", re.IGNORECASE)


def is_secret(name: str) -> bool:
    """A file whose values must never be read, counted, or quoted."""
    lowered = name.lower()
    if ENV_FILE.match(lowered):
        return not ENV_SAFE.match(lowered)
    return lowered in SECRET_FILES or lowered.endswith(SECRET_SUFFIXES) or bool(SECRET_NAME.search(name))


TEST_DIRS = {"test", "tests", "__tests__", "spec", "specs", "e2e", "fixtures", "__mocks__", "testdata"}
TEST_FILE = re.compile(r"(^|[._-])(test|tests|spec)[._-]|[._-](test|tests|spec)\.[^.]+$|^test_", re.IGNORECASE)


class Row(dict):
    """One planned page."""

    @property
    def page(self) -> str:
        return self["page"]


def fail(problems: list[str], gate: str) -> int:
    if not problems:
        print(f"{gate}: PASS")
        return 0
    print(f"{gate}: FAIL ({len(problems)})")
    for problem in problems:
        print(f"  - {problem}")
    return 1


def split_cell(value: str) -> list[str]:
    value = value.strip()
    if value in {"", "-", "—", "none"}:
        return []
    return [part.strip() for part in value.split(";") if part.strip()]


def parse_map(path: str) -> tuple[list[Row], list[str]]:
    """Return the page rows and the deliberately excluded source paths."""
    with open(path, encoding="utf-8") as handle:
        lines = handle.read().splitlines()

    excluded: list[str] = []
    in_excluded = False
    header: list[str] | None = None
    rows: list[Row] = []

    for line in lines:
        stripped = line.strip()

        if stripped.startswith("#"):
            in_excluded = stripped.lower().lstrip("# ").startswith("excluded")
            continue

        if in_excluded and stripped.startswith("-"):
            entry = stripped.lstrip("- ").split("—")[0].split(" - ")[0].split(": ")[0]
            excluded.append(entry.strip().strip("`"))
            continue

        if not stripped.startswith("|"):
            continue

        cells = [cell.strip() for cell in stripped.strip("|").split("|")]

        if header is None:
            header = [cell.lower().strip("* ") for cell in cells]
            continue

        if set("".join(cells)) <= set("-: "):
            continue

        row = Row()
        for index, name in enumerate(header):
            row[name] = cells[index] if index < len(cells) else ""
        rows.append(row)

    if header is None:
        raise SystemExit(f"{path}: no map table found (expected a Markdown table)")

    missing = [name for name in COLUMNS if name not in header]
    if missing:
        raise SystemExit(f"{path}: map table is missing columns: {', '.join(missing)}")

    return rows, excluded


def is_binary(path: str) -> bool:
    try:
        with open(path, "rb") as handle:
            return b"\0" in handle.read(2048)
    except OSError:
        return True


def source_files(roots: list[str], secrets: list[str] | None = None, dotfiles: list[str] | None = None) -> list[str]:
    found: list[str] = []
    for root in roots:
        for base, dirs, names in os.walk(root):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
            for name in names:
                if is_secret(name):
                    if secrets is not None:
                        secrets.append(os.path.join(base, name).replace("\\", "/"))
                    continue
                if name.lower().endswith(NON_SOURCE_SUFFIXES):
                    continue
                if name.startswith("."):
                    if dotfiles is not None:
                        dotfiles.append(os.path.join(base, name).replace("\\", "/"))
                    continue
                path = os.path.join(base, name).replace("\\", "/")
                parts = {part.lower() for part in path.split("/")[:-1]}
                if parts & TEST_DIRS or TEST_FILE.search(name):
                    continue
                if is_binary(path):
                    continue
                found.append(path)
    return sorted(found)


def covers(claim: str, path: str) -> bool:
    """A claim covers a path when it names the file or one of its directories.

    Matched anywhere in the path, so a map written relative to the repository root
    still matches a scan started from a subdirectory.
    """
    claim = claim.strip().strip("/").replace("\\", "/")
    if not claim:
        return False
    return path == claim or path.startswith(claim + "/") or f"/{claim}/" in f"/{path}" or path.endswith(f"/{claim}")


def check_map(rows: list[Row], excluded: list[str], srcs: list[str]) -> int:
    problems: list[str] = []
    pages = [row["page"] for row in rows]

    for page in sorted({p for p in pages if pages.count(p) > 1}):
        problems.append(f"page listed twice: {page}")

    for row in rows:
        page = row["page"] or "(unnamed row)"

        if row["tier"].lower() not in TIERS:
            problems.append(f"{page}: tier '{row['tier']}' is not one of {sorted(TIERS)}")

        if row["status"].lower() not in STATUSES:
            problems.append(f"{page}: status '{row['status']}' is not one of {sorted(STATUSES)}")

        # Invariant 2: every page covers something.
        if not split_cell(row["covers"]):
            problems.append(f"{page}: covers nothing, so it is a page invented to fill a shape")

        if len(re.findall(r"[.!?](\s|$)", row["job"].strip())) > 1:
            problems.append(f"{page}: job needs more than one sentence, so it is more than one page")

        # Invariant 4: every deferral names a planned page.
        for target in split_cell(row["links to"]):
            if target not in pages:
                problems.append(f"{page}: links to '{target}', which is not on the map")

        for assumed in split_cell(row["assumes"]):
            if assumed not in pages:
                problems.append(f"{page}: assumes '{assumed}', which is not on the map")

    # Invariant 3: every concept owned exactly once.
    owners: dict[str, list[str]] = {}
    for row in rows:
        for concept in split_cell(row["owns"]):
            owners.setdefault(concept.lower(), []).append(row["page"])
    for concept, holders in sorted(owners.items()):
        if len(holders) > 1:
            problems.append(f"concept '{concept}' is owned by {len(holders)} pages: {', '.join(holders)}")

    # Invariant 1: every source area is covered by some page, or excluded on purpose.
    if srcs:
        claimed = [c for row in rows for c in split_cell(row["covers"])] + excluded
        files = source_files(srcs)
        uncovered = [p for p in files if not any(covers(c, p) for c in claimed)]
        print(f"  coverage: {len(files) - len(uncovered)} of {len(files)} source files claimed")
        if uncovered:
            problems.append(
                f"{len(uncovered)} source file(s) are covered by no page and not excluded, "
                f"first: {', '.join(uncovered[:5])}"
            )

    return fail(problems, "map")


def check_slices(slices_dir: str, srcs: list[str]) -> int:
    """The union of what the slices opened, against what is actually on disk.

    A slice list can only ever say what was read. The denominator comes from the
    filesystem, so a file no slice was pointed at is a failure rather than a file
    nobody thought about.
    """
    problems: list[str] = []
    opened: dict[str, list[str]] = {}

    if not os.path.isdir(slices_dir):
        return fail([f"no slice reports at {slices_dir}"], "coverage")

    # Without it, every scanner ran on what it already believed about the language.
    toolchain = os.path.join(os.path.dirname(slices_dir.rstrip("/\\")) or ".", "toolchain.md")
    if not os.path.exists(toolchain):
        problems.append(f"no toolchain answers at {toolchain}, so the slices were scanned on recall")

    for name in sorted(os.listdir(slices_dir)):
        if not name.endswith(".md"):
            continue
        path = os.path.join(slices_dir, name)
        with open(path, encoding="utf-8", errors="replace") as handle:
            body = handle.read()

        listed = re.findall(r"^\s*[-*]\s+`?([^\s`]+\.[A-Za-z0-9]+)`?\s*$", body, re.MULTILINE)
        for entry in listed:
            opened.setdefault(entry.replace("\\", "/").lstrip("./"), []).append(name)

        given = re.search(r"^files given:\s*(\d+)", body, re.IGNORECASE | re.MULTILINE)
        claim = re.search(r"^files opened:\s*(\d+)", body, re.IGNORECASE | re.MULTILINE)
        if not given or not claim:
            problems.append(f"{name}: no 'Files given' / 'Files opened' count")
            continue
        if given.group(1) != claim.group(1):
            problems.append(f"{name}: opened {claim.group(1)} of {given.group(1)} files given")
        if len(listed) != int(claim.group(1)):
            problems.append(f"{name}: claims {claim.group(1)} files opened but lists {len(listed)}")

    for path in sorted(opened):
        if is_secret(os.path.basename(path)):
            problems.append(f"{path} carries secrets and was opened by {', '.join(opened[path])}")

    secrets: list[str] = []
    dotfiles: list[str] = []
    files = source_files(srcs, secrets, dotfiles)
    unread = [p for p in files if not any(p == o or p.endswith("/" + o) or o.endswith("/" + p) for o in opened)]
    print(f"  read: {len(files) - len(unread)} of {len(files)} source files, across {len(opened)} listed path(s)")
    if secrets:
        print(f"  skipped as secret-bearing: {len(secrets)} file(s): {', '.join(sorted(secrets)[:5])}")
    if dotfiles:
        print(f"  skipped as dotfiles, read any that configure the project: {len(dotfiles)} file(s): {', '.join(sorted(dotfiles)[:5])}")
    if unread:
        problems.append(
            f"{len(unread)} source file(s) appear in no slice report, "
            f"first: {', '.join(unread[:5])}"
        )

    for path, owners in sorted(opened.items()):
        if len(owners) > 1:
            problems.append(f"{path} was read by {len(owners)} slices: {', '.join(owners)}")

    return fail(problems, "coverage")


def emit_status(rows: list[Row], reviews_dir: str) -> int:
    """The block that opens the report. Generated, so it cannot be phrased away."""
    counts = {"planned": 0, "drafted": 0, "reviewed": 0, "other": 0}
    for row in rows:
        counts[row["status"].lower() if row["status"].lower() in counts else "other"] += 1

    passed = failed = missing = 0
    for row in rows:
        for kind in ("factcheck", "reader"):
            path = os.path.join(reviews_dir, f"{slug(row['page'])}.{kind}.md")
            if not os.path.exists(path):
                missing += 1
                continue
            with open(path, encoding="utf-8", errors="replace") as handle:
                body = handle.read()
            if re.search(r"^verdict:\s*pass\s*$", body, re.IGNORECASE | re.MULTILINE):
                passed += 1
            else:
                failed += 1

    total = len(rows)
    done = counts["reviewed"] == total and failed == 0 and missing == 0

    print("")
    print("    STATUS: " + ("DELIVERED" if done else "INCOMPLETE"))
    print(f"    Pages reviewed: {counts['reviewed']} of {total}")
    print(f"    Drafted, not reviewed: {counts['drafted']}    Planned, not written: {counts['planned']}")
    print(f"    Review verdicts: {passed} PASS, {failed} FAIL, {missing} missing")
    print("")

    if not done:
        print("    This set is not delivered. Report it as INCOMPLETE, lead with these")
        print("    numbers, and do not describe the work as a finished pass.")
        print("")

    return 0 if done else 1


def slug(page: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", page.lower()).strip("-")


def page_digest(path: str) -> str | None:
    try:
        with open(path, "rb") as handle:
            return hashlib.sha256(handle.read()).hexdigest()[:16]
    except OSError:
        return None


def check_reviews(rows: list[Row], reviews_dir: str) -> int:
    """Delivery gate. A page still planned is unwritten work, not a note to keep.

    Run it whenever you want to know whether the set is finished; it fails while
    anything is outstanding, which is the point. A page that will not be written
    is removed from the map and its source moved to the excluded list with a
    reason, so the decision is recorded where the coverage check reads it.
    """
    problems: list[str] = []
    for row in rows:
        if row["status"].lower() == "planned":
            problems.append(f"{row['page']}: still planned, so the set is not delivered")
            continue
        if row["status"].lower() != "reviewed":
            problems.append(f"{row['page']}: status is '{row['status']}', not reviewed")
        for kind in ("factcheck", "reader"):
            path = os.path.join(reviews_dir, f"{slug(row['page'])}.{kind}.md")
            if not os.path.exists(path):
                problems.append(f"{row['page']}: no {kind} review at {path}")
                continue
            with open(path, encoding="utf-8") as handle:
                body = handle.read()
            if not re.search(r"^verdict:\s*pass\s*$", body, re.IGNORECASE | re.MULTILINE):
                problems.append(f"{row['page']}: {kind} review does not carry a line 'Verdict: PASS'")
                continue

            # A verdict judged one version of a page. Editing the page afterwards
            # leaves an approval standing over content nobody reviewed, which is
            # how a corrected page and a stale FAIL end up in the same report.
            named = re.search(r"^reviewed:\s*(\S+)\s*$", body, re.IGNORECASE | re.MULTILINE)
            digest = re.search(r"^reviewed-sha:\s*([0-9a-f]{16})\s*$", body, re.IGNORECASE | re.MULTILINE)
            stamp = (named, digest) if named and digest else None
            if not stamp:
                problems.append(
                    f"{row['page']}: {kind} review carries no 'Reviewed:' plus 'Reviewed-SHA:' stamp, "
                    f"so nothing says which version it judged"
                )
                continue

            current = page_digest(named.group(1))
            if current is None:
                problems.append(f"{row['page']}: {kind} review names {named.group(1)}, which does not exist")
            elif current != digest.group(1).lower():
                problems.append(
                    f"{row['page']}: {kind} review is stale: the page changed after it was written. Review it again."
                )
    return fail(problems, "reviews")


LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)")


def check_links(rows: list[Row], docs_root: str) -> int:
    problems: list[str] = []
    pages = {row["page"] for row in rows}
    checked = 0

    for base, dirs, names in os.walk(docs_root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for name in names:
            if not name.endswith((".md", ".mdx")):
                continue
            path = os.path.join(base, name)
            with open(path, encoding="utf-8", errors="replace") as handle:
                body = handle.read()
            for target in LINK.findall(body):
                if target.startswith(("http://", "https://", "mailto:", "#", "data:")):
                    continue
                checked += 1
                bare = target.split("#")[0].split("?")[0]
                if not bare:
                    continue
                if bare.startswith("/"):
                    if bare.rstrip("/") not in {p.rstrip("/") for p in pages}:
                        problems.append(f"{path}: '{target}' resolves to no page on the map")
                    continue
                resolved = os.path.normpath(os.path.join(base, bare))
                if os.path.exists(resolved):
                    continue
                if any(os.path.exists(resolved + ext) for ext in (".md", ".mdx")):
                    continue
                problems.append(f"{path}: '{target}' does not exist")

    print(f"  links: {checked} internal link(s) checked")
    return fail(problems, "links")


def emit_mermaid(rows: list[Row]) -> int:
    print("```mermaid")
    print("graph TD")
    ids = {row["page"]: f"n{index}" for index, row in enumerate(rows)}
    for row in rows:
        label = row["page"].replace('"', "'")
        print(f'    {ids[row["page"]]}["{label}<br/>({row["tier"]})"]')
    for row in rows:
        for assumed in split_cell(row["assumes"]):
            if assumed in ids:
                print(f"    {ids[assumed]} --> {ids[row['page']]}")
        for target in split_cell(row["links to"]):
            if target in ids:
                print(f"    {ids[row['page']]} -.-> {ids[target]}")
    print("```")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("gate", choices=["status", "coverage", "map", "reviews", "links", "mermaid", "all"])
    parser.add_argument("--map", default="docs-work/map.md")
    parser.add_argument("--src", nargs="*", default=[])
    parser.add_argument("--docs", default=None)
    parser.add_argument("--reviews", default="docs-work/reviews")
    parser.add_argument("--slices", default="docs-work/slices")
    args = parser.parse_args()

    if args.gate == "coverage":
        return check_slices(args.slices, args.src)

    rows, excluded = parse_map(args.map)
    print(f"{args.map}: {len(rows)} page(s), {len(excluded)} excluded path(s)")

    if args.gate == "mermaid":
        return emit_mermaid(rows)

    if args.gate == "status":
        return emit_status(rows, args.reviews)

    status = 0
    if args.gate == "all" and args.src:
        status |= check_slices(args.slices, args.src)
    if args.gate in {"map", "all"}:
        status |= check_map(rows, excluded, args.src)
    if args.gate in {"reviews", "all"}:
        status |= check_reviews(rows, args.reviews)
    if args.gate in {"links", "all"} and args.docs:
        status |= check_links(rows, args.docs)
    return status


if __name__ == "__main__":
    sys.exit(main())
