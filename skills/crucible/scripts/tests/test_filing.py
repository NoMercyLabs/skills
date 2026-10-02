import json
import os
from unittest import mock

from cruciblelib.common import CrucibleError, Root
from cruciblelib.filing import POINTER_BODY, POINTER_TITLE, build_plan, recheck_visibility
from cruciblelib.permissions import GROUPS
from cruciblelib.trackers import github
from cruciblelib.trackers.base import text_digest

from .helpers import CrucibleCase, good_finding, run

FILES = {"app.py": "import os\nTOKEN_PATH = os.environ['X']\n"}
PUBLIC_TITLE = "Handler reads its token path unchecked"
PRIVATE_TITLE = "Admin endpoint skips the authorization check"
PRIVATE_SUMMARY = "Any caller reaches the admin route without a login."


class FakeGh:
    """A stand-in for the gh command: keeps repos, boards, issues and advisories in memory."""

    def __init__(self):
        self.repos = {"acme/svc": "PUBLIC", "acme/priv": "PRIVATE"}
        self.boards = {}
        self.issues, self.advisories, self.labels, self.board_items, self.calls = {}, {}, [], [], []

    def __call__(self, args, stdin=None):
        self.calls.append(list(args))
        head = args[:2]
        if head == ["repo", "view"]:
            return self.repos[args[2]] + "\n"
        if head == ["project", "view"]:
            return json.dumps({"public": self.boards[(args[args.index("--owner") + 1], args[2])] == "public"})
        if head == ["label", "create"]:
            self.labels.append((args[args.index("--repo") + 1], args[2]))
            return ""
        if head == ["issue", "create"]:
            url = f"fake-issue-{len(self.issues) + 1}"
            self.issues[url] = {"repo": args[args.index("--repo") + 1], "title": args[args.index("--title") + 1],
                                "body": args[args.index("--body") + 1]}
            return "noise line\n" + url + "\n"
        if head == ["issue", "view"]:
            item = self.issues[args[2]]
            return json.dumps({"title": item["title"], "body": item["body"]})
        if head == ["project", "item-add"]:
            self.board_items.append((args[2], args[args.index("--url") + 1]))
            return ""
        if args[0] == "api" and "-X" in args:
            payload = json.loads(stdin)
            ghsa = f"GHSA-{len(self.advisories) + 1}"
            self.advisories[ghsa] = {"repo": args[3].split("/security")[0][len("repos/"):],
                                     "summary": payload["summary"], "description": payload["description"]}
            return json.dumps({"ghsa_id": ghsa})
        if args[0] == "api":
            item = self.advisories[args[1].rsplit("/", 1)[1]]
            return json.dumps({"summary": item["summary"], "description": item["description"]})
        if head == ["auth", "status"]:
            return "Token scopes: 'repo', 'read:org'\n"
        raise AssertionError(f"unexpected gh call {args}")

    def created(self):
        return [c for c in self.calls if c[:2] == ["issue", "create"] or (c[0] == "api" and "-X" in c)]


class FilingCase(CrucibleCase):
    def setUp(self):
        self.gh = FakeGh()
        patcher = mock.patch.object(github, "run_gh", self.gh)
        patcher.start()
        self.addCleanup(patcher.stop)

    def finding(self, number, title=PUBLIC_TITLE, visibility="public", **over):
        f = good_finding(title, id=f"F-{number:04d}", visibility=visibility, **over)
        return f

    def ready(self, findings, auto="false", confirmed=None, flags=None, destination='{"kind": "local_report"}',
              grants=None, tracker=None, owners=None, confirm=True):
        root, repo = self.make_root(FILES, confirm=False)
        cfg = Root(root).config()
        cfg["repos"][0]["remote"] = "git@host.test:acme/svc.git"
        cfg["tracker"] = tracker or {"kind": "github-issues", "owner": "acme", "repo": "svc", "project_number": 0,
                                     "fields": {}}
        cfg["owners"] = owners or {}
        Root(root).save_config(cfg)
        self.assertEqual(run(root, "answer", "auto_file", auto, "--words", "test")[0], 0)
        self.assertEqual(run(root, "answer", "blocker_fixes", '{"mode": "never"}', "--words", "test")[0], 0)
        for flag, value in {"pointers": "false", "public_board_items": "false", "collaborators_see_security": "true",
                            **(flags or {})}.items():
            self.assertEqual(run(root, "answer", f"visibility.{flag}", value, "--words", "test")[0], 0)
        if destination:
            self.assertEqual(run(root, "answer", "private_destination", destination, "--words", "test")[0], 0)
        for slug, value in {"acme/svc": "public", **(confirmed or {})}.items():
            code, out, err = run(root, "visibility", "confirm", slug, value, "--words", "the user said so")
            self.assertEqual(code, 0, err)
        defaults = {"tracker_issues": ["repos=acme/svc,acme/priv", "max_count=10"],
                    "tracker_advisories": ["repos=acme/svc", "max_count=5"],
                    "tracker_labels": ["repos=acme/svc,acme/priv", "labels=bug"],
                    "tracker_board": ["repos=acme/svc", "max_count=5"]}
        defaults.update(grants or {})
        for group in GROUPS:
            if defaults.get(group) is not None:
                bounds = [x for item in defaults[group] for x in ("--bound", item)]
                self.assertEqual(run(root, "grant", group, "yes", "--words", "yes", *bounds)[0], 0)
            else:
                self.assertEqual(run(root, "grant", group, "no", "--words", "no")[0], 0)
        for f in findings:
            self.write(root, f"findings/{f['id']}.json", f)
        if confirm:
            code, out, err = run(root, "confirm")
            self.assertEqual(code, 0, err)
        return root

    def dry_run_hash(self, root):
        code, out, err = run(root, "file", "--dry-run")
        self.assertEqual(code, 0, err)
        return [ln for ln in out.splitlines() if ln.startswith("plan hash: ")][0].split(": ")[1]

    def filed_everything(self, root):
        digest = self.dry_run_hash(root)
        if Root(root).config()["auto_file"] is not True:
            self.assertEqual(run(root, "approve", digest)[0], 0)
        code, out, err = run(root, "file", "--apply")
        self.assertEqual(code, 0, out + err)
        return digest

    def log_rows(self, root):
        with open(os.path.join(root, "actions.log"), encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]


class DryRunApplyTests(FilingCase):
    def test_file_dry_run_records_the_hash_and_writes_nothing(self):
        root = self.ready([self.finding(1)])
        digest = self.dry_run_hash(root)
        with open(os.path.join(root, "dryruns.json"), encoding="utf-8") as fh:
            self.assertEqual([r["hash"] for r in json.load(fh)], [digest])
        self.assertEqual(self.gh.created(), [])
        self.assertFalse(os.path.exists(os.path.join(root, "actions.log")))

    def test_apply_needs_dry_run(self):
        root = self.ready([self.finding(1)], auto="true")
        code, out, err = run(root, "file", "--apply")
        self.assertEqual(code, 1)
        self.assertIn("no dry run of this exact plan", err)
        self.assertEqual(self.gh.created(), [])

    def test_apply_refuses_a_plan_changed_since_the_dry_run(self):
        root = self.ready([self.finding(1)], auto="true")
        self.dry_run_hash(root)
        self.write(root, "findings/F-0002.json", self.finding(2, title="Second handler also reads it unchecked"))
        code, out, err = run(root, "file", "--apply")
        self.assertEqual(code, 1)
        self.assertIn("changed since the dry run", err)
        self.assertEqual(self.gh.created(), [])

    def test_apply_needs_the_users_approval_when_auto_file_is_off(self):
        root = self.ready([self.finding(1)], auto="false")
        self.dry_run_hash(root)
        code, out, err = run(root, "file", "--apply")
        self.assertEqual(code, 1)
        self.assertIn("not approved", err)
        self.assertEqual(self.gh.created(), [])

    def test_auto_file_applies_the_dry_run_plan_without_approval(self):
        root = self.ready([self.finding(1)], auto="true")
        self.dry_run_hash(root)
        code, out, err = run(root, "file", "--apply")
        self.assertEqual(code, 0, err)
        self.assertEqual(len(self.gh.issues), 1)
        self.assertFalse(os.path.exists(os.path.join(root, "approvals.json")))

    def test_every_filing_write_is_logged(self):
        root = self.ready([self.finding(1, labels=["bug"])])
        self.filed_everything(root)
        rows = self.log_rows(root)
        self.assertEqual([(r["group"], r["status"]) for r in rows],
                         [("tracker_labels", "ok"), ("tracker_issues", "ok")])
        self.assertIn("acme/svc", rows[1]["command"])

    def test_apply_is_refused_before_the_first_write_when_the_plan_is_over_the_grant(self):
        root = self.ready([self.finding(1), self.finding(2, title="Second handler also reads it unchecked")],
                          auto="true", grants={"tracker_issues": ["repos=acme/svc", "max_count=1"]})
        self.dry_run_hash(root)
        code, out, err = run(root, "file", "--apply")
        self.assertEqual(code, 1)
        self.assertIn("over the granted max_count", err)
        self.assertEqual(self.gh.created(), [])

    def test_apply_without_the_issue_grant_is_refused(self):
        root = self.ready([self.finding(1)], auto="true", grants={"tracker_issues": None})
        self.dry_run_hash(root)
        code, out, err = run(root, "file", "--apply")
        self.assertEqual(code, 1)
        self.assertIn("the user answered no", err)
        self.assertEqual(self.gh.created(), [])
        self.assertEqual(self.log_rows(root)[-1]["status"], "refused")

    def test_a_label_outside_the_grant_is_refused(self):
        root = self.ready([self.finding(1, labels=["wontfix"])], auto="true")
        self.dry_run_hash(root)
        code, out, err = run(root, "file", "--apply")
        self.assertEqual(code, 1)
        self.assertIn("labels wontfix not granted", err)
        self.assertEqual(self.gh.created(), [])

    def test_a_second_apply_files_nothing_again(self):
        root = self.ready([self.finding(1)], auto="true")
        self.filed_everything(root)
        code, out, err = run(root, "file", "--apply")
        self.assertEqual(code, 0, err)
        self.assertEqual(len(self.gh.issues), 1)
        self.assertIn("0 writes done, 1 already filed", out)

    def test_the_markdown_adapter_writes_a_file_per_finding(self):
        root = self.ready([self.finding(1), self.finding(2, title="Second handler also reads it unchecked")],
                          tracker={"kind": "markdown", "owner": "", "repo": "", "project_number": 0, "fields": {}},
                          grants={"tracker_issues": None})
        self.filed_everything(root)
        folder = os.path.join(root, "report", "filed")
        self.assertEqual(sorted(os.listdir(folder)), ["markdown-local-F-0001.md", "markdown-local-F-0002.md"])
        text = self.read_text(os.path.join(folder, "markdown-local-F-0001.md"))
        self.assertTrue(text.startswith(PUBLIC_TITLE + "\n\n## Summary"))
        self.assertEqual(self.gh.calls, [])
        self.assertEqual([r["status"] for r in self.log_rows(root)], ["ok", "ok"])

    def test_the_gh_command_is_called_only_by_the_github_adapter(self):
        folder = os.path.join(os.path.dirname(github.__file__), "..")
        for name in sorted(os.listdir(folder)):
            path = os.path.join(folder, name)
            if name.endswith(".py"):
                text = self.read_text(path)
                self.assertNotIn('["gh"', text, name)

    def test_github_scopes_are_checked_by_output_and_the_fix_is_left_to_the_user(self):
        self.assertEqual(github.missing_scopes("Token scopes: 'repo', 'read:org'", ("repo", "project")), ["project"])
        self.assertEqual(github.refresh_hint(["project"]), "gh auth refresh -s project")
        self.assertEqual(github.missing_scopes("no scope line", ("repo",)), [])
        with self.assertRaises(CrucibleError) as ctx:
            github.GitHub().check_scopes("board")
        self.assertIn("gh auth refresh -s project", str(ctx.exception))
        self.assertEqual([c for c in self.gh.calls if c[0] == "auth"], [["auth", "status"]] * 1)


class VerifyTests(FilingCase):
    def test_verify_passes_after_apply(self):
        root = self.ready([self.finding(1)], auto="true")
        self.filed_everything(root)
        code, out, err = run(root, "file", "--verify")
        self.assertEqual(code, 0, out + err)
        self.assertIn("VERIFY PASS: 1 filed items", out)

    def test_verify_catches_text_changed_after_the_write(self):
        root = self.ready([self.finding(1)], auto="true")
        self.filed_everything(root)
        for item in self.gh.issues.values():
            item["body"] += "\nedited later"
        code, out, err = run(root, "file", "--verify")
        self.assertEqual(code, 1)
        self.assertIn("VERIFY FAIL", out)
        self.assertIn("changed since it was written", out)

    def test_verify_needs_something_filed(self):
        root = self.ready([self.finding(1)], auto="true")
        self.assertEqual(run(root, "file", "--verify")[0], 1)

    def test_report_counts_filed_items_per_visibility_and_destination(self):
        root = self.ready([self.finding(1), self.finding(2, title=PRIVATE_TITLE, visibility="private")],
                          auto="true")
        self.filed_everything(root)
        code, out, err = run(root, "report")
        self.assertEqual(code, 0, err)
        self.assertIn("filed by visibility: private 1, public 1", out)
        self.assertIn("filed by destination: acme/svc 1, local 1", out)
