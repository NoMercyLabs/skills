import argparse
import os
import unittest
from unittest import mock

from cruciblelib import verdicts
from cruciblelib.common import read_json

from .helpers import CrucibleCase, good_finding, run, src, verdict

UNIT = "svc-u01"


class VerdictCheckTests(CrucibleCase):
    def check(self, candidates, verdicts, **kw):
        root, unit = self.prepared_unit(candidates, verdicts, **kw)
        code, out, err = run(root, "verdict-check", unit)
        return root, code, out + err

    def test_every_candidate_with_a_verdict_passes(self):
        a, b = good_finding(), good_finding(title="Second handler problem here")
        root, code, out = self.check([a, b], {src(UNIT, a): verdict(), src(UNIT, b): verdict("reject")})
        self.assertEqual(code, 0, out)
        self.assertIn("PASS svc-u01: 2 of 2 judged", out)

    def test_candidate_without_a_verdict_refused(self):
        a, b = good_finding(), good_finding(title="Second handler problem here")
        root, code, out = self.check([a, b], {src(UNIT, a): verdict()})
        self.assertEqual(code, 1)
        self.assertIn(f"{src(UNIT, b)}: no final verdict", out)

    def test_verdict_without_reason_or_checked_lines_refused(self):
        a = good_finding()
        for bad in (verdict(reason=" "), verdict(checked=[])):
            root, code, out = self.check([a], {src(UNIT, a): bad})
            self.assertEqual(code, 1)
            self.assertIn("no final verdict", out)

    def test_reject_without_other_defect_refused(self):
        a = good_finding()
        no_field = verdict("reject")
        del no_field["other_defect"]
        for bad in (no_field, verdict("reject", other_defect="there is a second bug")):
            root, code, out = self.check([a], {src(UNIT, a): bad})
            self.assertEqual(code, 1)
            self.assertIn("other_defect", out)

    def test_reject_saying_the_defect_is_real_refused(self):
        a = good_finding()
        for reason in ("The mismatch is real but dead code.", "a latent defect remains",
                       "the real consequence is the opposite of the claim"):
            root, code, out = self.check([a], {src(UNIT, a): verdict("reject", reason=reason)})
            self.assertEqual(code, 1, reason)
            self.assertIn("says the defect is real", out)

    def test_lead_without_verdict_refused(self):
        a = good_finding()
        leads = [{"ref": "app.py:3", "suspect": "query is unescaped", "dropped_because": "looked fine"}]
        root, code, out = self.check([a], {src(UNIT, a): verdict()}, leads=leads)
        self.assertEqual(code, 1)
        self.assertIn("lead app.py:3: no verdict", out)
        self.write(root, f"review/verdicts-{UNIT}.json", {
            src(UNIT, a): verdict(),
            "_leads": {"app.py:3": {"verdict": "cleared", "reason": "query is a constant", "checked": ["app.py:3"]}}})
        code, out, err = run(root, "verdict-check", UNIT)
        self.assertEqual(code, 0, out + err)
        self.assertIn("2 of 2 judged", out)

    def test_checked_line_past_end_of_file_refused(self):
        a = good_finding()
        root, code, out = self.check([a], {src(UNIT, a): verdict(checked=["app.py:2", "app.py:99"])})
        self.assertEqual(code, 1)
        self.assertIn("past the end of the file (3 lines)", out)

    def test_checked_entry_without_a_line_refused(self):
        a = good_finding()
        root, code, out = self.check([a], {src(UNIT, a): verdict(checked=["app.py"])})
        self.assertEqual(code, 1)
        self.assertIn("is not path:line", out)

    def test_checked_range_and_comma_forms_are_checked(self):
        a = good_finding()
        root, code, out = self.check([a], {src(UNIT, a): verdict(checked=["app.py:1-3", "app.py:2,3 (git show abc123)"])})
        self.assertEqual(code, 0, out)
        root, code, out = self.check([a], {src(UNIT, a): verdict(checked=["app.py:2-9"])})
        self.assertEqual(code, 1)

    def test_fix_with_an_unknown_field_path_refused(self):
        a = good_finding()
        root, code, out = self.check([a], {src(UNIT, a): verdict("fix", fix={"severty": "low"})})
        self.assertEqual(code, 1)
        self.assertIn("no field 'severty'", out)

    def test_fix_without_fields_refused(self):
        a = good_finding()
        root, code, out = self.check([a], {src(UNIT, a): verdict("fix", fix={})})
        self.assertEqual(code, 1)
        self.assertIn("needs a 'fix' object", out)

    def test_fix_verdict_can_add_visibility_and_links(self):
        a = good_finding()
        del a["visibility"]
        a.pop("verified_links", None)
        fix = {"visibility": "private", "verified_links": ["app.py:2"]}
        root, code, out = self.check([a], {src(UNIT, a): verdict("fix", fix=fix)})
        self.assertEqual(code, 0, out)
        self.assertNotIn("no field", out)

    def test_verdict_links_checked_by_gate(self):
        def accept(links):
            a = good_finding(root_cause_verified=True)
            a["not_checked"] = []
            a.pop("verified_links", None)
            fix = {"verified_links": links}
            checked = ["app.py:2", "app.py:3"]
            root, unit = self.prepared_unit([a], {src(UNIT, a): verdict("fix", fix=fix, checked=checked)})
            code, out, err = run(root, "accept", unit)
            return code, out + err

        code, out = accept(["app.py:2"])
        self.assertEqual(code, 1, out)
        self.assertIn("verified_links does not list every link", out)
        code, out = accept(["app.py:3", "app.py:2", "gone.py:9"])
        self.assertEqual(code, 1, out)
        self.assertIn("gone.py:9", out)
        code, out = accept(["app.py:3", "app.py:2"])
        self.assertEqual(code, 0, out)

    def test_verdict_check_reads_extra_verdict_files(self):
        a, b = good_finding(), good_finding(title="Second handler problem here")
        root, unit = self.prepared_unit([a, b], {src(UNIT, a): verdict()})
        self.write(root, f"review/verdicts-{UNIT}-b.json", {src(UNIT, b): verdict()})
        code, out, err = run(root, "verdict-check", unit)
        self.assertEqual(code, 0, out + err)


class AcceptTests(CrucibleCase):
    def accept(self, root, unit=UNIT):
        code, out, err = run(root, "accept", unit)
        return code, out + err

    def test_accept_refused_without_a_passed_proof(self):
        a = good_finding()
        root, unit = self.prepared_unit([a], {src(UNIT, a): verdict()}, prove=False)
        code, out = self.accept(root)
        self.assertEqual(code, 1)
        self.assertIn("proof has not passed", out)
        self.assertEqual(read_json(os.path.join(root, "state.json"))["units"][UNIT]["status"], "pending")
        self.assertEqual(os.listdir(os.path.join(root, "findings")) if os.path.isdir(os.path.join(root, "findings")) else [], [])

    def test_accept_refused_after_a_failed_proof(self):
        a = good_finding()
        root, unit = self.prepared_unit([a], {src(UNIT, a): verdict()}, prove=False)
        run(root, "proof", unit, self.transcript(root, unit, ["app.py"], drop_line=2))
        code, out = self.accept(root)
        self.assertEqual(code, 1)
        self.assertIn("proof has not passed", out)

    def test_accept_promotes_accepted_and_skips_rejected(self):
        a, b = good_finding(), good_finding(title="Second handler problem here")
        root, unit = self.prepared_unit([a, b], {src(UNIT, a): verdict(), src(UNIT, b): verdict("reject")})
        code, out = self.accept(root)
        self.assertEqual(code, 0, out)
        self.assertEqual(sorted(os.listdir(os.path.join(root, "findings"))), ["F-0001.json"])
        finding = read_json(os.path.join(root, "findings", "F-0001.json"))
        self.assertEqual(finding["id"], "F-0001")
        self.assertEqual(finding["source"], src(UNIT, a))
        state = read_json(os.path.join(root, "state.json"))
        self.assertEqual(state["units"][UNIT]["status"], "done")
        self.assertEqual(state["accepted"], {src(UNIT, a): "F-0001"})
        code, out, err = run(root, "status")
        self.assertIn("coverage: 1 of 1 units done", out)

    def test_accept_refused_when_verdict_check_fails(self):
        a = good_finding()
        root, unit = self.prepared_unit([a], {})
        code, out = self.accept(root)
        self.assertEqual(code, 1)
        self.assertIn("verdict-check FAIL", out)
        self.assertEqual(read_json(os.path.join(root, "state.json"))["units"][UNIT]["status"], "pending")

    def test_fix_applied_to_the_right_field(self):
        a = good_finding()
        fix = {"severity": "low", "what.expected": "a message naming X", "evidence[0].ref": "app.py:2",
               "where.0.ref": "app.py:2-3"}
        root, unit = self.prepared_unit([a], {src(UNIT, a): verdict("fix", fix=fix)})
        code, out = self.accept(root)
        self.assertEqual(code, 0, out)
        finding = read_json(os.path.join(root, "findings", "F-0001.json"))
        self.assertEqual(finding["severity"], "low")
        self.assertEqual(finding["what"]["expected"], "a message naming X")
        self.assertEqual(finding["what"]["summary"], a["what"]["summary"])
        self.assertEqual(finding["where"][0]["ref"], "app.py:2-3")
        self.assertEqual(finding["title"], a["title"])

    def test_verifier_fix_survives_the_next_accept(self):
        a = good_finding()
        fix = {"title": "Handler reads its token path with no default", "severity": "high"}
        root, unit = self.prepared_unit([a], {src(UNIT, a): verdict("fix", fix=fix)})
        self.assertEqual(self.accept(root)[0], 0)
        stored = read_json(os.path.join(root, "candidates", UNIT + ".json"))[0]
        self.assertEqual(stored["severity"], "high")
        self.assertEqual(stored["title"], fix["title"])
        state = read_json(os.path.join(root, "state.json"))
        state["units"][UNIT]["status"] = "partial"
        self.write(root, "state.json", state)
        code, out = self.accept(root)
        self.assertEqual(code, 0, out)
        finding = read_json(os.path.join(root, "findings", "F-0001.json"))
        self.assertEqual(finding["severity"], "high")
        self.assertEqual(finding["title"], fix["title"])
        self.assertEqual(os.listdir(os.path.join(root, "findings")), ["F-0001.json"])

    def test_accept_rerun_idempotent(self):
        good, bad = good_finding(), good_finding(title="Second handler problem here", siblings=[])
        root, unit = self.prepared_unit([good, bad], {src(UNIT, good): verdict(), src(UNIT, bad): verdict()})
        code, out = self.accept(root)
        self.assertEqual(code, 1)
        self.assertIn("the gate failed 1 of 2", out)
        self.assertNotIn("decided before", out)
        self.assertEqual(read_json(os.path.join(root, "state.json"))["units"][UNIT]["status"], "pending")
        cands = read_json(os.path.join(root, "candidates", UNIT + ".json"))
        cands[1]["siblings"] = ["searched: os.environ[, 0 more"]
        self.write(root, f"candidates/{UNIT}.json", cands)
        code, out = self.accept(root)
        self.assertEqual(code, 0, out)
        self.assertNotIn("decided before", out)
        self.assertEqual(sorted(os.listdir(os.path.join(root, "findings"))), ["F-0001.json", "F-0002.json"])
        self.assertEqual(read_json(os.path.join(root, "findings", "F-0001.json"))["source"], src(UNIT, good))
        code, out = self.accept(root)
        self.assertEqual(code, 0, out)
        self.assertIn("already done", out)
        self.assertEqual(len(os.listdir(os.path.join(root, "findings"))), 2)

    def test_refused_accept_leaves_no_findings(self):
        good, bad = good_finding(), good_finding(title="Second handler problem here", siblings=[])
        root, unit = self.prepared_unit([good, bad], {src(UNIT, good): verdict(), src(UNIT, bad): verdict()})
        before = read_json(os.path.join(root, "state.json"))["accepted"]
        code, out = self.accept(root)
        self.assertEqual(code, 1)
        self.assertIn("the gate failed 1 of 2", out)
        findings_dir = os.path.join(root, "findings")
        self.assertEqual(os.listdir(findings_dir) if os.path.isdir(findings_dir) else [], [])
        self.assertEqual(read_json(os.path.join(root, "state.json"))["accepted"], before)
        code, out, err = run(root, "status")
        self.assertIn("findings: 0", out + err)
        cands = read_json(os.path.join(root, "candidates", UNIT + ".json"))
        cands[1]["siblings"] = ["searched: os.environ[, 0 more"]
        self.write(root, f"candidates/{UNIT}.json", cands)
        code, out = self.accept(root)
        self.assertEqual(code, 0, out)
        self.assertEqual(sorted(os.listdir(findings_dir)), ["F-0001.json", "F-0002.json"])
        self.assertEqual(read_json(os.path.join(root, "findings", "F-0001.json"))["source"], src(UNIT, good))

    def test_score_counts_only_accepted_findings(self):
        good, bad = good_finding(), good_finding(title="Second handler problem here", siblings=[])
        root, unit = self.prepared_unit([good, bad], {src(UNIT, good): verdict(), src(UNIT, bad): verdict()})
        code, out = self.accept(root)
        self.assertEqual(code, 1, out)
        code, out, err = run(root, "selftest", "--score")
        text = out + err
        self.assertIn("found 0 of", text)
        self.assertIn("invented 0", text)
        self.assertNotIn("invented 1", text)
        code, out, err = run(root, "status")
        self.assertIn("findings: 0", out + err)

    def test_candidate_without_a_repo_is_refused_not_a_crash(self):
        a = good_finding()
        a.pop("repo")
        a["root_cause_verified"] = True
        a["verified_links"] = ["app.py:2", "app.py:3"]
        root, unit = self.prepared_unit([a], {src(UNIT, a): verdict(checked=["app.py:2", "app.py:3"])})
        code, out = self.accept(root)
        self.assertEqual(code, 1, out)
        self.assertNotIn("Traceback", out)
        self.assertIn("repo is empty", out)
        findings_dir = os.path.join(root, "findings")
        self.assertEqual(os.listdir(findings_dir) if os.path.isdir(findings_dir) else [], [])

    def test_crashed_accept_leaves_no_findings(self):
        a = good_finding()
        root, unit = self.prepared_unit([a], {src(UNIT, a): verdict()})
        with mock.patch.object(verdicts, "check_finding", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                verdicts.cmd_accept(argparse.Namespace(root=root, unit=unit, file_accepted_risks=False))
        findings_dir = os.path.join(root, "findings")
        self.assertEqual(os.listdir(findings_dir) if os.path.isdir(findings_dir) else [], [])
        self.assertEqual(read_json(os.path.join(root, "state.json"))["accepted"], {})

    def test_refused_accept_keeps_findings_of_an_earlier_accept(self):
        a, b = good_finding(), good_finding(title="Second handler problem here", siblings=[])
        root, unit = self.prepared_unit([a, b], {src(UNIT, a): verdict(), src(UNIT, b): verdict()})
        self.write(root, "findings/F-0001.json", dict(good_finding(), id="F-0001", source=src(UNIT, a)))
        state = read_json(os.path.join(root, "state.json"))
        state["accepted"][src(UNIT, a)] = "F-0001"
        self.write(root, "state.json", state)
        code, out = self.accept(root)
        self.assertEqual(code, 1, out)
        self.assertEqual(os.listdir(os.path.join(root, "findings")), ["F-0001.json"])
        self.assertEqual(read_json(os.path.join(root, "state.json"))["accepted"], {src(UNIT, a): "F-0001"})

    def test_accept_gives_new_ids_after_existing_findings(self):
        a = good_finding()
        root, unit = self.prepared_unit([a], {src(UNIT, a): verdict()})
        self.write(root, "findings/F-0007.json", good_finding(id="F-0007", title="An older finding of this audit"))
        self.assertEqual(self.accept(root)[0], 0)
        self.assertTrue(os.path.exists(os.path.join(root, "findings", "F-0008.json")))

    def test_accept_with_every_candidate_rejected_marks_the_unit_done(self):
        a = good_finding()
        root, unit = self.prepared_unit([a], {src(UNIT, a): verdict("reject")})
        code, out = self.accept(root)
        self.assertEqual(code, 0, out)
        state = read_json(os.path.join(root, "state.json"))
        self.assertEqual(state["units"][UNIT]["status"], "done")
        self.assertEqual(state["units"][UNIT]["reason"], "0 accepted, 1 rejected")

    def test_accept_marks_the_coverage_ledger(self):
        a = good_finding()
        root, unit = self.prepared_unit([a], {src(UNIT, a): verdict()})
        self.accept(root)
        entry = read_json(os.path.join(root, "coverage.json"))["files"]["svc/app.py"]
        self.assertEqual(entry["status"], "done")
        self.assertRegex(entry["sha256"], r"^[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()
