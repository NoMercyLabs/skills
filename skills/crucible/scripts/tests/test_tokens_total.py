import json
import os
from unittest import mock

from cruciblelib import tokens
from cruciblelib.common import Root
from cruciblelib.models import plan_for

from .helpers import CrucibleCase, run
from .test_tokens import make_transcript


class TokensTotalTests(CrucibleCase):
    def prepared(self, config=None):
        cfg = {"unit_bytes": 100000}
        cfg.update(config or {})
        root, repo = self.make_root({"a.py": "x = 1\n" * 40, "b.py": "y = 2\n" * 60}, config=cfg)
        self.assertEqual(run(root, "inventory")[0], 0)
        return root

    def calibrate(self, root, role, unit, total, name):
        path = make_transcript(os.path.join(self.tmp(), name + ".jsonl"), 2, total, 100)
        code, out, err = run(root, "calibrate", "--role", role, "--unit", unit, "--transcript", path)
        self.assertIn(code, (0, tokens.STOP_CODE), err)

    def ledger_sum(self, root):
        with open(os.path.join(root, "tokens.json"), encoding="utf-8") as fh:
            return sum(r["tokens"] for r in json.load(fh)["records"])

    def test_tokens_spent_matches_ledger_after_split(self):
        root = self.prepared()
        parent = plan_for(Root(root))["units"][0]["unit"]
        self.calibrate(root, "reader", parent, 1000, "parent")
        self.assertEqual(run(root, "split", parent)[0], 0)
        part = parent + "a"
        path = make_transcript(os.path.join(self.tmp(), "again.jsonl"), 2, 300, 100)
        for _ in range(2):  # a retried call: the second one replaces the first
            run(root, "calibrate", "--role", "reader", "--unit", part, "--transcript", path)
        self.calibrate(root, "reader", parent + "b", 500, "b")
        spent = tokens.tokens_spent(Root(root))
        self.assertEqual(spent, self.ledger_sum(root) + 300)
        self.assertIn(f"tokens: {spent} of", run(root, "status")[1])
        self.assertIn(f"tokens: {spent} of", run(root, "report")[1])

    def test_cap_counts_the_tokens_of_a_replaced_record(self):
        root = self.prepared({"budget": {"max_tokens": 65000, "tokens_per_line": 34}})
        unit = plan_for(Root(root))["units"][0]["unit"]
        self.calibrate(root, "reader", unit, 60000, "first")
        self.calibrate(root, "reader", unit, 10000, "second")
        self.assertEqual(self.ledger_sum(root), 10000)
        self.assertEqual(tokens.tokens_spent(Root(root)), 70000)
        self.assertIn("tokens: 70000 of 65000 (over the cap)", run(root, "status")[1])
        self.assertFalse(tokens.readers_may_start(Root(root)))

    def test_ledger_is_written_before_the_refit(self):
        root = self.prepared()
        unit = plan_for(Root(root))["units"][0]["unit"]
        path = make_transcript(os.path.join(self.tmp(), "u.jsonl"), 2, 20000, 100)
        with mock.patch.object(tokens, "fit_terms", side_effect=RuntimeError("refit failed")):
            with self.assertRaises(RuntimeError):
                run(root, "calibrate", "--role", "reader", "--unit", unit, "--transcript", path)
        self.assertEqual(self.ledger_sum(root), 20000)
        self.assertEqual(tokens.tokens_spent(Root(root)), 20000)

    def test_a_state_with_a_stored_total_and_no_ledger_still_reads(self):
        root = self.prepared()
        state = Root(root).state()
        state["tokens_spent"] = 500
        Root(root).save_state(state)
        self.assertEqual(tokens.tokens_spent(Root(root)), 500)
        self.assertIn("tokens: 500 of", run(root, "status")[1])

    def test_a_stale_stored_total_loses_to_the_ledger(self):
        root = self.prepared()
        unit = plan_for(Root(root))["units"][0]["unit"]
        self.calibrate(root, "reader", unit, 20000, "u")
        state = Root(root).state()
        state["tokens_spent"] = 999999
        Root(root).save_state(state)
        self.assertEqual(tokens.tokens_spent(Root(root)), 20000)
