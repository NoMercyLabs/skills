import json
import re

from .common import CrucibleError, Root, stamp

HEADER = re.compile(r"^=== (.+?) ([0-9a-f]{10}) (\d+)-(\d+)/(\d+) ===$", re.M)


def transcript_text(path):
    """Every tool_result text of a JSONL agent transcript; a line that is not JSON counts as plain text."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            rows = fh.read().split("\n")
    except OSError as exc:
        raise CrucibleError(f"cannot read transcript {path}: {exc}")
    out = []
    for raw in rows:
        try:
            row = json.loads(raw)
        except ValueError:
            out.append(raw)
            continue
        message = row.get("message") if isinstance(row, dict) else None
        content = (message or {}).get("content")
        if not isinstance(message, dict) or message.get("role") != "user" or not isinstance(content, list):
            continue
        for part in content:
            if isinstance(part, dict) and part.get("type") == "tool_result":
                body = part.get("content")
                if isinstance(body, list):
                    body = "\n".join(x.get("text", "") for x in body if isinstance(x, dict))
                out.append(str(body or ""))
    return "\n".join(out).replace("\r\n", "\n")


def shown_blocks(text):
    """(path, a, b, n, stamp, body) for each stamped block that has its END line."""
    for m in HEADER.finditer(text):
        path = m.group(1)
        end = text.find(f"\n=== END {path} ===", m.end())
        if end < 0:
            continue
        yield (path, int(m.group(3)), int(m.group(4)), int(m.group(5)), m.group(2), text[m.end() + 1:end])


def check_proof(root, unit, transcript):
    """-> (ok, message). ok False with a message that starts TAMPER REFUSED or PROOF FAIL."""
    ledger = root.ledger(unit)
    if ledger is None:
        return False, f"PROOF FAIL {unit}: no ledger"
    files = root.unit(unit)["files"]
    key = root.key()
    covered = {}
    for path, a, b, n, given, body in shown_blocks(transcript_text(transcript)):
        if stamp(key, path, a, b, n, body) != given:
            return False, f"TAMPER REFUSED {unit}: {path} lines {a}-{b} do not match their stamp"
        covered.setdefault(path, set()).update(range(a, b + 1) if n else {0})
    problems = []
    if not isinstance(ledger.get("leads"), list):
        problems.append("ledger has no 'leads' list (dropped suspects are kept, [] when none)")
    read, skipped = ledger.get("read", []), ledger.get("skipped", {})
    no_reason = sorted(p for p, why in skipped.items() if not str(why).strip())
    if no_reason:
        problems.append(f"{len(no_reason)} skipped files have no reason (first: {no_reason[0]})")
    uncovered = sorted(set(files) - set(read) - set(skipped))
    extra = sorted((set(read) | set(skipped)) - set(files))
    if uncovered:
        problems.append(f"{len(uncovered)} of {len(files)} unit files neither read nor skipped (first: {uncovered[0]})")
    if extra:
        problems.append(f"ledger lists files outside the unit (first: {extra[0]})")
    unread = []
    for path in read:
        if path not in files:
            continue
        n = len(root.snapshot_lines(root.unit(unit)["repo"], path))
        if not (set(range(1, n + 1)) if n else {0}) <= covered.get(path, set()):
            unread.append(path)
    if unread:
        problems.append(f"{len(unread)} of {len(read)} 'read' files not shown whole in the transcript "
                        f"(first: {unread[0]})")
    if problems:
        return False, f"PROOF FAIL {unit}: " + "; ".join(problems)
    return True, f"PROOF PASS {unit}: {len(read)} files shown whole, {len(ledger['leads'])} leads kept"


def cmd_proof(args):
    root = Root(args.root)
    root.require_confirmed()
    ok, message = check_proof(root, args.unit, args.transcript)
    state = root.state()
    state["units"].setdefault(args.unit, {"status": "pending"})["proof"] = "pass" if ok else "fail"
    root.save_state(state)
    print(message)
    return 0 if ok else 1


def register(sub):
    p = sub.add_parser("proof", help="prove a reader was shown every file whole")
    p.add_argument("unit")
    p.add_argument("transcript")
    p.set_defaults(func=cmd_proof)
