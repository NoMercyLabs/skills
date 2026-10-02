"""Self-healing inside a run: a stage failure is classified from measured facts, a known class gets one scripted
recovery, and a unit that fails twice in one class is blocked. A refusal is never healed and an unknown failure is
never retried; both are reported with their facts."""
import contextlib
import io
import re
from types import SimpleNamespace

from . import blockers, split
from .common import CrucibleError, read_json, write_json
from .permissions import log_action, now

GROUP = "heal"
MAX_TRIES = 2
REFUSALS = ("gate", "test", "permission", "visibility")
RATE_LIMIT = re.compile(r"rate.?limit|too many requests|\b429\b", re.I)
TRACKER_SCOPE = re.compile(r"(token|tracker).{0,60}scope|scope.{0,60}(token|tracker)|insufficient.scope", re.I)
TOOL_REFUSED = re.compile(r"(tool|permission).{0,40}(refused|denied)|refused by the harness", re.I)
CONTEXT_TEXT = re.compile(r"context (length|window)|prompt is too long", re.I)
STUB_PROMPT = "call your first real tool now"
SCOPE_HINT = "refresh the tracker token with the missing scope, then run the stage again"
LOG_STATUS = {"healed": "ok", "failed": "failed", "blocked": "failed", "refused": "refused", "reported": "skipped",
              "stopped": "skipped"}


def classify(facts):
    """The failure class from exit code, schema result, truncation, tool calls and the harness text only."""
    if facts.get("refusal") in REFUSALS:
        return "refused"
    code, text = facts.get("exit_code", 0), facts.get("output") or ""
    if code == 0 and facts.get("schema_ok"):
        return "none"
    if facts.get("truncated") or CONTEXT_TEXT.search(text):
        return "context_exhausted"
    if code != 0:
        for name, pattern in (("rate_limited", RATE_LIMIT), ("tracker_scope", TRACKER_SCOPE),
                              ("tool_refused", TOOL_REFUSED)):
            if pattern.search(text):
                return name
        return "unknown"
    return "stub_reply" if not facts.get("tool_calls") else "schema_missing"


def load(root):
    return read_json(root.p("heals.json"), [])


def record(root, cls, unit, tries, result, detail=""):
    write_json(root.p("heals.json"), load(root) + [{"class": cls, "unit": unit, "try": tries, "result": result,
                                                    "at": now()}])
    log_action(root, GROUP, f"{cls} {unit} try {tries}", f"{result} {detail}".strip(), LOG_STATUS[result])
    return {"class": cls, "unit": unit, "try": tries, "result": result}


def tries_used(root, cls, unit):
    return sum(1 for r in load(root) if r["class"] == cls and r["unit"] == unit and r["result"] in
               ("healed", "failed", "blocked") and r["try"])


def run_halves(root, unit, runner):
    with contextlib.redirect_stdout(io.StringIO()):
        split.cmd_split(SimpleNamespace(root=root.path, unit=unit))
    return all(runner(part, **{}).get("ok") for part in root.state()["units"][unit]["parts"])


def recovery(cls, root, unit, facts, runner):
    """True when the scripted recovery made the unit run."""
    if cls == "context_exhausted":
        return run_halves(root, unit, runner)
    if cls == "stub_reply":
        return bool(runner(unit, prompt_addendum=STUB_PROMPT).get("ok"))
    if cls == "rate_limited":
        return bool(runner(unit, wait=facts.get("retry_after", 0), resume=True).get("ok"))
    return bool(runner(unit).get("ok"))


def block(root, cls, unit, facts):
    state = root.state()
    state["units"].setdefault(unit, {})["heal"] = "blocked"
    root.save_state(state)
    if not any(b["stage"] == unit and b["status"] == "open" for b in blockers.load(root)):
        blockers.add(root, f"{cls}: the unit failed after {MAX_TRIES} scripted recoveries", unit)


def recover(root, unit, facts, runner):
    """Classify the failure and run its one scripted recovery; returns the heal record. runner(unit, **options)
    reruns a stage and returns {"ok": bool}."""
    cls = classify(facts)
    detail = f"exit_code={facts.get('exit_code')} output={(facts.get('output') or '')[-200:]!r}"
    if cls == "refused":
        return record(root, cls, unit, 0, "refused", f"{facts.get('refusal')} refusal is never healed")
    if cls == "none":
        return {"class": cls, "unit": unit, "try": 0, "result": "none"}
    if cls == "tracker_scope":
        return {**record(root, cls, unit, 0, "stopped", SCOPE_HINT), "hint": SCOPE_HINT}
    if cls in ("unknown", "tool_refused"):
        return record(root, cls, unit, 0, "reported", detail)
    used = tries_used(root, cls, unit)
    if used >= MAX_TRIES:
        block(root, cls, unit, facts)
        return {"class": cls, "unit": unit, "try": used, "result": "blocked"}
    try:
        ok = recovery(cls, root, unit, facts, runner)
    except CrucibleError as exc:
        ok, detail = False, str(exc)
    if ok:
        return record(root, cls, unit, used + 1, "healed")
    if used + 1 >= MAX_TRIES:
        block(root, cls, unit, facts)
        return record(root, cls, unit, used + 1, "blocked", detail)
    return record(root, cls, unit, used + 1, "failed", detail)


def no_rerun(unit, **options):
    return {"ok": False}


def record_failure(root, unit, output, refusal=None):
    """Heal record for a stage the command line itself found failed. The command line cannot rerun a reader, so no
    recovery that needs a rerun is attempted here; the facts are classified and recorded."""
    facts = {"exit_code": 1, "output": output, "schema_ok": False, "truncated": False, "tool_calls": 1}
    if refusal:
        facts["refusal"] = refusal
    return recover(root, unit, facts, no_rerun)


def report_lines(root):
    rows = load(root)
    if not rows:
        return []
    lines = [f"healed: {sum(1 for r in rows if r['result'] == 'healed')}"]
    return lines + [f"  {r['class']} {r['unit']} try {r['try']}: {r['result']}" for r in rows]
