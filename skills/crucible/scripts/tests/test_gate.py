import os
import unittest

from .helpers import CrucibleCase, good_finding, run

FILES = {"app.py": "import os\nTOKEN_PATH = os.environ['X']\nrun(query)\n"}


class GateTests(CrucibleCase):
    def gate(self, finding, config=None, extra=()):
        root = self.make_inventoried(FILES, config=config)
        path = os.path.join(self.tmp(), "F.json")
        self.write(os.path.dirname(path), "F.json", finding)
        code, out, err = run(root, "gate", path, *extra)
        return code, out + err

    def test_gate_passes_a_complete_finding(self):
        code, out = self.gate(good_finding())
        self.assertEqual(code, 0, out)
        self.assertIn("PASS", out)

    def test_gate_placeholder_refused(self):
        for text in ("TBD", "?", "n/a", "...", "-", "todo", "same as above"):
            finding = good_finding()
            finding["what"]["observed"] = text
            code, out = self.gate(finding)
            self.assertEqual(code, 1, text)
            self.assertIn("placeholder", out)

    def test_gate_allows_not_checked_text(self):
        finding = good_finding()
        finding["how"]["prove"] = "not checked"
        code, out = self.gate(finding)
        self.assertEqual(code, 0, out)

    def test_gate_refuses_an_empty_field(self):
        finding = good_finding()
        finding["who"]["owner"] = "  "
        code, out = self.gate(finding)
        self.assertEqual(code, 1)
        self.assertIn("who.owner is empty", out)

    def test_gate_refuses_a_missing_group(self):
        finding = good_finding()
        del finding["how"]
        code, out = self.gate(finding)
        self.assertEqual(code, 1)
        self.assertIn("how is missing", out)

    def test_gate_refuses_a_goal_that_is_not_in_the_config(self):
        code, out = self.gate(good_finding(goal=99))
        self.assertEqual(code, 1)
        self.assertIn("goal", out)

    def test_gate_refuses_a_short_title(self):
        code, out = self.gate(good_finding(title="short"))
        self.assertEqual(code, 1)
        self.assertIn("title", out)

    def test_gate_refuses_a_stage_that_is_not_in_the_config(self):
        code, out = self.gate(good_finding(stage="launch"), config={"stages": ["alpha"]})
        self.assertEqual(code, 1)
        self.assertIn("stage", out)

    def test_gate_refuses_a_quote_that_is_not_at_the_cited_line(self):
        finding = good_finding()
        finding["evidence"][0]["quote"] = "this text is nowhere"
        code, out = self.gate(finding)
        self.assertEqual(code, 1)
        self.assertIn("quote is not at app.py:2", out)

    def test_gate_refuses_an_evidence_line_past_the_end_of_the_file(self):
        finding = good_finding()
        finding["evidence"][0]["ref"] = "app.py:40"
        code, out = self.gate(finding)
        self.assertEqual(code, 1)
        self.assertIn("past the end", out)

    def test_gate_accepts_a_line_range_and_whitespace_differences(self):
        finding = good_finding()
        finding["evidence"][0] = {"kind": "file_line", "ref": "app.py:2-3",
                                  "quote": "TOKEN_PATH   =   os.environ['X']\nrun(query)"}
        code, out = self.gate(finding)
        self.assertEqual(code, 0, out)

    def test_siblings_required(self):
        for value in ([], None, [" "]):
            finding = good_finding(siblings=value)
            code, out = self.gate(finding)
            self.assertEqual(code, 1, value)
            self.assertIn("siblings", out)

    def test_unverified_cause_refused(self):
        unverified = good_finding()
        unverified["why"]["verified"] = False
        code, out = self.gate(unverified)
        self.assertEqual(code, 1)
        self.assertIn("cause:", out)
        unverified["not_checked"] += ["cause: the deploy script may set X"]
        code, out = self.gate(unverified)
        self.assertEqual(code, 0, out)

    def test_unverified_cause_refused_when_verified_has_no_evidence(self):
        finding = good_finding()
        finding["evidence"] = [{"kind": "command", "ref": "grep -n X app.py", "quote": "2:TOKEN_PATH"}]
        code, out = self.gate(finding)
        self.assertEqual(code, 1)
        self.assertIn("why.verified is true but no file_line evidence", out)

    def test_privacy_word_refused(self):
        finding = good_finding()
        finding["what"]["summary"] = "Reported by Casey from the Orchard team."
        code, out = self.gate(finding, config={"privacy_words": ["casey"]})
        self.assertEqual(code, 1)
        self.assertIn("what.summary holds a privacy word", out)
        self.assertNotIn("Casey", out)

    def test_privacy_word_is_checked_in_evidence_and_lists(self):
        finding = good_finding()
        finding["siblings"] = ["host build-7.internal.example"]
        code, out = self.gate(finding, config={"privacy_words": ["internal.example"]})
        self.assertEqual(code, 1)
        self.assertIn("siblings[0]", out)

    def test_privacy_word_matches_whole_words_only(self):
        finding = good_finding()
        finding["what"]["summary"] = "The caseyboard widget is slow."
        code, out = self.gate(finding, config={"privacy_words": ["casey"]})
        self.assertEqual(code, 0, out)

    def test_key_like_refused(self):
        samples = ["a" * 32, "0123456789abcdef" * 4, "sk-" + "A1b2C3d4" * 3, "ghp_" + "a1B2" * 8,
                   "AKIA" + "ABCDEFGH12345678", "-----BEGIN RSA PRIVATE KEY-----",
                   "Zm9vYmFyMTIzNDU2Nzg5MEFCQ0RFRkdISUpLTE1OT1BRUlNUVVZXWFla"]
        for sample in samples:
            finding = good_finding()
            finding["what"]["observed"] = "the config holds " + sample
            code, out = self.gate(finding)
            self.assertEqual(code, 1, sample)
            self.assertIn("key-like", out, sample)

    def test_key_like_masked_line_is_accepted(self):
        finding = good_finding()
        finding["what"]["observed"] = "the config holds\n<token, masked>"
        finding["evidence"][0]["quote"] = "TOKEN_PATH = os.environ['X']\n<token, masked>"
        code, out = self.gate(finding)
        self.assertEqual(code, 0, out)

    def test_key_like_allows_git_shas_and_long_paths(self):
        finding = good_finding()
        finding["before_you_fix"] = {"current_behaviour": "reads X", "callers": "main",
                                     "consumers": "none", "earlier_fixes": "fixed in " + "a" * 40,
                                     "instances": "not checked"}
        finding["where"][0]["ref"] = "src/components/deeply/nested/folder/structure/with/long/names/handler.py"
        code, out = self.gate(finding)
        self.assertEqual(code, 0, out)

    def test_gate_default_checks_every_finding_and_fails_on_one_bad(self):
        root = self.make_inventoried(FILES)
        self.write(root, "findings/F-0001.json", good_finding(id="F-0001"))
        code, out, err = run(root, "gate")
        self.assertEqual(code, 0, out + err)
        self.write(root, "findings/F-0002.json", good_finding(id="F-0002", siblings=[]))
        code, out, err = run(root, "gate")
        self.assertEqual(code, 1)
        self.assertIn("PASS F-0001", out)
        self.assertIn("FAIL F-0002", out)

    def test_gate_candidates_flag_checks_candidates(self):
        root = self.make_inventoried(FILES)
        self.write(root, "candidates/svc-u01.json", [good_finding(), good_finding(title="A second handler problem", siblings=[])])
        code, out, err = run(root, "gate", "--candidates")
        self.assertEqual(code, 1)
        self.assertIn("PASS svc-u01[0]", out)
        self.assertIn("FAIL svc-u01[1]", out)

    def test_gate_refused_until_config_is_confirmed(self):
        root, repo = self.make_root(FILES, confirm=False)
        code, out, err = run(root, "gate")
        self.assertEqual(code, 1)
        self.assertIn("config not confirmed", err)


if __name__ == "__main__":
    unittest.main()
