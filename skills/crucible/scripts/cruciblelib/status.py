from .common import Root, read_json


def unit_status(root, unit):
    """pending, partial, done, split or rejected-all. Done needs accept plus a full ledger."""
    recorded = root.state()["units"].get(unit, {})
    status = recorded.get("status", "pending")
    if status in ("split", "rejected-all", "carried"):
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
    done, carried = counts.get("done", 0), counts.get("carried", 0)
    detail = ", ".join(f"{n} {s}" for s, n in sorted(counts.items()) if s not in ("done", "carried"))
    line = f"coverage: {done} of {total} units done"
    if carried:
        line += f", {carried} carried"
    print(line + (f" ({detail})" if detail else ""))
    if parents:
        print(f"{parents} split parent{'s' if parents > 1 else ''} not counted")
    coverage = read_json(root.p("coverage.json"))
    if coverage:
        files = coverage["files"]
        kept = sum(1 for e in files.values() if e["status"] == "carried")
        print(f"files: {len(files) - kept} read this audit, {kept} carried from an earlier audit")
    if total and done + carried == total:
        print("coverage 100%")
    findings = root.findings()
    by_goal = {}
    for f in findings.values():
        by_goal[f.get("goal")] = by_goal.get(f.get("goal"), 0) + 1
    print(f"findings: {len(findings)}")
    for g in cfg["goals"]:
        print(f"goal {g['id']} {g['name']}: {by_goal.pop(g['id'], 0)}")
    for goal, n in sorted(by_goal.items(), key=str):
        print(f"goal {goal} (not in config): {n}")
    cap = cfg["budget"]["max_tokens"]
    spent = state["tokens_spent"]
    print(f"tokens: {spent} of {cap if cap else 'no cap'}" + (" (over the cap)" if cap and spent > cap else ""))


def register(sub):
    p = sub.add_parser("status", help="coverage, findings and tokens")
    p.set_defaults(func=cmd_status)
