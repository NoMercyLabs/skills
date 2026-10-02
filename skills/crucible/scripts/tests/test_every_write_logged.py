import json
import os

from cruciblelib.common import Root

from .helpers import CrucibleCase, run
from .test_costs import RELEASE, RULES
from .test_knowledge import KnowledgeCase


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
