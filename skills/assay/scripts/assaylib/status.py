from .common import Root


def unit_status(root, unit):
    """pending, partial, done, split or rejected-all. Done needs accept plus a full ledger."""
    recorded = root.state()["units"].get(unit, {})
    status = recorded.get("status", "pending")
    if status in ("split", "rejected-all"):
        return status
    ledger = root.ledger(unit)
    if ledger is None:
        return "pending"
    covered = set(ledger.get("read", [])) | set(ledger.get("skipped", {}))
    if not set(root.unit(unit)["files"]) <= covered or recorded.get("proof") == "fail":
        return "partial"
    return "done" if status == "done" else "partial"


def cmd_status(args):
    root = Root(args.root)
    root.require_confirmed()
    cfg = root.config()
    state = root.state()
    counts, parents = {}, 0
    for unit in root.units():
        status = unit_status(root, unit)
        if status == "split":
            parents += 1
            continue
        counts[status] = counts.get(status, 0) + 1
    total = sum(counts.values())
    detail = ", ".join(f"{n} {s}" for s, n in sorted(counts.items()) if s != "done")
    print(f"coverage: {counts.get('done', 0)} of {total} units done" + (f" ({detail})" if detail else ""))
    if parents:
        print(f"{parents} split parent{'s' if parents > 1 else ''} not counted")
    findings = root.findings()
    by_goal = {}
    for f in findings.values():
        by_goal[f.get("goal")] = by_goal.get(f.get("goal"), 0) + 1
    names = {g["id"]: g["name"] for g in cfg["goals"]}
    line = f"findings: {len(findings)}"
    if by_goal:
        line += " (" + ", ".join(f"goal {names.get(g, g)}: {n}" for g, n in sorted(by_goal.items(), key=str)) + ")"
    print(line)
    cap = cfg["budget"]["max_tokens"]
    print(f"tokens: {state['tokens_spent']} of {cap if cap else 'no cap'}")


def register(sub):
    p = sub.add_parser("status", help="coverage, findings and tokens")
    p.set_defaults(func=cmd_status)
