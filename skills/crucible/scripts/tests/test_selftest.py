import json
import os
import unittest
from unittest import mock

from cruciblelib import selftest
from cruciblelib.common import Root

from .helpers import CrucibleCase, run

SKILL = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXPECTED = os.path.join(SKILL, "fixtures", "seeded", "EXPECTED.json")


def expected():
    with open(EXPECTED, encoding="utf-8") as fh:
        return json.load(fh)


class SelftestTests(CrucibleCase):
    def prepared(self):
        work = os.path.join(self.tmp(), "run")
        code, out, err = run(work, "selftest", "--prepare", "--work", work)
        self.assertEqual(code, 0, out + err)
        return work, out

    def file_finding(self, work, number, path, line_a, line_b=None):
        ref = f"{path}:{line_a}" + (f"-{line_b}" if line_b else "")
        self.write(work, f"findings/F-{number:04d}.json", {
            "id": f"F-{number:04d}", "repo": "repo", "title": f"Seeded check number {number}",
            "where": [{"kind": "file", "ref": ref}],
            "evidence": [{"kind": "file_line", "ref": ref, "quote": "x"}]})

    def finish_units(self, work):
        """Mark every unit read whole, proven and accepted, the way a finished run leaves them."""
        root = Root(work)
        state = root.state()
        for unit in root.units():
            self.write_ledger(work, unit, root.unit(unit)["files"])
            state["units"][unit] = {"status": "done", "proof": "pass"}
        root.save_state(state)

    def test_replay_runs_the_pipeline_and_refuses_a_tampered_transcript(self):
        work = os.path.join(self.tmp(), "replay")
        code, out, err = run(work, "selftest", "--replay", "--work", work)
        self.assertEqual(code, 0, out + err)
        self.assertIn("scripted", out)
        self.assertIn("PROOF PASS", out)
        self.assertIn("coverage 100%", out)
        self.assertRegex(out, r"TAMPER REFUSED: \S+ lines \d+-\d+ do not match their stamp")
        self.assertTrue(Root(work).findings(), "replay accepted no finding")

    def test_score_counts_found_missed_invented(self):
        work, _ = self.prepared()
        self.file_finding(work, 1, "app/db.py", 205, 215)
        self.file_finding(work, 2, "app/routes.py", 88)
        self.file_finding(work, 3, "web/main.js", 1)
        code, out, err = run(work, "selftest", "--score")
        self.assertEqual(code, 1, out + err)
        self.assertIn("found 2 of 12", out)
        self.assertIn("missed 10", out)
        self.assertIn("D03", out)
        self.assertNotIn("D01,", out.split("missed")[1])
        self.assertIn("invented 1", out)

    def test_score_passes_when_recall_and_coverage_are_met(self):
        work, _ = self.prepared()
        for number, defect in enumerate(expected(), 1):
            self.file_finding(work, number, defect["file"], defect["line_start"], defect["line_end"])
        self.finish_units(work)
        code, out, err = run(work, "selftest", "--score")
        self.assertEqual(code, 0, out + err)
        self.assertIn("found 12 of 12", out)
        self.assertIn("invented 0", out)
        self.assertIn("coverage 100%", out)
        self.assertIn("proof PASS", out)

    def temp_expected(self):
        """A temp EXPECTED file with one seeded defect and one known extra; the real file is never touched."""
        path = os.path.join(self.tmp(), "EXPECTED.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"defects": [{"id": "D03", "file": "app/routes.py", "line_start": 233, "line_end": 233,
                                    "goal": "security", "summary": "seeded"}],
                       "known_extras": [{"file": "app/db.py", "line_start": 100, "line_end": 110,
                                         "title": "a real defect that is not seeded"}]}, fh)
        return path

    def score_with_temp_expected(self, work):
        with mock.patch.object(selftest, "EXPECTED", self.temp_expected()):
            return run(work, "selftest", "--score")

    def test_known_extra_not_counted_invented(self):
        work, _ = self.prepared()
        self.file_finding(work, 1, "app/routes.py", 233)
        self.file_finding(work, 2, "app/db.py", 105)
        code, out, err = self.score_with_temp_expected(work)
        self.assertIn("found 1 of 1", out)
        self.assertIn("extra (known) 1 (F-0002)", out)
        self.assertIn("invented 0", out)
        self.assertNotIn("invented findings accepted", out)

    def test_unlisted_finding_still_invented(self):
        work, _ = self.prepared()
        self.file_finding(work, 1, "app/routes.py", 233)
        self.file_finding(work, 2, "app/db.py", 105)
        self.file_finding(work, 3, "web/main.js", 1)
        code, out, err = self.score_with_temp_expected(work)
        self.assertEqual(code, 1, out + err)
        self.assertIn("extra (known) 1 (F-0002)", out)
        self.assertIn("invented 1 (F-0003)", out)
        self.assertIn("1 invented findings accepted", out)

    def test_prepare_hides_expected_defects(self):
        work, out = self.prepared()
        for folder, _, names in os.walk(work):
            self.assertNotIn("EXPECTED.json", names, folder)
        root = Root(work)
        for unit in root.units():
            self.assertFalse([f for f in root.unit(unit)["files"] if "EXPECTED" in f])
        self.assertTrue(root.units())
        self.assertIn(f"show {root.units()[0]} ", out)
        self.assertIn("proof ", out)
        self.assertIn("accept ", out)

    def test_score_coverage_below_100_fails(self):
        work, _ = self.prepared()
        for number, defect in enumerate(expected(), 1):
            self.file_finding(work, number, defect["file"], defect["line_start"], defect["line_end"])
        code, out, err = run(work, "selftest", "--score")
        self.assertEqual(code, 1, out + err)
        self.assertIn("found 12 of 12", out)
        self.assertIn("coverage 0%", out)
        self.assertNotIn("coverage 100%", out)


if __name__ == "__main__":
    unittest.main()
