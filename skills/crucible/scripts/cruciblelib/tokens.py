import math
import os

from .common import CrucibleError, Root, read_json, write_json
from .models import JUDGE_CALL_TOKENS, TIERS, plan_for
from .transcripts import read_usage

PILOT_UNITS = 3
REFIT_EVERY = 10
STOP_CODE = 3
MIN_SPREAD = 0.05
ROLES = ("reader", "verifier", "judge", "main")

# Planning numbers until a calibration run measures them on the user's own code; calibrate replaces them per tier.
DEFAULT_TERMS = {
    "start_tokens": 15000,
    "tokens_per_line": 20,
    "turn_tokens": 4000,
    "lines_per_turn": 400,
    "output_tokens": 3000,
    "verifier_start_tokens": 12000,
    "verifier_tokens_per_candidate": 2500,
    "candidates_per_unit": 3,
    "judge_call_tokens": JUDGE_CALL_TOKENS,
    "main_session_tokens": 50000,
    "spread": 0.25,
}


def load_calibration(path):
    return read_json(path, {}) or {}


def terms_by_tier(calibration):
    saved = calibration.get("tiers", {})
    return {tier: dict(DEFAULT_TERMS, **saved.get(tier, {})) for tier in TIERS}


def turns_for(terms, lines):
    return 1 + math.ceil(lines / terms["lines_per_turn"])


def reader_parts(terms, lines):
    """Every cost of one reader: the start cost, the lines read, each turn re-sending the context, the output."""
    turns = turns_for(terms, lines)
    return {"start": terms["start_tokens"], "lines": terms["tokens_per_line"] * lines,
            "turns": turns, "turn_tokens": terms["turn_tokens"] * turns, "output": terms["output_tokens"]}


def reader_tokens(terms, lines):
    parts = reader_parts(terms, lines)
    return round(parts["start"] + parts["lines"] + parts["turn_tokens"] + parts["output"])


def verifier_tokens(terms):
    return round(terms["verifier_start_tokens"] + terms["candidates_per_unit"] * terms["verifier_tokens_per_candidate"])


def pick_pilot(units):
    """The smallest unit, the largest, and a high-risk one (the middle one when none is high risk)."""
    ordered = sorted(units, key=lambda u: (u["lines"], u["unit"]))
    if len(ordered) <= PILOT_UNITS:
        return ordered
    picked = [ordered[0], ordered[-1]]
    rest = ordered[1:-1]
    high = [u for u in rest if u["risk"] == "high"]
    picked.append(high[-1] if high else rest[len(rest) // 2])
    return sorted(picked, key=lambda u: (u["lines"], u["unit"]))


def refit_due(count, pilot=PILOT_UNITS):
    return count > 0 and (count == pilot or count % REFIT_EVERY == 0)


def fit_line(points):
    """Least squares y = start + slope * x, both clamped at zero; None when the x values do not differ."""
    n = len(points)
    mx, my = sum(x for x, y in points) / n, sum(y for x, y in points) / n
    sxx = sum((x - mx) ** 2 for x, y in points)
    if n < 2 or sxx == 0:
        return None
    slope = max(0.0, sum((x - mx) * (y - my) for x, y in points) / sxx)
    start = max(0.0, my - slope * mx)
    worst = max(abs(start + slope * x - y) / y for x, y in points if y > 0)
    return start, slope, worst


def fit_terms(tiers, records):
    """Refit each tier's terms from the recorded usage. Readers: start cost and tokens per line, after the turns and
    the output are taken off; verifiers: start cost and tokens per candidate; judge and main: their own means."""
    out = {}
    for tier in TIERS:
        terms = dict(tiers[tier])
        mine = [r for r in records if r["tier"] == tier]
        readers = [r for r in mine if r["role"] == "reader"]
        found = fit_line([(r["lines"], r["tokens"] - terms["turn_tokens"] * r["turns"] - r["output"])
                          for r in readers]) if readers else None
        if found:
            terms.update(start_tokens=round(found[0]), tokens_per_line=round(found[1], 4),
                         output_tokens=round(sum(r["output"] for r in readers) / len(readers)),
                         spread=round(max(MIN_SPREAD, found[2]), 4), samples=len(readers))
        verifiers = [r for r in mine if r["role"] == "verifier"]
        found = fit_line([(r["candidates"], r["tokens"]) for r in verifiers]) if verifiers else None
        if found:
            terms.update(verifier_start_tokens=round(found[0]), verifier_tokens_per_candidate=round(found[1]))
        judges = [r for r in mine if r["role"] == "judge"]
        if judges:
            terms["judge_call_tokens"] = round(sum(r["tokens"] for r in judges) / sum(r["calls"] for r in judges))
        mains = [r for r in mine if r["role"] == "main"]
        if mains:
            terms["main_session_tokens"] = round(sum(r["tokens"] for r in mains) / len(mains))
        if terms != tiers[tier]:
            out[tier] = terms
    return out


def project(plan, tiers, records):
    """Per role: tokens already spent (from records), tokens still to come (formula), and the margin on those."""
    done = {(r["role"], r.get("unit")): r for r in records}
    parts = {role: {"spent": 0, "left": 0, "margin": 0.0} for role in ROLES}

    factor = plan.get("forecast_factor", 1)

    def add(role, tier, spent, estimate):
        part = parts[role]
        if spent is None:
            estimate = round(estimate * factor)
            part["left"] += estimate
            part["margin"] += estimate * tiers[tier]["spread"]
        else:
            part["spent"] += spent

    verifier_tier = plan["roles"]["verifier"]["tier"]
    for unit in plan["units"]:
        tier = unit["reader_tier"]
        record = done.get(("reader", unit["unit"]))
        add("reader", tier, record and record["tokens"], reader_tokens(tiers[tier], unit["lines"]))
        record = done.get(("verifier", unit["unit"]))
        add("verifier", verifier_tier, record and record["tokens"], verifier_tokens(tiers[verifier_tier]))
    judge_tier = next(iter(plan["complex_jobs"].values()))["tier"]
    for role, tier, estimate in (
            ("judge", judge_tier, sum(j["calls"] for j in plan["complex_jobs"].values())
             * tiers[judge_tier]["judge_call_tokens"]),
            ("main", judge_tier, tiers[judge_tier]["main_session_tokens"])):
        spent = sum(r["tokens"] for r in records if r["role"] == role)
        add(role, tier, spent or None, estimate)
    for part in parts.values():
        part["total"] = part["spent"] + part["left"]
    return parts


def summary(parts):
    spent = sum(p["spent"] for p in parts.values())
    total = sum(p["total"] for p in parts.values())
    margin = math.ceil(sum(p["margin"] for p in parts.values()))
    return {"spent": spent, "total": total, "low": max(spent, total - margin), "high": total + margin}


def like_for_like(forecast_parts, records):
    """The forecast and the actual over the roles that were measured, so a run without verifier records is not
    blamed for the verifier tokens it never spent."""
    actual = {}
    for r in records:
        actual[r["role"]] = actual.get(r["role"], 0) + r["tokens"]
    total = sum(actual.values())
    forecast = sum(forecast_parts[role] for role in actual)
    return forecast, total, sorted(actual), (forecast - total) / total if total else 0.0


def percent(error):
    return f"{error * 100:+.1f}%"


def ledger_path(root):
    return root.p("tokens.json")


def load_ledger(root):
    return read_json(ledger_path(root), {"records": [], "forecasts": []})


def calibration_path(root, ledger, given=None):
    return given or ledger.get("calibration") or root.p("calibration.json")


def ensure_first_estimate(root, plan, tiers, ledger):
    if "first_estimate" not in ledger:
        parts = project(plan, tiers, [])
        ledger["first_estimate"] = {"parts": {role: p["total"] for role, p in parts.items()},
                                    "units": {u["unit"]: round(reader_tokens(tiers[u["reader_tier"]], u["lines"]) * plan.get("forecast_factor", 1))
                                              for u in plan["units"]}}
        write_json(ledger_path(root), ledger)


def is_complete(plan, records):
    read = {r["unit"] for r in records if r["role"] == "reader"}
    return bool(plan["units"]) and all(u["unit"] in read for u in plan["units"])


def over_cap(root, high):
    cap = root.config()["budget"]["max_tokens"]
    return bool(cap) and high > cap


def stop_line(root, high):
    return (f"STOP: the forecast high of {high} tokens is over the cap of {root.config()['budget']['max_tokens']}; "
            "no new readers start. Ask the user to raise the cap or to go on anyway.")


def readers_may_start(root):
    ledger = load_ledger(root)
    plan = plan_for(root)
    tiers = terms_by_tier(load_calibration(calibration_path(root, ledger)))
    return not over_cap(root, summary(project(plan, tiers, ledger["records"]))["high"])


def forecast_text(found):
    return f"forecast: {found['total']} (low {found['low']}, high {found['high']})"


def closed_runs(root, ledger, records):
    runs = []
    for stage in ledger["forecasts"]:
        forecast, actual, roles, error = like_for_like(stage["parts"], records)
        runs.append({"source": os.path.basename(root.path), "stage": stage["stage"], "after_units": stage["after_units"],
                     "roles": roles, "forecast": forecast, "actual": actual, "forecast_error": round(error, 4)})
    return runs


def cmd_calibrate(args):
    root = Root(args.root)
    root.require_confirmed()
    plan = plan_for(root)
    ledger = load_ledger(root)
    path = calibration_path(root, ledger, args.out)
    calibration = load_calibration(path)
    tiers = terms_by_tier(calibration)
    ensure_first_estimate(root, plan, tiers, ledger)
    units = {u["unit"]: u for u in plan["units"]}
    if args.role in ("reader", "verifier") and args.unit not in units:
        raise CrucibleError(f"{args.role} needs --unit, one of the units in the plan")
    unit = units.get(args.unit)
    usage = read_usage(args.transcript)
    tier = unit["reader_tier"] if unit and args.role == "reader" else (
        plan["roles"]["verifier"]["tier"] if args.role == "verifier" else
        next(iter(plan["complex_jobs"].values()))["tier"])
    record = {"role": args.role, "unit": unit and unit["unit"], "tier": tier, "lines": unit["lines"] if unit else 0,
              "candidates": args.candidates, "calls": args.calls, "turns": usage["turns"],
              "tokens": usage["tokens"], "output": usage["output"], "transcript": os.path.basename(args.transcript)}
    old = [r for r in ledger["records"] if r["role"] == args.role and (r["unit"] == record["unit"] or unit is None)]
    ledger["records"] = [r for r in ledger["records"] if r not in old] + [record]
    state = root.state()
    state["tokens_spent"] += record["tokens"] - sum(r["tokens"] for r in old)
    root.save_state(state)
    readers = sum(1 for r in ledger["records"] if r["role"] == "reader")
    if args.refit or (args.role == "reader" and refit_due(readers, min(PILOT_UNITS, len(units)))):
        changed = fit_terms(tiers, ledger["records"])
        tiers.update(changed)
        calibration["tiers"] = dict(calibration.get("tiers", {}), **changed)
        calibration.setdefault("version", 1)
        stage = "pilot" if readers == min(PILOT_UNITS, len(units)) else f"after-{readers}"
        found = summary(project(plan, tiers, ledger["records"]))
        ledger["forecasts"] = [f for f in ledger["forecasts"] if f["stage"] != stage] + [
            {"stage": stage, "after_units": readers, "parts": {r: p["total"] for r, p in
                                                              project(plan, tiers, ledger["records"]).items()},
             **found}]
        print(f"refit after {readers} units: " + (", ".join(sorted(changed)) or "no tier") + " updated")
    ledger["calibration"] = path
    if is_complete(plan, ledger["records"]) and ledger["forecasts"]:
        calibration["runs"] = [r for r in calibration.get("runs", []) if r.get("source") != os.path.basename(root.path)] \
            + closed_runs(root, ledger, ledger["records"])
    if calibration:
        write_json(path, calibration)
    write_json(ledger_path(root), ledger)
    found = summary(project(plan, tiers, ledger["records"]))
    print(f"recorded {args.role} {record['unit'] or ''}: {record['tokens']} tokens from the harness transcript, "
          f"{record['turns']} turns".replace("  ", " "))
    print(forecast_text(found))
    if over_cap(root, found["high"]):
        print(stop_line(root, found["high"]))
        return STOP_CODE
    return 0


def print_estimate(plan, tiers):
    readers = [(tiers[u["reader_tier"]], u["lines"]) for u in plan["units"]]
    factor = plan.get("forecast_factor", 1)
    parts = [reader_parts(terms, lines) for terms, lines in readers]
    total = round(sum(reader_tokens(terms, lines) for terms, lines in readers) * factor)
    print(f"reader tokens: {total} (start cost {round(sum(p['start'] for p in parts) * factor)}, "
          f"lines {round(sum(p['lines'] for p in parts) * factor)}, "
          f"turns {round(sum(p['turn_tokens'] for p in parts) * factor)} over {sum(p['turns'] for p in parts)} turns, "
          f"output {round(sum(p['output'] for p in parts) * factor)})")
    estimate = project(plan, tiers, [])
    print(f"verifier tokens: {estimate['verifier']['total']} (start cost plus tokens per candidate)")
    print(f"judgment tokens: {estimate['judge']['total']}")
    print(f"main session tokens: {estimate['main']['total']}")
    print(f"estimate: {summary(estimate)['total']} (low {summary(estimate)['low']}, high {summary(estimate)['high']})")


def print_report(root, plan, ledger, records):
    first = ledger["first_estimate"]
    print("estimate vs actual:")
    if not is_complete(plan, records):
        read = len({r["unit"] for r in records if r["role"] == "reader"})
        print(f"spent: {sum(r['tokens'] for r in records)}; run not finished: {read} of {len(plan['units'])} "
              "units read, the error of the total is not known yet")
    else:
        forecast, actual, roles, error = like_for_like(first["parts"], records)
        print(f"actual: {actual} (roles measured: {', '.join(roles)})")
        print(f"first estimate: {forecast} (whole run {sum(first['parts'].values())}), error {percent(error)}")
        for stage in ledger["forecasts"]:
            forecast, actual, roles, error = like_for_like(stage["parts"], records)
            label = "pilot forecast" if stage["stage"] == "pilot" else f"forecast after {stage['after_units']} units"
            print(f"{label}: {forecast} (whole run {stage['total']}), error {percent(error)}")
    print("per unit (first estimate vs actual):")
    for r in records:
        if r["role"] == "reader" and r["unit"] in first["units"]:
            estimate = first["units"][r["unit"]]
            print(f"  {r['unit']}: estimate {estimate}, actual {r['tokens']}, error "
                  f"{percent((estimate - r['tokens']) / r['tokens'])}")


def cmd_tokens(args):
    root = Root(args.root)
    root.require_confirmed()
    plan = plan_for(root)
    ledger = load_ledger(root)
    tiers = terms_by_tier(load_calibration(calibration_path(root, ledger, args.calibration)))
    ensure_first_estimate(root, plan, tiers, ledger)
    print(f"units: {len(plan['units'])}")
    print("pilot: " + ", ".join(u["unit"] for u in pick_pilot(plan["units"])))
    print_estimate(plan, tiers)
    found = summary(project(plan, tiers, ledger["records"]))
    if ledger["records"]:
        print(f"spent: {found['spent']}")
        print(forecast_text(found))
        print_report(root, plan, ledger, ledger["records"])
    cap = root.config()["budget"]["max_tokens"]
    print("cap: " + (str(cap) if cap else "none set"))
    if over_cap(root, found["high"]):
        print(stop_line(root, found["high"]))
        return STOP_CODE
    return 0


def register(sub):
    p = sub.add_parser("tokens", help="token estimate with start cost and turns, the pilot units, estimate vs actual")
    p.add_argument("--calibration", metavar="PATH", help="terms to use (default ROOT/calibration.json)")
    p.set_defaults(func=cmd_tokens)
    p = sub.add_parser("calibrate", help="record an agent's usage from its transcript and refit the terms")
    p.add_argument("--transcript", required=True, help="the agent's transcript JSONL; usage is read from it")
    p.add_argument("--role", choices=ROLES, default="reader")
    p.add_argument("--unit", help="the unit the reader or verifier worked on")
    p.add_argument("--candidates", type=int, default=0, help="verifier: how many candidates it was given")
    p.add_argument("--calls", type=int, default=1, help="judge: how many calls the transcript holds")
    p.add_argument("--out", metavar="PATH", help="where the fitted terms go (default ROOT/calibration.json)")
    p.add_argument("--refit", action="store_true", help="refit now, outside the pilot and the every-10-units points")
    p.set_defaults(func=cmd_calibrate)
