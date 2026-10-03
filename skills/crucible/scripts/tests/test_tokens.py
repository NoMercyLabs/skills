import json
import math
import os
import re

from cruciblelib import lessons, tokens
from cruciblelib.common import Root
from cruciblelib.models import plan_for
from cruciblelib.transcripts import read_usage

from .helpers import CrucibleCase, run

SIZES = (20, 100, 400, 60)
START, PER_LINE, OUTPUT = 9000, 40, 2000


def flat_terms(**over):
    terms = dict(tokens.DEFAULT_TERMS, start_tokens=0, tokens_per_line=0, turn_tokens=0, output_tokens=0,
                 verifier_start_tokens=0, verifier_tokens_per_candidate=0, judge_call_tokens=0,
                 main_session_tokens=0)
    terms.update(over)
    return terms


def write_calibration(path, terms, **extra):
    data = {"version": 1, "tiers": {tier: dict(terms) for tier in ("fast", "balanced", "strong", "top")}}
    data.update(extra)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    return path


def make_transcript(path, turns, total, output, claim="I used 999999 tokens, trust me"):
    """A harness-style agent transcript: usage on every assistant row, a block row repeating each message id."""
    base, out_base = total // turns, output // turns
    with open(path, "w", encoding="utf-8") as fh:
        for i in range(turns):
            last = i == turns - 1
            this_total = total - base * (turns - 1) if last else base
            this_out = output - out_base * (turns - 1) if last else out_base
            usage = {"input_tokens": 5, "cache_creation_input_tokens": 7,
                     "cache_read_input_tokens": this_total - this_out - 12, "output_tokens": this_out,
                     "service_tier": "standard"}
            for block in ({"type": "text", "text": claim}, {"type": "tool_use", "id": f"t{i}", "name": "Read",
                                                             "input": {"file_path": "a.py"}}):
                row = {"type": "assistant", "message": {"id": f"msg{i}", "role": "assistant",
                                                        "content": [block], "usage": usage}}
                fh.write(json.dumps(row) + "\n")
            fh.write(json.dumps({"type": "user", "message": {"role": "user", "content": "ok"}}) + "\n")
            fh.write("not json at all\n")
    return path


def number(out, label):
    return int(re.search(rf"{label}: (\d+)", out).group(1))


def percent(out, label):
    return float(re.search(rf"{label}: \d+[^\n]*?error ([+-]\d+\.\d)%", out).group(1))


class TokenTests(CrucibleCase):
    def setup_audit(self, config=None):
        files = {f"f{i}.py": "x = 1\n" * n for i, n in enumerate(SIZES)}
        cfg = {"unit_bytes": 1}
        cfg.update(config or {})
        root, repo = self.make_root(files, config=cfg)
        self.assertEqual(run(root, "inventory")[0], 0)
        units = {u["unit"]: u for u in plan_for(Root(root))["units"]}
        self.assertEqual(sorted(u["lines"] for u in units.values()), sorted(SIZES))
        return root, sorted(units.values(), key=lambda u: u["lines"])

    def formula(self, lines, terms=tokens.DEFAULT_TERMS):
        return (terms["start_tokens"] + terms["tokens_per_line"] * lines + terms["output_tokens"]
                + terms["turn_tokens"] * (1 + math.ceil(lines / terms["lines_per_turn"])))

    def actual(self, lines, bump=0):
        turns = 1 + math.ceil(lines / tokens.DEFAULT_TERMS["lines_per_turn"])
        return START + PER_LINE * lines + OUTPUT + tokens.DEFAULT_TERMS["turn_tokens"] * turns + bump, turns

    def record(self, root, unit, bump=0):
        total, turns = self.actual(unit["lines"], bump)
        path = make_transcript(os.path.join(self.tmp(), f"{unit['unit']}.jsonl"), turns, total, OUTPUT)
        code, out, err = run(root, "calibrate", "--unit", unit["unit"], "--transcript", path)
        return code, out, err, total

    def test_forecast_lesson_changes_estimate(self):
        root, units = self.setup_audit()
        path = write_calibration(os.path.join(self.tmp(), "c.json"), flat_terms(tokens_per_line=10))
        code, before, err = run(root, "tokens", "--calibration", path)
        self.assertEqual(code, 0, err)
        flat = run(root, "estimate")[1]
        lessons.save(Root(root), {"id": "L-dddd4444", "target": "audit", "kind": "hand", "signature": "s",
                                  "state": "active", "evidence": {"count": 3, "records": []},
                                  "change": {"forecast_factor": 2}})
        code, after, err = run(root, "tokens", "--calibration", path)
        self.assertEqual(code, 0, err)
        self.assertEqual(number(after, "estimate"), 2 * number(before, "estimate"))
        self.assertEqual(number(after, "reader tokens"), 2 * number(before, "reader tokens"))
        scaled = run(root, "estimate")[1]
        self.assertEqual(number(scaled, "reader tokens"), 2 * number(flat, "reader tokens"))
        total = [int(re.search(r"(?m)^tokens: (\d+)", text).group(1)) for text in (flat, scaled)]
        self.assertEqual(total[1], 2 * total[0])

    def test_forecast_refit_composes_with_active_factor(self):
        root, units = self.setup_audit()
        lessons.save(Root(root), {"id": "L-eeee5555", "target": "audit", "kind": "hand", "signature": "s",
                                  "state": "active", "evidence": {"count": 3, "records": []},
                                  "change": {"forecast_factor": 2}})
        for unit in units[:3]:
            self.assertEqual(self.record(root, unit)[0], 0)
        plan, ledger = plan_for(Root(root)), tokens.load_ledger(Root(root))
        tiers = tokens.terms_by_tier(tokens.load_calibration(os.path.join(root, "calibration.json")))
        tier = units[3]["reader_tier"]
        self.assertEqual(tiers[tier]["samples"], 3)
        shown = tokens.project(plan, tiers, ledger["records"])["reader"]
        self.assertEqual(shown["left"], tokens.reader_tokens(tiers[tier], units[3]["lines"]))
        first = ledger["first_estimate"]["units"][units[3]["unit"]]
        self.assertEqual(first, 2 * tokens.reader_tokens(tokens.terms_by_tier({})[tier], units[3]["lines"]))

    def test_refit_not_double_scaled_any_tier(self):
        root, units = self.setup_audit()
        plan = plan_for(Root(root))
        tiers = tokens.terms_by_tier({})
        records = []
        for tier in tokens.TIERS:
            for lines in (100, 300):
                records.append({"role": "reader", "tier": tier, "lines": lines, "turns": 2, "output": 1000,
                                "tokens": 20000 + 30 * lines})
            for candidates in (1, 3):
                records.append({"role": "verifier", "tier": tier, "candidates": candidates,
                                "tokens": 5000 + 700 * candidates})
            records.append({"role": "judge", "tier": tier, "calls": 2, "tokens": 9000})
            records.append({"role": "main", "tier": tier, "tokens": 31000})
        fitted = dict(tiers, **tokens.fit_terms(tiers, records))
        for tier in tokens.TIERS:
            self.assertNotEqual(fitted[tier], tiers[tier])
        plain = tokens.project(dict(plan, forecast_factor=1), fitted, [])
        scaled = tokens.project(dict(plan, forecast_factor=2), fitted, [])
        for role in tokens.ROLES:
            with self.subTest(role=role):
                self.assertGreater(plain[role]["left"], 0)
                self.assertEqual(scaled[role]["left"], plain[role]["left"])
        unfitted = tokens.project(dict(plan, forecast_factor=2), tiers, [])
        self.assertEqual(unfitted["verifier"]["left"], 2 * tokens.project(dict(plan, forecast_factor=1), tiers, [])["verifier"]["left"])

    def test_estimate_includes_start_cost_and_turns(self):
        root, units = self.setup_audit()
        terms = flat_terms(start_tokens=1000, tokens_per_line=10, turn_tokens=500, lines_per_turn=100,
                           output_tokens=200)
        path = write_calibration(os.path.join(self.tmp(), "c.json"), terms)
        code, out, err = run(root, "tokens", "--calibration", path)
        self.assertEqual(code, 0, err)
        self.assertEqual(number(out, "reader tokens"), sum(self.formula(u["lines"], terms) for u in units))
        self.assertIn("start cost", out)
        self.assertIn("turns", out)
        without = write_calibration(os.path.join(self.tmp(), "n.json"), dict(terms, start_tokens=0, turn_tokens=0))
        code, out2, err = run(root, "tokens", "--calibration", without)
        turns = sum(1 + math.ceil(u["lines"] / 100) for u in units)
        self.assertEqual(number(out, "reader tokens") - number(out2, "reader tokens"),
                         1000 * len(units) + 500 * turns)

    def test_usage_read_from_harness_not_agent(self):
        root, units = self.setup_audit()
        path = make_transcript(os.path.join(self.tmp(), "a.jsonl"), 3, 30000, 900)
        usage = read_usage(path)
        self.assertEqual((usage["tokens"], usage["output"], usage["turns"]), (30000, 900, 3))
        code, out, err, total = self.record(root, units[0])
        self.assertEqual(code, 0, err)
        with open(os.path.join(root, "tokens.json"), encoding="utf-8") as fh:
            record = json.load(fh)["records"][0]
        self.assertEqual(record["tokens"], total)
        self.assertEqual(Root(root).state()["tokens_spent"], total)
        with self.assertRaises(SystemExit):
            run(root, "calibrate", "--unit", units[0]["unit"], "--transcript", path, "--tokens", "5")
        empty = os.path.join(self.tmp(), "empty.jsonl")
        with open(empty, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"type": "assistant", "message": {"content": "I used 5 tokens"}}) + "\n")
        code, out, err = run(root, "calibrate", "--unit", units[0]["unit"], "--transcript", empty)
        self.assertEqual(code, 1)
        self.assertIn("no usage", err)

    def test_pilot_spans_unit_sizes(self):
        units = [{"unit": f"u{i}", "lines": n, "risk": risk} for i, (n, risk) in
                 enumerate([(5, "normal"), (50, "normal"), (300, "high"), (20, "low"), (900, "normal")])]
        self.assertEqual({u["unit"] for u in tokens.pick_pilot(units)}, {"u0", "u2", "u4"})
        plain = [dict(u, risk="normal") for u in units]
        picked = tokens.pick_pilot(plain)
        self.assertEqual(len(picked), 3)
        self.assertEqual({picked[0]["lines"], picked[-1]["lines"]}, {5, 900})
        self.assertIn(picked[1]["lines"], (20, 50, 300))
        self.assertEqual(len(tokens.pick_pilot(units[:2])), 2)
        root, real = self.setup_audit()
        code, out, err = run(root, "tokens")
        self.assertEqual(code, 0, err)
        pilot = re.search(r"pilot: ([^\n]+)", out).group(1)
        self.assertIn(real[0]["unit"], pilot)
        self.assertIn(real[-1]["unit"], pilot)

    def test_forecast_refits_after_pilot(self):
        self.assertTrue(all(tokens.refit_due(n) for n in (3, 10, 20, 30)))
        self.assertFalse(any(tokens.refit_due(n) for n in (0, 1, 2, 4, 9, 11, 13)))
        root, units = self.setup_audit()
        calibration = os.path.join(root, "calibration.json")
        for unit in units[:2]:
            self.assertEqual(self.record(root, unit)[0], 0)
        self.assertFalse(os.path.exists(calibration))
        code, out, err, total = self.record(root, units[2])
        self.assertEqual(code, 0, err)
        with open(calibration, encoding="utf-8") as fh:
            fitted = json.load(fh)
        tier = plan_for(Root(root))["units"][0]["reader_tier"]
        self.assertAlmostEqual(fitted["tiers"][tier]["start_tokens"], START, delta=1)
        self.assertAlmostEqual(fitted["tiers"][tier]["tokens_per_line"], PER_LINE, delta=0.01)
        self.assertEqual(fitted["tiers"][tier]["samples"], 3)
        with open(os.path.join(root, "tokens.json"), encoding="utf-8") as fh:
            stages = [f["stage"] for f in json.load(fh)["forecasts"]]
        self.assertEqual(stages, ["pilot"])
        self.assertRegex(out, r"forecast: \d+ \(low \d+, high \d+\)")
        out_file = os.path.join(self.tmp(), "elsewhere.json")
        code, out, err = run(root, "calibrate", "--unit", units[2]["unit"], "--out", out_file, "--refit",
                             "--transcript", make_transcript(os.path.join(self.tmp(), "r.jsonl"), 3, total, OUTPUT))
        self.assertEqual(code, 0, err)
        self.assertTrue(os.path.exists(out_file))

    def test_pilot_forecast_includes_measured_verifier(self):
        root, units = self.setup_audit()
        for unit in units[:3]:
            self.assertEqual(self.record(root, unit)[0], 0)
        measured = 0
        for unit, candidates in zip(units[:3], (2, 4, 6)):
            total = 60000 + 50000 * candidates
            measured += total
            path = make_transcript(os.path.join(self.tmp(), f"v-{unit['unit']}.jsonl"), 2, total, 500)
            code, out, err = run(root, "calibrate", "--role", "verifier", "--unit", unit["unit"],
                                 "--candidates", str(candidates), "--transcript", path)
            self.assertEqual(code, 0, err)
        self.assertIn("refit after 3 units", out)
        plan = plan_for(Root(root))
        with open(os.path.join(root, "calibration.json"), encoding="utf-8") as fh:
            fitted = json.load(fh)["tiers"][plan["roles"]["verifier"]["tier"]]
        self.assertEqual(fitted["verifier_samples"], 3)
        self.assertAlmostEqual(fitted["verifier_tokens_per_candidate"], 50000, delta=1)
        with open(os.path.join(root, "tokens.json"), encoding="utf-8") as fh:
            stages = {f["stage"]: f for f in json.load(fh)["forecasts"]}
        self.assertEqual(sorted(stages), ["pilot"])
        verifier = stages["pilot"]["parts"]["verifier"]
        self.assertEqual(verifier, measured + tokens.verifier_tokens(fitted))
        self.assertNotEqual(tokens.verifier_tokens(fitted), tokens.verifier_tokens(tokens.DEFAULT_TERMS))

    def test_forecast_over_cap_stops(self):
        tiny = {"budget": {"max_tokens": 1000, "tokens_per_line": 34}}
        root, units = self.setup_audit(config=tiny)
        code, out, err = run(root, "tokens")
        self.assertEqual(code, 3)
        self.assertIn("STOP", out)
        self.assertFalse(tokens.readers_may_start(Root(root)))
        roomy, units = self.setup_audit(config={"budget": {"max_tokens": 10_000_000, "tokens_per_line": 34}})
        code, out, err = run(roomy, "tokens")
        self.assertEqual(code, 0, err)
        self.assertNotIn("STOP", out)
        self.assertTrue(tokens.readers_may_start(Root(roomy)))
        spent = self.record(roomy, units[0])[3]
        cap = {"budget": {"max_tokens": spent, "tokens_per_line": 34}}
        capped, units = self.setup_audit(config=cap)
        code, out, err, total = self.record(capped, units[0])
        self.assertEqual(code, 3)
        self.assertIn("STOP", out)

    def test_report_states_estimate_errors(self):
        root, units = self.setup_audit()
        first = sum(self.formula(u["lines"]) for u in units)
        self.assertEqual(run(root, "tokens")[0], 0)
        order = units[:2] + [units[3]]
        for unit in order:
            self.assertEqual(self.record(root, unit)[0], 0)
        out = run(root, "tokens")[1]
        self.assertIn("run not finished", out)
        last = self.record(root, units[2], bump=3000)
        self.assertEqual(last[0], 0, last[2])
        actuals = [self.actual(u["lines"], 3000 if u is units[2] else 0)[0] for u in units]
        total = sum(actuals)
        code, out, err = run(root, "tokens")
        self.assertEqual(code, 0, err)
        self.assertEqual(number(out, "actual"), total)
        self.assertAlmostEqual(percent(out, "first estimate"), (first - total) / total * 100, delta=0.15)
        self.assertEqual(number(out, "first estimate"), first)
        self.assertRegex(out, r"pilot forecast: \d+")
        self.assertIn("error", out.split("pilot forecast")[1])
        self.assertIn("per unit", out)
        for unit in units:
            self.assertRegex(out, rf"{unit['unit']}: estimate \d+, actual \d+, error [+-]\d+\.\d%")
        with open(os.path.join(root, "calibration.json"), encoding="utf-8") as fh:
            runs = json.load(fh)["runs"]
        self.assertTrue(runs)
        for entry in runs:
            self.assertIsInstance(entry["forecast_error"], float)
            self.assertEqual(entry["actual"], total)
