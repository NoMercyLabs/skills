"""`crucible cited UNIT`: everything a verifier needs to start, in one bounded output.

For every candidate of the unit: its source id, its title, and for each evidence ref and each chain link ref the cited
line or range with a few lines of context each side, numbered, from the snapshot. Then the ledger leads of the unit.
No line outside those ranges is printed. A ref the snapshot cannot give is named, never skipped silently.
"""

import re

from .common import CrucibleError, Root, source_id

CONTEXT = 3
REF_RE = re.compile(r"^(.*?):(\d+)(?:-(\d+))?$")


def link_refs(cand):
    """(label, repo override, ref) for every evidence ref and chain link of one candidate."""
    out = []
    for i, ev in enumerate(cand.get("evidence") or []):
        out.append((f"evidence {i}", ev.get("repo"), ev.get("ref")))
    chain = cand.get("chain") or {}
    if isinstance(chain.get("symptom"), dict):
        out.append(("symptom", None, chain["symptom"].get("ref")))
    for i, step in enumerate(chain.get("mechanism") or []):
        ev = step.get("evidence") or {}
        out.append((f"mechanism {i}", ev.get("repo"), step.get("ref")))
    if isinstance(chain.get("root_cause"), dict):
        ev = chain["root_cause"].get("evidence") or {}
        out.append(("root cause", ev.get("repo"), chain["root_cause"].get("ref")))
    return out


def block(root, repo, ref):
    match = REF_RE.match(ref or "")
    if not match:
        return [f"  (ref {ref!r} has no path:line)"]
    path, first = match.group(1), int(match.group(2))
    last = int(match.group(3) or first)
    try:
        lines = root.snapshot_lines(repo, path)
    except CrucibleError as exc:
        return [f"  ({exc})"]
    a, b = max(1, first - CONTEXT), min(len(lines), last + CONTEXT)
    if first > len(lines):
        return [f"  ({path} has {len(lines)} lines: line {first} is past the end)"]
    width = len(str(b))
    rows = [f"  --- {path} {first}" + (f"-{last}" if last != first else "") + f" (lines {a}-{b} of {len(lines)}) ---"]
    for n in range(a, b + 1):
        mark = ">" if first <= n <= last else " "
        rows.append(f"  {mark}{n:>{width}}|{lines[n - 1]}")
    return rows


def cmd_cited(args):
    root = Root(args.root)
    root.unit(args.unit)
    cands = root.candidates(args.unit)
    print(f"=== cited {args.unit}: {len(cands)} candidates ===")
    for cand in cands:
        print(f"\n## {source_id(args.unit, cand)}  {cand.get('title', '')}")
        seen = set()
        for label, repo, ref in link_refs(cand):
            key = (repo, ref)
            if key in seen:
                continue
            seen.add(key)
            print(f" [{label}] {ref}")
            for row in block(root, repo or cand.get("repo"), ref):
                print(row)
    ledger = root.ledger(args.unit) or {}
    leads = ledger.get("leads") or []
    print(f"\n=== leads of {args.unit}: {len(leads)} ===")
    for lead in leads:
        print(f"- {lead.get('ref')}: {lead.get('suspect')} | dropped because: {lead.get('dropped_because')}")
    print("=== END cited ===")


def register(sub):
    p = sub.add_parser("cited", help="a unit's candidates with their cited lines and context, and its leads, in one call")
    p.add_argument("unit")
    p.set_defaults(func=cmd_cited)
