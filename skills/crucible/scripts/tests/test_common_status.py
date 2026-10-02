import json
import os
import threading
import unittest

from cruciblelib import common
from cruciblelib.status import unit_status

from .helpers import CrucibleCase, run


class CommonTests(CrucibleCase):
    def test_parallel_tmp_isolated(self):
        folders = [self.tmp() for _ in range(4)]
        self.assertEqual(len(set(folders)), 4)
        errors = []

        def work(folder):
            try:
                for i in range(25):
                    common.write_json(os.path.join(folder, "state.json"), {"n": i})
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=work, args=(f,)) for f in folders]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        for folder in folders:
            self.assertEqual(common.read_json(os.path.join(folder, "state.json")), {"n": 24})
            self.assertEqual(os.listdir(folder), ["state.json"])

    def test_write_json_is_utf8_and_leaves_no_temp_file(self):
        folder = self.tmp()
        path = os.path.join(folder, "sub", "a.json")
        common.write_json(path, {"name": "café"})
        with open(path, "rb") as fh:
            self.assertIn("café".encode("utf-8"), fh.read())
        self.assertEqual(os.listdir(os.path.dirname(path)), ["a.json"])

    def test_read_json_default_and_broken_file(self):
        folder = self.tmp()
        self.assertEqual(common.read_json(os.path.join(folder, "none.json"), []), [])
        bad = os.path.join(folder, "bad.json")
        with open(bad, "w", encoding="utf-8") as fh:
            fh.write("{oops")
        with self.assertRaises(common.CrucibleError):
            common.read_json(bad)

    def test_source_id_is_stable_and_title_based(self):
        a = common.source_id("svc-u01", {"title": "Handler drops errors"})
        b = common.source_id("svc-u01", {"title": "Handler drops errors", "severity": "low"})
        self.assertEqual(a, b)
        self.assertRegex(a, r"^svc-u01#[0-9a-f]{8}$")
        self.assertNotEqual(a, common.source_id("svc-u01", {"title": "Another"}))

    def test_numbered_pads_the_line_number_to_five_columns(self):
        self.assertEqual(common.numbered(["a", "b", "c"], 2, 3), "    2| b\n    3| c")

    def test_root_loads_units_and_snapshot_lines(self):
        root = self.make_inventoried({"a.py": "one\ntwo\n"})
        r = common.Root(root)
        self.assertEqual(r.units(), ["svc-u01"])
        self.assertEqual(r.unit("svc-u01")["files"], ["a.py"])
        self.assertEqual(r.snapshot_lines("svc", "a.py"), ["one", "two"])
        self.assertEqual(r.findings(), {})
        self.assertEqual(r.candidates("svc-u01"), [])

    def test_cli_reports_an_crucible_error_on_stderr_with_exit_1(self):
        code, out, err = run(self.tmp(), "status")
        self.assertEqual(code, 1)
        self.assertIn("no config", err)


class StatusTests(CrucibleCase):
    def set_state(self, root, unit, **fields):
        path = os.path.join(root, "state.json")
        state = common.read_json(path)
        state["units"][unit].update(fields)
        common.write_json(path, state)

    def test_partial_unit_not_done(self):
        root = self.make_inventoried({"a.py": "x = 1\n", "b.py": "y = 2\n"})
        unit = "svc-u01"
        self.assertEqual(unit_status(common.Root(root), unit), "pending")
        self.write_ledger(root, unit, ["a.py"])
        self.assertEqual(unit_status(common.Root(root), unit), "partial")
        self.set_state(root, unit, status="done")
        self.assertEqual(unit_status(common.Root(root), unit), "partial")

    def test_unit_with_full_ledger_is_not_done_before_accept(self):
        root = self.make_inventoried({"a.py": "x = 1\n", "b.py": "y = 2\n"})
        unit = "svc-u01"
        self.write_ledger(root, unit, ["a.py"], skipped={"b.py": "generated"})
        self.set_state(root, unit, proof="pass")
        self.assertEqual(unit_status(common.Root(root), unit), "partial")

    def test_unit_is_done_only_after_accept_with_full_coverage(self):
        root = self.make_inventoried({"a.py": "x = 1\n", "b.py": "y = 2\n"})
        unit = "svc-u01"
        self.write_ledger(root, unit, ["a.py", "b.py"])
        self.set_state(root, unit, proof="pass", status="done")
        self.assertEqual(unit_status(common.Root(root), unit), "done")

    def test_unit_with_failed_proof_is_not_done(self):
        root = self.make_inventoried({"a.py": "x = 1\n"})
        unit = "svc-u01"
        self.write_ledger(root, unit, ["a.py"])
        self.set_state(root, unit, proof="fail", status="done")
        self.assertEqual(unit_status(common.Root(root), unit), "partial")

    def test_status_counts_coverage_and_skips_split_parents(self):
        root = self.make_inventoried({"a.py": "x = 1\n"})
        state_path = os.path.join(root, "state.json")
        state = common.read_json(state_path)
        state["units"]["svc-u01"]["status"] = "split"
        state["units"]["svc-u01a"] = {"status": "pending"}
        state["units"]["svc-u01b"] = {"status": "pending"}
        parent = common.Root(root).unit("svc-u01")
        for part in ("svc-u01a", "svc-u01b"):
            common.write_json(os.path.join(root, "units", part + ".json"), dict(parent, unit=part, parent="svc-u01"))
        state["tokens_spent"] = 500
        common.write_json(state_path, state)
        cfg = common.Root(root).config()
        cfg["budget"]["max_tokens"] = 2000
        common.write_json(os.path.join(root, "config.json"), cfg)
        code, out, err = run(root, "status")
        self.assertEqual(code, 0, err)
        self.assertIn("coverage: 0 of 2 units done", out)
        self.assertIn("1 split parent not counted", out)
        self.assertIn("findings: 0", out)
        self.assertIn("tokens: 500 of 2000", out)


if __name__ == "__main__":
    unittest.main()
