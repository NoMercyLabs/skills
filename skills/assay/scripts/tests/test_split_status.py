import os
import unittest

from assaylib.common import Root, read_json

from .helpers import AssayCase, good_finding, run, src, verdict

BIG = {"a.py": "x = 1\n" * 40, "b.py": "y = 2\n" * 30, "c.py": "z = 3\n" * 10}
UNIT = "svc-u01"


class SplitTests(AssayCase):
    def split_root(self):
        root = self.make_inventoried(BIG)
        self.write_ledger(root, UNIT, ["a.py"])
        self.write(root, f"candidates/{UNIT}.json", [good_finding()])
        self.write(root, f"review/verdicts-{UNIT}.json", {"x": verdict()})
        code, out, err = run(root, "split", UNIT)
        self.assertEqual(code, 0, out + err)
        return root

    def test_split_makes_two_parts_with_the_parent_set(self):
        root = self.split_root()
        a, b = Root(root).unit(UNIT + "a"), Root(root).unit(UNIT + "b")
        self.assertEqual(a["parent"], UNIT)
        self.assertEqual(b["parent"], UNIT)
        self.assertEqual(sorted(a["files"] + b["files"]), ["a.py", "b.py", "c.py"])
        self.assertTrue(a["files"] and b["files"])
        self.assertEqual(a["lines"] + b["lines"], 80)
        self.assertEqual(read_json(os.path.join(root, "state.json"))["units"][UNIT]["status"], "split")

    def test_split_parks_old_candidates_ledger_and_verdicts(self):
        root = self.split_root()
        self.assertFalse(os.path.exists(os.path.join(root, "candidates", UNIT + ".json")))
        self.assertFalse(os.path.exists(os.path.join(root, "ledger", UNIT + ".json")))
        for relative in (f"candidates/{UNIT}.json", f"ledger/{UNIT}.json", f"review/verdicts-{UNIT}.json"):
            self.assertTrue(os.path.exists(os.path.join(root, "parked", *relative.split("/"))), relative)

    def test_split_parent_not_counted(self):
        root = self.split_root()
        code, out, err = run(root, "status")
        self.assertEqual(code, 0, err)
        self.assertIn("coverage: 0 of 2 units done", out)
        self.assertIn("1 split parent not counted", out)
        code, out, err = run(root, "gate", "--candidates")
        self.assertEqual(out.strip(), "gate: nothing to check")

    def test_split_parent_old_candidates_do_not_block_the_parts(self):
        root = self.split_root()
        part = UNIT + "a"
        files = Root(root).unit(part)["files"]
        self.write_ledger(root, part, files)
        code, out, err = run(root, "proof", part, self.transcript(root, part, files))
        self.assertEqual(code, 0, out + err)
        self.write(root, f"candidates/{part}.json", [])
        code, out, err = run(root, "accept", part)
        self.assertEqual(code, 0, out + err)
        code, out, err = run(root, "status")
        self.assertIn("coverage: 1 of 2 units done", out)

    def test_split_refuses_a_single_file_unit(self):
        root = self.make_inventoried({"a.py": "x = 1\n"})
        code, out, err = run(root, "split", UNIT)
        self.assertEqual(code, 1)
        self.assertIn("holds one file", err)

    def test_split_refuses_a_unit_twice_and_a_done_unit(self):
        root = self.split_root()
        code, out, err = run(root, "split", UNIT)
        self.assertEqual(code, 1)
        self.assertIn("is split", err)

    def test_split_keeps_the_coverage_ledger_pointing_at_the_parts(self):
        root = self.make_inventoried(BIG)
        run(root, "split", UNIT)
        units = {e["unit"] for e in read_json(os.path.join(root, "coverage.json"))["files"].values()}
        self.assertEqual(units, {UNIT + "a", UNIT + "b"})


class StatusTests(AssayCase):
    def test_status_prints_goal_counts_and_tokens(self):
        root = self.make_inventoried({"a.py": "x = 1\n"})
        self.write(root, "findings/F-0001.json", good_finding(id="F-0001", goal=2))
        self.write(root, "findings/F-0002.json", good_finding(id="F-0002", goal=2))
        self.write(root, "findings/F-0003.json", good_finding(id="F-0003", goal=3))
        cfg = read_json(os.path.join(root, "config.json"))
        cfg["budget"]["max_tokens"] = 100
        self.write(root, "config.json", cfg)
        state = read_json(os.path.join(root, "state.json"))
        state["tokens_spent"] = 140
        self.write(root, "state.json", state)
        code, out, err = run(root, "status")
        self.assertIn("findings: 3", out)
        self.assertIn("goal 2 security: 2", out)
        self.assertIn("goal 3 stability: 1", out)
        self.assertIn("goal 1 users can use the product without help: 0", out)
        self.assertIn("tokens: 140 of 100 (over the cap)", out)

    def test_status_says_coverage_100_only_when_every_unit_is_done(self):
        a = good_finding()
        root, unit = self.prepared_unit([a], {src(UNIT, a): verdict()})
        code, out, err = run(root, "status")
        self.assertNotIn("coverage 100%", out)
        self.assertEqual(run(root, "accept", UNIT)[0], 0)
        code, out, err = run(root, "status")
        self.assertIn("coverage 100%", out)

    def test_status_does_not_say_100_for_an_empty_inventory(self):
        root = self.make_inventoried({"a.py": "x = 1\n"})
        os.remove(os.path.join(root, "units", UNIT + ".json"))
        code, out, err = run(root, "status")
        self.assertNotIn("coverage 100%", out)

    def test_estimate_prints_reader_and_verifier_numbers(self):
        root = self.make_inventoried({"a.py": "x\n" * 100})
        code, out, err = run(root, "estimate")
        self.assertIn("reader tokens: 2900", out)
        self.assertIn("verifier tokens: 435", out)
        self.assertIn("tokens: 3335 (about 33 per line)", out)

    def test_estimate_marks_an_estimate_over_the_cap(self):
        root = self.make_inventoried({"a.py": "x\n" * 100}, config={"budget": {"max_tokens": 1000, "tokens_per_line": 34}})
        code, out, err = run(root, "estimate")
        self.assertIn("estimate is over the cap", out)


if __name__ == "__main__":
    unittest.main()
