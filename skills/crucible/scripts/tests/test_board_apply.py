import glob
import json
import os
from unittest import mock

from cruciblelib.common import Root
from cruciblelib.trackers import github

from .helpers import run
from .test_board_propose import finding
from .test_filing import FakeGh, FilingCase

BOARD = {"kind": "github-project", "owner": "acme", "repo": "svc", "project_number": 1, "fields": {}}
WRITES = (["project", "field-create"], ["project", "item-add"], ["project", "item-edit"], ["issue", "create"])


def camel(name):
    first, *rest = name.split()
    return first.lower() + "".join(w.capitalize() for w in rest)


class BoardGh(FakeGh):
    """FakeGh plus a Projects v2 board with canned JSON: fields, items, edits."""

    def __init__(self, fields=None, backups=None):
        super().__init__()
        self.boards[("acme", "1")] = "private"
        self.fields = fields if fields is not None else [
            {"id": "F-title", "name": "Title", "type": "ProjectV2Field"},
            {"id": "F-status", "name": "Status", "type": "ProjectV2SingleSelectField",
             "options": [{"id": "O-todo", "name": "Todo"}, {"id": "O-done", "name": "Done"}]}]
        self.items = []
        self.backups = backups or (lambda: [])
        self.backups_at_create = []

    def __call__(self, args, stdin=None):
        head = args[:2]
        if head == ["project", "view"]:
            self.calls.append(list(args))
            return json.dumps({"id": "PVT_1", "public": False})
        if head == ["project", "field-list"]:
            self.calls.append(list(args))
            return json.dumps({"fields": self.fields, "totalCount": len(self.fields)})
        if head == ["project", "field-create"]:
            self.calls.append(list(args))
            self.backups_at_create.append(self.backups())
            name = args[args.index("--name") + 1]
            options = args[args.index("--single-select-options") + 1].split(",") \
                if "--single-select-options" in args else None
            field = {"id": f"F-{name}", "name": name, "type": "ProjectV2SingleSelectField" if options else "ProjectV2Field"}
            if options:
                field["options"] = [{"id": f"O-{name}-{o}", "name": o} for o in options]
            self.fields.append(field)
            return json.dumps(field)
        if head == ["project", "item-add"]:
            url = args[args.index("--url") + 1]
            self.items.append({"id": f"PVTI_{len(self.items) + 1}", "content": {"url": url}})
            return super().__call__(args, stdin)
        if head == ["project", "item-list"]:
            self.calls.append(list(args))
            return json.dumps({"items": self.items, "totalCount": len(self.items)})
        if head == ["project", "item-edit"]:
            self.calls.append(list(args))
            field = next(f for f in self.fields if f["id"] == args[args.index("--field-id") + 1])
            option = next(o for o in field["options"] if o["id"] == args[args.index("--single-select-option-id") + 1])
            item = next(i for i in self.items if i["id"] == args[args.index("--id") + 1])
            item[camel(field["name"])] = option["name"]
            return ""
        return super().__call__(args, stdin)

    def writes(self):
        return [c for c in self.calls if c[:2] in WRITES]


class BoardApplyCase(FilingCase):
    def setUp(self):
        self.root_folder = None
        self.gh = BoardGh(backups=lambda: sorted(glob.glob(os.path.join(self.root_folder, "backups", "*"))))
        patcher = mock.patch.object(github, "run_gh", self.gh)
        patcher.start()
        self.addCleanup(patcher.stop)

    def board_ready(self, grants=None):
        findings = [finding("F-001"), finding("F-002")]
        for f in findings:
            f["visibility"] = "public"
        root = self.ready(findings, tracker=dict(BOARD), confirmed={"board:acme/1": "private"}, grants=grants)
        self.root_folder = root
        return root

    def approved_plan(self, root):
        code, out, err = run(root, "board", "propose")
        self.assertEqual(code, 0, err)
        digest = [ln for ln in out.splitlines() if ln.startswith("plan hash: ")][0].split(": ")[1]
        self.assertEqual(run(root, "approve", digest)[0], 0)
        with open(os.path.join(root, "board", "plan.json"), encoding="utf-8") as fh:
            return json.load(fh)

    def applied_board(self, root):
        plan = self.approved_plan(root)
        code, out, err = run(root, "board", "apply")
        self.assertEqual(code, 0, out + err)
        digest = self.dry_run_hash(root)
        self.assertEqual(run(root, "approve", digest)[0], 0)
        code, out, err = run(root, "file", "--apply")
        self.assertEqual(code, 0, out + err)
        return plan, out


class BoardApplyTests(BoardApplyCase):
    def test_existing_board_fields_kept_and_backed_up(self):
        root = self.board_ready()
        self.gh.fields.append({"id": "F-Stage", "name": "stage", "type": "ProjectV2SingleSelectField",
                               "options": [{"id": "O-s1", "name": "Goal 1"}]})
        self.approved_plan(root)
        code, out, err = run(root, "board", "apply")
        self.assertEqual(code, 0, out + err)
        created = [c[c.index("--name") + 1] for c in self.gh.calls if c[:2] == ["project", "field-create"]]
        self.assertEqual(sorted(created), ["Area", "Owner", "Priority", "Severity", "Size"])
        self.assertTrue(self.gh.backups_at_create and all(self.gh.backups_at_create),
                        "a backup file must exist before every create call")
        backup_file = self.gh.backups_at_create[0][0]
        with open(backup_file, encoding="utf-8") as fh:
            saved = json.load(fh)
        self.assertEqual({f["name"] for f in saved["fields"]}, {"Title", "Status", "stage"})
        self.assertIn("items", saved)
        self.assertIn(backup_file, [r["result"] for r in self.log_rows(root) if r["group"] == "backups"])
        self.assertIn("view not created: gh has no command", out)
        self.assertIn("Start here", out)

    def test_item_fields_set_on_apply(self):
        root = self.board_ready()
        plan, out = self.applied_board(root)
        edits = [c for c in self.gh.calls if c[:2] == ["project", "item-edit"]]
        self.assertEqual(len(edits), 12, "6 fields on each of 2 items")
        for fid, number in (("F-001", 1), ("F-002", 2)):
            item = self.gh.items[number - 1]
            want = plan["items"][fid]
            for name, key in (("Area", "area"), ("Stage", "stage"), ("Severity", "severity"),
                              ("Priority", "priority"), ("Size", "size"), ("Owner", "owner")):
                self.assertEqual(item[camel(name)], str(want[key]), f"{fid} {name}")
        for call in edits:
            self.assertEqual(call[call.index("--project-id") + 1], "PVT_1")
        rows = [r for r in self.log_rows(root) if r["group"] == "tracker_board" and r["command"].startswith("set ")]
        self.assertEqual(len(rows), 12)
        self.assertTrue(all(r["status"] == "ok" for r in rows))

    def test_verify_reads_item_fields_back(self):
        root = self.board_ready()
        self.applied_board(root)
        code, out, err = run(root, "file", "--verify")
        self.assertEqual(code, 0, out + err)
        self.gh.items[0]["stage"] = "Somewhere else"
        code, out, err = run(root, "file", "--verify")
        self.assertEqual(code, 1)
        self.assertIn("VERIFY FAIL", out)
        self.assertIn("Stage", out)
        self.assertIn("Somewhere else", out)

    def test_field_write_needs_grant(self):
        root = self.board_ready(grants={"tracker_board": None})
        self.approved_plan(root)
        code, out, err = run(root, "board", "apply")
        self.assertEqual(code, 1)
        self.assertIn("refused", err)
        self.assertEqual(self.gh.writes(), [])
        digest = self.dry_run_hash(root)
        self.assertEqual(run(root, "approve", digest)[0], 0)
        code, out, err = run(root, "file", "--apply")
        self.assertEqual(code, 1)
        self.assertEqual(self.gh.writes(), [])
        refused = [r for r in self.log_rows(root) if r["group"] == "tracker_board" and r["status"] == "refused"]
        self.assertGreaterEqual(len(refused), 2)
        self.assertEqual(Root(root).config()["permissions"]["tracker_board"]["answer"], "no")
