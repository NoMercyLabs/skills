import copy
import json
import os
import subprocess

from cruciblelib import board
from cruciblelib.common import Root

from .helpers import CrucibleCase, good_finding, run

FILES = {"app.py": "import os\nTOKEN_PATH = os.environ['X']\nrun(query)\n" + "pass\n" * 60}
BOARD = {"kind": "github-project", "owner": "acme", "repo": "svc", "project_number": 1, "fields": {}}


def finding(fid, cause_line=2, goal=3, verified=True, **over):
    f = copy.deepcopy(good_finding(id=fid, goal=goal, root_cause_verified=verified, **over))
    f["chain"]["root_cause"]["ref"] = f"app.py:{cause_line}"
    f["chain"]["symptom"]["ref"] = f"app.py:{cause_line + 1}"
    return f


def commit_as(repo, name, message):
    env = dict(os.environ, GIT_AUTHOR_NAME=name, GIT_AUTHOR_EMAIL="dev@example.test",
               GIT_COMMITTER_NAME=name, GIT_COMMITTER_EMAIL="dev@example.test")
    for args in (["init", "-q"], ["add", "-A"], ["commit", "-q", "-m", message]):
        subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True, env=env)


class ProposeCase(CrucibleCase):
    def proposed(self, findings, tracker=None, owners=None):
        root = self.make_inventoried(FILES)
        for f in findings:
            self.write(root, f"findings/{f['id']}.json", f)
        self.write(root, "graph.json", {"repos": ["svc"], "edges": []})
        cfg = Root(root).config()
        if tracker:
            cfg["tracker"] = tracker
            cfg["repos"][0]["remote"] = "git@host.test:acme/svc.git"
        cfg["owners"] = owners or {}
        Root(root).save_config(cfg)
        return root

    def propose(self, root):
        code, out, err = run(root, "board", "propose")
        self.assertEqual(code, 0, err)
        return out

    def plan(self, root):
        with open(os.path.join(root, "board", "plan.json"), encoding="utf-8") as fh:
            return json.load(fh)

    def item_owner(self, root, fid="F-001"):
        return self.plan(root)["items"][fid]["owner"]

    def repo_path(self, root):
        return Root(root).config()["repos"][0]["path"]


class ResearchGateTests(ProposeCase):
    def test_board_proposed_after_research(self):
        root = self.proposed([])
        code, out, err = run(root, "board", "propose")
        self.assertEqual(code, 1)
        self.assertIn("no accepted findings", err)
        self.assertFalse(os.path.exists(os.path.join(root, "board", "plan.json")))

        root = self.proposed([finding("F-001", verified=False)])
        code, out, err = run(root, "board", "propose")
        self.assertEqual(code, 1)
        self.assertIn("F-001", err)
        self.assertIn("root cause is not verified", err)

        root = self.proposed([finding("F-001"), finding("F-002")])
        out = self.propose(root)
        self.assertIn("research: 2 findings, every root cause verified, 1 root causes (1 shared", out)
        digest = [ln for ln in out.splitlines() if ln.startswith("plan hash: ")][0].split(": ")[1]
        with open(os.path.join(root, "dryruns.json"), encoding="utf-8") as fh:
            self.assertIn(digest, [row["hash"] for row in json.load(fh)])
        self.assertEqual(self.plan(root)["hash"], digest)

    def test_board_plan_shows_every_field_stage_reason_and_mapping(self):
        root = self.proposed([finding("F-001"), finding("F-002"), finding("F-003", 40, goal=1)])
        out = self.propose(root)
        for field in ("Area", "Stage", "Severity", "Priority", "Size", "Owner"):
            self.assertIn(f"field {field}", out)
        self.assertIn("svc (source: ", out)
        self.assertIn("F-001: blocks 2 findings in svc", out)
        self.assertIn("F-003: goal 1: users can use the product without help", out)

    def test_existing_board_fields_are_mapped_and_only_additions_proposed(self):
        tracker = dict(BOARD, fields={"stage": ["Goal 3: stability"], "Status": ["Todo"]})
        root = self.proposed([finding("F-001", 40)], tracker=tracker)
        self.propose(root)
        fields = {f["name"]: f for f in self.plan(root)["fields"]}
        self.assertEqual(fields["Stage"]["action"], "map")
        self.assertEqual(fields["Stage"]["existing"], "stage")
        self.assertEqual(fields["Stage"]["add_values"], [])
        self.assertEqual(fields["Area"]["action"], "add")
        self.assertNotIn("Status", fields)


class ApprovalTests(ProposeCase):
    def test_board_needs_approved_plan_hash(self):
        root = self.proposed([finding("F-001")], tracker=BOARD)
        code, out, err = run(root, "file", "--apply")
        self.assertEqual(code, 1)
        self.assertIn("board plan", err)
        self.assertIn("board propose", err)

        out = self.propose(root)
        digest = [ln for ln in out.splitlines() if ln.startswith("plan hash: ")][0].split(": ")[1]
        code, out, err = run(root, "file", "--apply")
        self.assertEqual(code, 1)
        self.assertIn("board plan is not approved", err)

        self.assertEqual(run(root, "approve", digest)[0], 0)
        code, out, err = run(root, "file", "--apply")
        self.assertNotIn("board plan", err)

    def test_a_changed_board_plan_needs_a_new_approval(self):
        root = self.proposed([finding("F-001")], tracker=BOARD)
        first = [ln for ln in self.propose(root).splitlines() if ln.startswith("plan hash: ")][0].split(": ")[1]
        self.assertEqual(run(root, "approve", first)[0], 0)
        self.write(root, "findings/F-002.json", finding("F-002", 40, goal=1))
        self.propose(root)
        code, out, err = run(root, "file", "--apply")
        self.assertIn("board plan is not approved", err)

    def test_a_plain_issue_tracker_needs_no_board_plan(self):
        root = self.proposed([finding("F-001")])
        code, out, err = run(root, "file", "--apply")
        self.assertNotIn("board plan", err)


class OwnerTests(ProposeCase):
    def test_owner_never_guessed(self):
        root = self.proposed([finding("F-001", who={"affected": "operators", "owner": "platform team"})])
        self.propose(root)
        item = self.plan(root)["items"]["F-001"]
        self.assertEqual(item["owner"], "unassigned")
        self.assertEqual(item["owner_source"], "none found")

    def test_owner_from_codeowners(self):
        root = self.proposed([finding("F-001")])
        repo = self.repo_path(root)
        os.makedirs(os.path.join(repo, ".github"))
        with open(os.path.join(repo, ".github", "CODEOWNERS"), "w", encoding="utf-8", newline="\n") as fh:
            fh.write("# owners\n* @acme/everyone\n*.py @acme/python-team\n")
        self.propose(root)
        item = self.plan(root)["items"]["F-001"]
        self.assertEqual(item["owner"], "@acme/python-team")
        self.assertEqual(item["owner_source"], ".github/CODEOWNERS")

    def test_owner_from_git_history_of_the_cited_lines(self):
        root = self.proposed([finding("F-001")])
        commit_as(self.repo_path(root), "Ada Dev", "add the app")
        self.propose(root)
        item = self.plan(root)["items"]["F-001"]
        self.assertEqual(item["owner"], "Ada Dev")
        self.assertEqual(item["owner_source"], "git log of app.py:2")

    def test_owner_from_the_users_answer(self):
        root = self.proposed([finding("F-001")], owners={"svc": {"owner": "acme", "assignee": "grace"}})
        self.propose(root)
        item = self.plan(root)["items"]["F-001"]
        self.assertEqual(item["owner"], "grace")
        self.assertEqual(item["owner_source"], "the user's owners answer")


class ViewTests(ProposeCase):
    def view_names(self, root):
        return [v["name"] for v in self.plan(root)["views"]]

    def test_views_follow_the_brief(self):
        root = self.proposed([finding("F-001"), finding("F-002"), finding("F-003", 40, goal=1)])
        out = self.propose(root)
        plan = self.plan(root)
        self.assertEqual(self.view_names(root), ["Start here", "By stage", "By repo", "By owner"])
        start = plan["views"][0]
        self.assertEqual(start["filter"], f"Stage = {plan['stages'][0]['name']}")
        self.assertEqual([v["group_by"] for v in plan["views"][1:]], ["Stage", "Area", "Owner"])
        for name in self.view_names(root):
            self.assertIn(f"view {name}", out)

    def test_security_view_only_on_private_board(self):
        private = self.proposed([finding("F-001")], tracker=BOARD)
        self.assertEqual(run(private, "visibility", "confirm", "board:acme/1", "private", "--words", "test")[0], 0)
        self.propose(private)
        self.assertEqual(self.view_names(private)[-1], "Security")

        public = self.proposed([finding("F-001")], tracker=BOARD)
        self.assertEqual(run(public, "visibility", "confirm", "board:acme/1", "public", "--words", "test")[0], 0)
        self.propose(public)
        self.assertNotIn("Security", self.view_names(public))

        unconfirmed = self.proposed([finding("F-001")], tracker=BOARD)
        self.propose(unconfirmed)
        self.assertNotIn("Security", self.view_names(unconfirmed))


class DatesTests(ProposeCase):
    def test_dates_asked_default_none(self):
        root = self.proposed([finding("F-001")])
        out = self.propose(root)
        self.assertIn(board.DATES_QUESTION, out)
        self.assertEqual(board.DATES_QUESTION,
                         "Put dates on the stages? This needs your team speed; dates from estimates drift.")
        self.assertEqual(self.plan(root)["dates"], "none")
        self.assertNotIn("Target date", [f["name"] for f in self.plan(root)["fields"]])

        self.assertEqual(run(root, "answer", "board_dates", "estimates")[0], 0)
        self.propose(root)
        self.assertEqual(self.plan(root)["dates"], "estimates")
        self.assertIn("Target date", [f["name"] for f in self.plan(root)["fields"]])

        code, out, err = run(root, "answer", "board_dates", "weekly")
        self.assertEqual(code, 1)
        self.assertIn("board_dates is one of: none, estimates", err)
