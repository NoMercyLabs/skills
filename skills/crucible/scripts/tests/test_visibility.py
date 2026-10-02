import json
import os

from cruciblelib.common import Root
from cruciblelib.filing import POINTER_BODY, POINTER_TITLE, build_plan, recheck_visibility
from cruciblelib.trackers import github

from .helpers import CrucibleCase, good_finding, run
from .test_filing import FILES, PRIVATE_SUMMARY, PRIVATE_TITLE, PUBLIC_TITLE, FilingCase

SECOND_TITLE = "Second handler also reads it unchecked"
PRIV_REPO = '{"kind": "private_repo", "repo": "acme/priv"}'
BOARD = {"kind": "github-project", "owner": "acme", "repo": "priv", "project_number": 7, "fields": {}}


class GateCase(CrucibleCase):
    def gate(self, finding):
        root = self.make_inventoried(FILES)
        path = os.path.join(self.tmp(), "F.json")
        self.write(os.path.dirname(path), "F.json", finding)
        code, out, err = run(root, "gate", path)
        return code, out + err


class ConfirmationTests(CrucibleCase):
    def test_repo_visibility_confirmed_by_user(self):
        root, repo = self.make_root(FILES, confirm=False)
        for flag in ("pointers", "public_board_items", "collaborators_see_security"):
            self.assertEqual(run(root, "answer", f"visibility.{flag}", "false", "--words", "t")[0], 0)
        self.assertEqual(run(root, "answer", "private_destination", '{"kind": "local_report"}', "--words", "t")[0], 0)
        self.answer_the_rest(root)
        code, out, err = run(root, "confirm")
        self.assertEqual(code, 1)
        self.assertIn("visibility", err)
        slug = os.path.basename(repo)
        code, out, err = run(root, "visibility", "confirm", slug, "public")
        self.assertEqual(code, 1)
        self.assertIn("--words", err)
        self.assertIn("visibility", err + out)
        code, out, err = run(root, "visibility", "list")
        self.assertIn("not confirmed", out)
        cfg = Root(root).config()
        self.assertIsNone(cfg.get("visibility", {}).get("destinations", {}).get(slug))
        code, out, err = run(root, "visibility", "confirm", slug, "private", "--words", "it is a private repo")
        self.assertEqual(code, 0, err)
        cfg = Root(root).config()
        self.assertEqual(cfg["visibility"]["destinations"][slug]["value"], "private")
        self.assertEqual(cfg["visibility"]["destinations"][slug]["words"], "it is a private repo")
        self.answer_brief(root)
        self.assertEqual(run(root, "confirm")[0], 0)

    def test_private_destination_asked(self):
        root, repo = self.make_root(FILES, confirm=False)
        self.answer_everything_but_destination(root)
        code, out, err = run(root, "confirm")
        self.assertEqual(code, 1)
        self.assertIn("private_destination", err)
        bad = run(root, "answer", "private_destination", '{"kind": "email"}', "--words", "t")
        self.assertEqual(bad[0], 1)
        self.assertEqual(run(root, "answer", "private_destination", '{"kind": "local_report"}', "--words", "t")[0], 0)
        self.answer_brief(root)
        self.assertEqual(run(root, "confirm")[0], 0)

    def answer_everything_but_destination(self, root):
        self.answer_visibility(root, destination=None)
        self.answer_the_rest(root)

    def answer_the_rest(self, root):
        for command in (["answer", "auto_file", "false"], ["answer", "blocker_fixes", '{"mode": "never"}']):
            self.assertEqual(run(root, *command, "--words", "t")[0], 0)
        self.answer_workspace(root)
        self.answer_fable(root)
        from cruciblelib.permissions import GROUPS
        for group in GROUPS:
            self.assertEqual(run(root, "grant", group, "no", "--words", "t")[0], 0)


class FindingRuleTests(GateCase):
    def test_finding_needs_visibility(self):
        finding = good_finding()
        del finding["visibility"]
        code, out = self.gate(finding)
        self.assertEqual(code, 1)
        self.assertIn("visibility must be public or private", out)
        finding["visibility"] = "secret"
        self.assertEqual(self.gate(finding)[0], 1)

    def test_exploitable_finding_forced_private(self):
        code, out = self.gate(good_finding(PRIVATE_TITLE, visibility="public"))
        self.assertEqual(code, 1)
        self.assertIn("visibility must be private: exploitable", out)
        code, out = self.gate(good_finding(PRIVATE_TITLE, visibility="private"))
        self.assertEqual(code, 0, out)
        code, out = self.gate(good_finding("Host 10.4.5.6 is hard coded in the client", visibility="public"))
        self.assertEqual(code, 1)
        self.assertIn("infrastructure", out)


class PlacementTests(FilingCase):
    def private(self, number=2):
        return self.finding(number, title=PRIVATE_TITLE, visibility="private", what={
            "summary": PRIVATE_SUMMARY, "observed": "the route answers", "expected": "a refusal"})

    def test_private_never_to_public_destination(self):
        root = self.ready([self.private()], auto="true")
        self.filed_everything(root)
        self.assertEqual(self.gh.issues, {})
        self.assertEqual(self.gh.advisories, {})
        self.assertEqual([a["destination"] for a in build_plan(Root(root))], ["local"])
        root = self.ready([self.private()], auto="true", destination=PRIV_REPO,
                          confirmed={"acme/priv": "private"})
        self.filed_everything(root)
        self.assertEqual([i["repo"] for i in self.gh.issues.values()], ["acme/priv"])
        action = {"kind": "issue", "key": "k", "target": "acme/svc", "visibility": "private", "board": ""}
        cfg = Root(root).config()
        from cruciblelib.common import CrucibleError
        with self.assertRaises(CrucibleError):
            recheck_visibility(Root(root), cfg, github.GitHub(), action)

    def test_private_never_on_public_board(self):
        self.gh.boards[("acme", "7")] = "public"
        root = self.ready([self.private(), self.finding(1)], auto="true", tracker=BOARD,
                          flags={"public_board_items": "true"},
                          confirmed={"acme/priv": "private", "board:acme/7": "public"},
                          grants={"tracker_issues": ["repos=acme/svc,acme/priv", "max_count=10"],
                                  "tracker_board": ["repos=acme/priv", "max_count=5"]})
        plan = build_plan(Root(root))
        by_finding = {a["finding"]: a for a in plan}
        self.assertEqual(by_finding["F-0002"]["board"], "")
        action = dict(by_finding["F-0002"], board="board:acme/7")
        from cruciblelib.common import CrucibleError
        with self.assertRaises(CrucibleError) as ctx:
            recheck_visibility(Root(root), Root(root).config(), github.GitHub(), action)
        self.assertIn("never go on a public board", str(ctx.exception))
        self.filed_everything(root)
        urls = [u for _, u in self.gh.board_items]
        self.assertTrue(urls)
        for url in urls:
            self.assertNotIn(PRIVATE_TITLE, self.gh.issues[url]["title"])

    def test_public_pointer_has_no_detail(self):
        root = self.ready([self.private()], auto="true", destination=PRIV_REPO, flags={"pointers": "true"},
                          confirmed={"acme/priv": "private"})
        self.filed_everything(root)
        public = [i for i in self.gh.issues.values() if i["repo"] == "acme/svc"]
        self.assertEqual(len(public), 1)
        self.assertEqual(public[0]["title"], POINTER_TITLE)
        self.assertEqual(public[0]["body"], POINTER_BODY)
        for text in (PRIVATE_TITLE, PRIVATE_SUMMARY, "app.py"):
            self.assertNotIn(text, public[0]["title"] + public[0]["body"])
        private = [i for i in self.gh.issues.values() if i["repo"] == "acme/priv"]
        self.assertEqual([i["title"] for i in private], [PRIVATE_TITLE])

    def test_visibility_rechecked_before_write(self):
        root = self.ready([self.private()], auto="true", destination=PRIV_REPO, confirmed={"acme/priv": "private"})
        self.dry_run_hash(root)
        self.gh.repos["acme/priv"] = "PUBLIC"
        code, out, err = run(root, "file", "--apply")
        self.assertEqual(code, 1, out)
        self.assertIn("now public", err)
        self.assertEqual(self.gh.created(), [])

    def test_verify_catches_private_text_in_public(self):
        root = self.ready([self.finding(1), self.private()], auto="true")
        self.filed_everything(root)
        for item in self.gh.issues.values():
            item["body"] += "\n" + PRIVATE_TITLE
        code, out, err = run(root, "file", "--verify")
        self.assertEqual(code, 1)
        self.assertIn("text of private finding F-0002 is in a public place", out)
        self.assertNotIn(json.dumps(PRIVATE_SUMMARY), err)
