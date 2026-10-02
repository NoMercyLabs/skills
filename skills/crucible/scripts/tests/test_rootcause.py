import copy
import os
import subprocess

from .helpers import CrucibleCase, good_finding, run

FILES = {"app.py": "import os\nTOKEN_PATH = os.environ['X']\nrun(query)\n"}


def git(path, *args):
    subprocess.run(["git", "-C", path, "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
                   check=True, capture_output=True, text=True)


class RootCauseCase(CrucibleCase):
    def gate(self, finding, root=None):
        root = root or self.make_inventoried(FILES)
        folder = self.tmp()
        self.write(folder, "F.json", finding)
        code, out, err = run(root, "gate", os.path.join(folder, "F.json"))
        return code, out + err

    def test_good_finding_passes_with_chain(self):
        code, out = self.gate(good_finding())
        self.assertEqual(code, 0, out)

    def test_why_restating_what_refused(self):
        finding = good_finding()
        finding["why"]["cause"] = "The token path is read without a default and KeyError at start"
        code, out = self.gate(finding)
        self.assertEqual(code, 1, out)
        self.assertIn("why.cause restates what", out)
        same = good_finding()
        same["chain"]["root_cause"]["ref"] = same["chain"]["symptom"]["ref"]
        code, out = self.gate(same)
        self.assertEqual(code, 1, out)
        self.assertIn("is at the symptom's own file:line", out)

    def test_causal_chain_needs_evidence_per_link(self):
        missing = good_finding()
        del missing["chain"]["mechanism"][0]["evidence"]
        code, out = self.gate(missing)
        self.assertEqual(code, 1, out)
        self.assertIn("chain.mechanism[0].evidence", out)
        fake = good_finding()
        fake["chain"]["root_cause"]["evidence"]["quote"] = "TOKEN_PATH = something that is not there"
        code, out = self.gate(fake)
        self.assertEqual(code, 1, out)
        self.assertIn("chain.root_cause.evidence", out)
        none = good_finding()
        del none["chain"]
        code, out = self.gate(none)
        self.assertEqual(code, 1, out)
        self.assertIn("chain is missing", out)
        explore_only = good_finding()
        explore_only["chain"]["mechanism"][0]["evidence"] = {"kind": "explore", "ref": "app.py:3",
                                                            "quote": "callers: none"}
        explore_only["exploration"]["runs"] = ["app.py:2"]
        code, out = self.gate(explore_only)
        self.assertEqual(code, 1, out)
        self.assertIn("names an explore run that is not in exploration.runs", out)

    def test_root_cause_verified_needs_every_link_reopened(self):
        finding = good_finding(root_cause_verified=True)
        finding["not_checked"] = []
        code, out = self.gate(finding)
        self.assertEqual(code, 1, out)
        self.assertIn("root_cause_verified is true", out)
        finding["verified_links"] = ["app.py:3", "app.py:2"]
        code, out = self.gate(finding)
        self.assertEqual(code, 0, out)
        finding["verified_links"] = ["app.py:2"]
        code, out = self.gate(finding)
        self.assertEqual(code, 1, out)

    def test_verdict_must_list_every_link_for_a_verified_root_cause(self):
        verified = good_finding(root_cause_verified=True)
        verified["not_checked"] = []
        verified["verified_links"] = ["app.py:3", "app.py:2"]
        from .helpers import verdict, src
        for checked, expect in ((["app.py:2"], 1), (["app.py:3", "app.py:2"], 0)):
            root, unit = self.prepared_unit([copy.deepcopy(verified)])
            cand = root and self.read(root, f"candidates/{unit}.json")[0]
            self.write(root, f"review/verdicts-{unit}.json", {src(unit, cand): verdict(checked=checked)})
            code, out, err = run(root, "accept", unit)
            self.assertEqual(code, expect, out + err)

    def test_exploration_record_required(self):
        none = good_finding()
        del none["exploration"]
        code, out = self.gate(none)
        self.assertEqual(code, 1, out)
        self.assertIn("exploration is missing", out)
        no_runs = good_finding()
        no_runs["exploration"]["runs"] = []
        code, out = self.gate(no_runs)
        self.assertEqual(code, 1, out)
        self.assertIn("exploration.runs", out)
        no_reason = good_finding()
        no_reason["exploration"]["not_followed"] = [{"item": "the deploy script"}]
        code, out = self.gate(no_reason)
        self.assertEqual(code, 1, out)
        self.assertIn("exploration.not_followed[0].reason", out)
        no_siblings = good_finding()
        no_siblings["siblings"] = []
        code, out = self.gate(no_siblings)
        self.assertEqual(code, 1, out)
        self.assertIn("siblings", out)

    def test_shared_root_cause_grouped(self):
        from cruciblelib.rootcause import group_by_root_cause
        a = good_finding(title="First symptom of the shared read", id="F-0001")
        b = good_finding(title="Second symptom of the shared read", id="F-0002")
        b["chain"]["symptom"]["ref"] = "app.py:1"
        b["chain"]["root_cause"]["ref"] = "app.py:2-2"
        c = good_finding(title="Unrelated cause somewhere else", id="F-0003")
        c["chain"]["root_cause"]["ref"] = "app.py:3"
        d = good_finding(title="Same line number in another repo", id="F-0004", repo="other")
        groups = group_by_root_cause({f["id"]: f for f in (a, b, c, d)})
        sets = sorted(sorted(g["findings"]) for g in groups)
        self.assertEqual(sets, [["F-0001", "F-0002"], ["F-0003"], ["F-0004"]])
        shared = next(g for g in groups if len(g["findings"]) == 2)
        self.assertEqual(sorted(shared["symptoms"]), ["app.py:1", "app.py:3"])
        root = self.make_inventoried(FILES)
        for fid, f in (("F-0001", a), ("F-0002", b)):
            f["id"] = fid
            self.write(root, f"findings/{fid}.json", f)
        code, out, err = run(root, "group")
        self.assertEqual(code, 0, err)
        self.assertIn("app.py:2", out)
        self.assertIn("F-0001, F-0002", out)

    def test_prior_symptom_fix_flagged(self):
        root, repo = self.make_root(FILES)
        path = os.path.join(repo, "app.py")
        with open(path, "w", encoding="utf-8", newline=chr(10)) as fh:
            fh.write(FILES["app.py"].replace("['X']", "['Y']"))
        git(repo, "init", "-q")
        git(repo, "add", "--", "app.py")
        git(repo, "commit", "-q", "-m", "feat: add app")
        with open(path, "w", encoding="utf-8", newline=chr(10)) as fh:
            fh.write(FILES["app.py"])
        git(repo, "commit", "-q", "-am", "fix: catch the KeyError at start")
        self.assertEqual(run(root, "inventory")[0], 0)
        code, out = self.gate(good_finding(), root)
        self.assertEqual(code, 1, out)
        self.assertIn("earlier fix", out)
        self.assertIn("fix: catch the KeyError at start", out)
        flagged = good_finding()
        sha = subprocess.run(["git", "-C", repo, "log", "-1", "--format=%h"], capture_output=True, text=True).stdout.strip()
        flagged["prior_fix"] = {"commits": [sha], "treated_symptom": True,
                                "why_back": "it caught the error and left the unchecked read in place"}
        code, out = self.gate(flagged, root)
        self.assertEqual(code, 0, out)

    def test_issue_has_root_cause_and_do_not_fix_by(self):
        from cruciblelib.filing import render_body
        body = render_body(good_finding())
        self.assertIn("## Root cause\n", body)
        self.assertIn("the app stops at start with a KeyError", body)
        self.assertIn("app.py:2", body)
        self.assertIn("## Do not fix by\n", body)
        self.assertIn("a try/except KeyError around the read", body)
        missing = good_finding()
        del missing["do_not_fix_by"]
        code, out = self.gate(missing)
        self.assertEqual(code, 1, out)
        self.assertIn("do_not_fix_by", out)
