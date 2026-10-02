import os
import unittest
from unittest import mock

from cruciblelib import config as config_module
from cruciblelib.common import read_json

from .helpers import CrucibleCase, good_finding, run, src, verdict

UNIT = "svc-u01"
FILES = {"app.py": "import os\nTOKEN_PATH = os.environ['X']\nrun(query)\n", "util.py": "def helper():\n    return 1\n"}


class MemoryTests(CrucibleCase):
    def test_init_writes_memory_null(self):
        root, repo = self.make_root({"a.py": "x = 1\n"}, confirm=False, memory=False)
        self.assertIsNone(read_json(os.path.join(root, "config.json"))["memory"])

    def test_memory_choice_required(self):
        root, repo = self.make_root({"a.py": "x = 1\n"}, confirm=False, memory=False)
        code, out, err = run(root, "confirm")
        self.assertEqual(code, 1)
        self.assertIn("memory not chosen", err)
        self.assertFalse(read_json(os.path.join(root, "config.json"))["confirmed"])
        code, out, err = run(root, "memory", "none")
        self.assertEqual(code, 0, err)
        self.answer_everything(root)
        code, out, err = run(root, "confirm")
        self.assertEqual(code, 0, err)
        self.assertTrue(read_json(os.path.join(root, "config.json"))["confirmed"])

    def test_memory_choice_required_also_for_an_empty_kind(self):
        root, repo = self.make_root({"a.py": "x = 1\n"}, confirm=False, memory=False, config={"memory": {}})
        code, out, err = run(root, "confirm")
        self.assertEqual(code, 1)

    def test_memory_grimoira_records_the_instance_and_confirm_passes(self):
        root, repo = self.make_root({"a.py": "x = 1\n"}, confirm=False, memory=False)
        code, out, err = run(root, "memory", "grimoira", "--instance", "work")
        self.assertEqual(code, 0, err)
        self.assertEqual(read_json(os.path.join(root, "config.json"))["memory"], {"kind": "grimoira", "instance": "work"})
        self.answer_everything(root)
        self.assertEqual(run(root, "confirm")[0], 0)

    def test_summary_prints_the_memory_choice(self):
        root, repo = self.make_root({"a.py": "x = 1\n"}, confirm=False, memory=False)
        code, out, err = run(root, "summary")
        self.assertIn("permanent memory: not chosen yet", out)
        run(root, "memory", "none")
        code, out, err = run(root, "summary")
        self.assertIn("permanent memory: none", out)
        self.assertIn("cannot skip files already read", out)

    def test_detect_reports_whether_grimoira_answers(self):
        root, repo = self.make_root({"a.py": "x = 1\n"}, confirm=False, memory=False)
        with mock.patch.object(config_module, "grimoira_status", return_value="command"):
            code, out, err = run(root, "detect")
        self.assertIn("the grimoira command answers", out)
        with mock.patch.object(config_module, "grimoira_status", return_value=""):
            code, out, err = run(root, "detect")
        self.assertIn("grimoira not found", out)

    def test_grimoira_status_is_stub_safe_when_the_command_fails(self):
        done = mock.Mock(returncode=1)
        with mock.patch.object(config_module.shutil, "which", return_value="/bin/grimoira"), \
                mock.patch.object(config_module.subprocess, "run", return_value=done), \
                mock.patch.object(config_module.glob, "glob", return_value=[]):
            self.assertEqual(config_module.grimoira_status(), "")
        with mock.patch.object(config_module.shutil, "which", return_value=None), \
                mock.patch.object(config_module.glob, "glob", return_value=["x"]):
            self.assertEqual(config_module.grimoira_status(), "plugin")


class DeltaTests(CrucibleCase):
    def finished_audit(self, files=FILES):
        """A finished audit over a repo folder; -> (root, repo)."""
        root, repo = self.make_root(files)
        self.assertEqual(run(root, "inventory")[0], 0)
        self.write_ledger(root, UNIT, sorted(files))
        self.assertEqual(run(root, "proof", UNIT, self.transcript(root, UNIT, sorted(files)))[0], 0)
        self.write(root, f"candidates/{UNIT}.json", [])
        code, out, err = run(root, "accept", UNIT)
        self.assertEqual(code, 0, out + err)
        return root, repo

    def second_audit(self, repo, old_root, *extra):
        new_root = os.path.join(self.tmp(), "audit2")
        self.assertEqual(run(new_root, "init", "--repo", repo)[0], 0)
        self.assertEqual(run(new_root, "memory", "none")[0], 0)
        self.answer_everything(new_root)
        self.assertEqual(run(new_root, "confirm")[0], 0)
        code, out, err = run(new_root, "inventory", "--delta", os.path.join(old_root, "coverage.json"), *extra)
        self.assertEqual(code, 0, out + err)
        return new_root, out

    def test_inventory_writes_a_coverage_ledger_with_sha256(self):
        root = self.make_inventoried(FILES)
        files = read_json(os.path.join(root, "coverage.json"))["files"]
        self.assertEqual(sorted(files), ["svc/app.py", "svc/util.py"])
        self.assertEqual(files["svc/app.py"]["unit"], UNIT)
        self.assertEqual(files["svc/app.py"]["status"], "pending")

    def test_delta_skips_unchanged(self):
        old_root, repo = self.finished_audit()
        with open(os.path.join(repo, "util.py"), "w", encoding="utf-8") as fh:
            fh.write("def helper():\n    return 2\n")
        new_root, out = self.second_audit(repo, old_root)
        self.assertIn("1 unchanged files carried", out)
        files = read_json(os.path.join(new_root, "coverage.json"))["files"]
        self.assertEqual(files["svc/app.py"]["status"], "carried")
        self.assertEqual(files["svc/app.py"]["from"], UNIT)
        self.assertEqual(files["svc/util.py"]["status"], "pending")
        state = read_json(os.path.join(new_root, "state.json"))["units"]
        carried = [u for u, e in state.items() if e["status"] == "carried"]
        pending = [u for u, e in state.items() if e["status"] == "pending"]
        self.assertEqual((len(carried), len(pending)), (1, 1))
        self.assertEqual(state[carried[0]]["carried_from"], [UNIT])
        code, out, err = run(new_root, "status")
        self.assertIn("coverage: 0 of 2 units done, 1 carried (1 pending)", out)
        self.assertIn("files: 1 read this audit, 1 carried from an earlier audit", out)
        self.assertNotIn("coverage 100%", out)

    def test_delta_with_nothing_changed_carries_everything_and_is_complete(self):
        old_root, repo = self.finished_audit()
        new_root, out = self.second_audit(repo, old_root)
        self.assertIn("2 unchanged files carried", out)
        code, out, err = run(new_root, "status")
        self.assertIn("coverage 100%", out)
        code, out, err = run(new_root, "estimate")
        self.assertIn("lines: 0", out)

    def test_delta_does_not_carry_a_file_whose_old_unit_was_not_done(self):
        root, repo = self.make_root(FILES)
        run(root, "inventory")
        new_root, out = self.second_audit(repo, root)
        self.assertIn("0 unchanged files carried", out)

    def test_delta_carry_chains_through_a_second_delta(self):
        old_root, repo = self.finished_audit()
        mid_root, out = self.second_audit(repo, old_root)
        last_root, out = self.second_audit(repo, mid_root)
        files = read_json(os.path.join(last_root, "coverage.json"))["files"]
        self.assertEqual({e["from"] for e in files.values()}, {UNIT})

    def test_delta_refuses_a_file_that_is_not_a_coverage_ledger(self):
        root, repo = self.make_root(FILES)
        bad = os.path.join(self.tmp(), "old.json")
        self.write(os.path.dirname(bad), "old.json", {"nope": 1})
        code, out, err = run(root, "inventory", "--delta", bad)
        self.assertEqual(code, 1)
        self.assertIn("not a coverage.json", err)

    def test_delta_new_file_becomes_a_new_unit(self):
        old_root, repo = self.finished_audit()
        with open(os.path.join(repo, "extra.py"), "w", encoding="utf-8") as fh:
            fh.write("print('new')\n")
        new_root, out = self.second_audit(repo, old_root)
        files = read_json(os.path.join(new_root, "coverage.json"))["files"]
        self.assertEqual(files["svc/extra.py"]["status"], "pending")
        self.assertEqual(files["svc/app.py"]["status"], "carried")


if __name__ == "__main__":
    unittest.main()
