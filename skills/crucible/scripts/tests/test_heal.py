import os
import unittest

from cruciblelib import heal
from cruciblelib.common import Root, read_json
from cruciblelib.permissions import read_log

from .helpers import CrucibleCase, run

BIG = {"a.py": "x = 1\n" * 40, "b.py": "y = 2\n" * 30, "c.py": "z = 3\n" * 10}
UNIT = "svc-u01"


class Runner:
    def __init__(self, ok=True):
        self.ok, self.calls = ok, []

    def __call__(self, unit, **opts):
        self.calls.append((unit, opts))
        return {"ok": self.ok}


def failed(**over):
    facts = {"exit_code": 1, "output": "", "schema_ok": False, "truncated": False, "tool_calls": 3}
    facts.update(over)
    return facts


class HealTests(CrucibleCase):
    def setUp(self):
        self.path = self.make_inventoried(BIG)
        self.root = Root(self.path)

    def test_failure_classified_from_facts(self):
        cases = {
            "context_exhausted": failed(truncated=True),
            "stub_reply": failed(exit_code=0, output="I will report back when done", tool_calls=0),
            "schema_missing": failed(exit_code=0, output="done"),
            "rate_limited": failed(output="Error: rate limit reached, retry after 60s", retry_after=60),
            "tool_refused": failed(output="tool call refused by the harness"),
            "tracker_scope": failed(output="tracker: token lacks the required scope"),
            "unknown": failed(output="something odd"),
        }
        for expected, facts in cases.items():
            self.assertEqual(heal.classify(facts), expected, facts)
        story = {"exit_code": 0, "output": "I hit a rate limit and context exhausted but fixed it", "schema_ok": True,
                 "truncated": False, "tool_calls": 2}
        self.assertEqual(heal.classify(story), "none")

    def test_known_failure_recovered_by_script(self):
        runner = Runner()
        out = heal.recover(self.root, UNIT, failed(truncated=True), runner)
        self.assertEqual((out["class"], out["result"], out["try"]), ("context_exhausted", "healed", 1))
        self.assertEqual([c[0] for c in runner.calls], [UNIT + "a", UNIT + "b"])
        self.assertEqual(read_json(os.path.join(self.path, "state.json"))["units"][UNIT]["status"], "split")
        runner = Runner()
        heal.recover(self.root, "other-u01", failed(exit_code=0, output="will report back", tool_calls=0), runner)
        self.assertIn("call your first real tool now", runner.calls[0][1]["prompt_addendum"])
        runner = Runner()
        heal.recover(self.root, "other-u02", failed(exit_code=0, output="done"), runner)
        self.assertEqual(runner.calls, [("other-u02", {})])
        runner = Runner()
        heal.recover(self.root, "other-u03", failed(output="rate limit", retry_after=60), runner)
        self.assertEqual(runner.calls, [("other-u03", {"wait": 60, "resume": True})])
        runner = Runner()
        out = heal.recover(self.root, "other-u04", failed(output="token lacks the required scope"), runner)
        self.assertEqual((runner.calls, out["result"]), ([], "stopped"))
        self.assertIn("refresh", out["hint"])

    def test_recovery_max_two_tries_then_blocked(self):
        runner = Runner(ok=False)
        facts = failed(exit_code=0, output="done")
        first = heal.recover(self.root, UNIT, facts, runner)
        second = heal.recover(self.root, UNIT, facts, runner)
        third = heal.recover(self.root, UNIT, facts, runner)
        self.assertEqual([first["result"], second["result"], third["result"]], ["failed", "blocked", "blocked"])
        self.assertEqual(len(runner.calls), 2)
        rows = read_json(os.path.join(self.path, "blockers.json"))
        self.assertEqual([(r["stage"], r["status"]) for r in rows], [(UNIT, "open")])
        self.assertEqual(read_json(os.path.join(self.path, "state.json"))["units"][UNIT]["heal"], "blocked")
        self.assertIn("coverage: 0 of 1 units done", run(self.path, "status")[1])

    def test_gate_refusal_never_healed(self):
        for kind in ("gate", "test", "permission", "visibility"):
            runner = Runner()
            out = heal.recover(self.root, UNIT, failed(refusal=kind, output="rate limit", retry_after=5), runner)
            self.assertEqual((out["class"], out["result"], runner.calls), ("refused", "refused", []), kind)
        self.assertEqual({r["status"] for r in read_log(self.root) if r["group"] == "heal"}, {"refused"})

    def test_unknown_failure_not_retried(self):
        runner = Runner()
        out = heal.recover(self.root, UNIT, failed(exit_code=7, output="strange"), runner)
        self.assertEqual((out["class"], out["result"], runner.calls), ("unknown", "reported", []))
        row = [r for r in read_log(self.root) if r["group"] == "heal"][-1]
        self.assertIn("exit_code=7", row["result"])
        self.assertIn("strange", row["result"])

    def test_heal_logged_and_reported(self):
        heal.recover(self.root, UNIT, failed(exit_code=0, output="done"), Runner())
        rows = [r for r in read_log(self.root) if r["group"] == "heal"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "ok")
        for word in ("schema_missing", UNIT, "try 1", "healed"):
            self.assertIn(word, rows[0]["command"] + " " + rows[0]["result"])
        lines = heal.report_lines(self.root)
        self.assertEqual(lines[0], "healed: 1")
        self.assertIn("schema_missing", lines[1])
        self.assertIn(UNIT, lines[1])
        self.assertIn("healed: 1", run(self.path, "report")[1])


if __name__ == "__main__":
    unittest.main()
