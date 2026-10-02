import json
import os
from unittest import mock

from cruciblelib import lessons
from cruciblelib.common import Root

from .helpers import CrucibleCase, run
from .test_blockers import BlockerCase
from .test_board_apply import BoardApplyCase
from .test_costs import RELEASE, RULES
from .test_knowledge import KnowledgeCase
from .test_lessons import PASSED, SHAPE, LessonCase
from .test_system import SystemCase


def actions(root):
    path = Root(root).p("actions.log")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


class EveryWriteIsLoggedTests(CrucibleCase):
    def test_log_every_write_costs_move_logs_the_change_to_the_instruction_file(self):
        root, repo = self.make_root({"CLAUDE.md": RULES + RELEASE})
        before = len(actions(root))
        code, out, err = run(root, "costs", "move", "--repo", "svc", "--file", "CLAUDE.md", "--heading", "Release steps")
        self.assertEqual(code, 0, err)
        new = actions(root)[before:]
        self.assertTrue(any("costs move" in row["command"] and row["status"] == "ok" for row in new), new)


class EveryFetchIsLoggedTests(KnowledgeCase):
    def test_log_every_write_knowledge_fetch_logs_what_it_wrote(self):
        folder = self.export({"notes.md": "# Notes\n\nPlain text.\n"})
        root = self.granted("folder:" + folder)
        before = len(actions(root))
        code, out, err = run(root, "knowledge", "fetch", "folder:" + folder)
        self.assertEqual(code, 0, err)
        self.assertTrue(self.written(root, [n for n in os.listdir(Root(root).p("knowledge"))][0]))
        new = actions(root)[before:]
        self.assertTrue(any("knowledge fetch" in row["command"] and row["status"] == "ok" for row in new), new)


class EveryLessonApplyIsLoggedTests(LessonCase):
    def test_log_every_write_learn_apply_logs_the_active_lesson(self):
        root, _ = self.audit()
        lesson = self.proposed(root)
        before = len(actions(root))
        with mock.patch.object(lessons, "run_selftest", return_value=PASSED):
            code, out, err = run(root, "learn", "apply", lesson["id"], "--yes")
        self.assertEqual(code, 0, err)
        new = actions(root)[before:]
        self.assertTrue(any(row["command"] == f"learn apply {lesson['id']}" and row["status"] == "ok"
                            and row["result"] == "active" for row in new), new)

    def test_log_every_write_learn_apply_logs_the_line_added_to_the_instruction_file(self):
        root, repo = self.audit()
        found = {"commands": 9, "scripts": [], "repeats": [
            {"shape": SHAPE, "runs": 4, "failed": 1, "retried": 1, "tokens": 800}]}
        lesson = lessons.propose(Root(root), repeats=found)[0]
        args = ("learn", "apply", lesson["id"], "--repo", "svc", "--file", "CLAUDE.md")
        self.assertEqual(run(root, *args, "--dry-run")[0], 0)
        before = len(actions(root))
        code, out, err = run(root, *args, "--yes")
        self.assertEqual(code, 0, err)
        new = actions(root)[before:]
        self.assertTrue(any(row["command"] == f"learn apply {lesson['id']}" and row["status"] == "ok"
                            and "CLAUDE.md" in row["result"] for row in new), new)


class EveryFixRunIsLoggedTests(BlockerCase):
    def test_log_every_write_fix_run_logs_the_outcome_of_the_change(self):
        self.allow()
        blocker = self.planned()
        before = len(actions(self.root))
        code, out, err = run(self.root, "fix", "run", blocker)
        self.assertEqual(code, 0, out + err)
        self.assertEqual(self.lib_text(), "FIXED")
        new = actions(self.root)[before:]
        self.assertTrue(any(row["command"] == f"fix run {blocker}" and row["status"] == "ok"
                            and row["result"].startswith("fixed") for row in new), new)


class EveryWorkspaceCloneIsLoggedTests(SystemCase):
    def test_log_every_write_workspace_clone_logs_the_clone(self):
        repo = self.git_repo({"app.py": "x = 1\n"})
        root = self.init_root(repo)
        base = os.path.join(self.tmp(), "base")
        self.assertEqual(run(root, "workspace", "choose", "base_folder", "--base", base, "--words", "a new folder")[0], 0)
        self.assertEqual(run(root, "grant", "workspace_clones", "yes", "--bound", "repos=svc", "--words", "clone svc")[0], 0)
        before = len(actions(root))
        code, out, err = run(root, "workspace", "clone", "--base", base)
        self.assertEqual(code, 0, err)
        self.assertTrue(os.path.isfile(os.path.join(base, "svc", "app.py")))
        new = actions(root)[before:]
        self.assertTrue(any(row["group"] == "workspace_clones" and row["command"].startswith("clone 1 repos into")
                            and row["status"] == "ok" and "svc" in row["result"] for row in new), new)


class EveryBoardApplyIsLoggedTests(BoardApplyCase):
    def test_log_every_write_board_apply_logs_each_field_it_creates(self):
        root = self.board_ready()
        self.approved_plan(root)
        before = len(actions(root))
        code, out, err = run(root, "board", "apply")
        self.assertEqual(code, 0, out + err)
        new = [row for row in actions(root)[before:] if row["group"] == "tracker_board" and row["status"] == "ok"]
        created = [row for row in new if row["command"].startswith("create field ")]
        self.assertEqual(len(created), len([c for c in self.gh.calls if c[:2] == ["project", "field-create"]]))
        self.assertTrue(created)
        self.assertTrue([row for row in new if row["command"].startswith("create view ")])
