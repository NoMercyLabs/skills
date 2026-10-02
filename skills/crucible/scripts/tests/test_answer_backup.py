import json
import os

from cruciblelib.answer import INTERVIEW_ORDER
from cruciblelib.common import CrucibleError, Root
from cruciblelib.backup import backup
from cruciblelib.permissions import GROUPS

from .helpers import CrucibleCase, run

FILES = {"app.py": "x = 1\n"}


class AnswerTests(CrucibleCase):
    def config(self, root):
        with open(os.path.join(root, "config.json"), encoding="utf-8") as fh:
            return json.load(fh)

    def fresh(self):
        root, repo = self.make_root(FILES, confirm=False, memory=False)
        return root

    def test_defaults_after_init(self):
        cfg = self.config(self.fresh())
        self.assertIsNone(cfg["auto_file"])
        self.assertEqual(cfg["blocker_fixes"], {"mode": None, "landing": "pr", "branch": None,
                                                "live_changes": "never"})
        self.assertEqual(cfg["backups"], {"enabled": True, "path": None})
        self.assertEqual(cfg["knowledge_sources"], [])
        self.assertEqual(cfg["permissions"], {})

    def test_auto_file_asked_after_tracker(self):
        root = self.fresh()
        for key in ("scope", "goals", "stages", "tracker"):
            code, out, err = run(root, "next")
            self.assertEqual(out.strip(), key)
            self.assertEqual(run(root, "answer", key, "{}", "--words", "ok")[0], 0)
        code, out, err = run(root, "next")
        self.assertEqual(out.strip(), "auto_file")
        self.assertEqual(INTERVIEW_ORDER.index("auto_file"), INTERVIEW_ORDER.index("tracker") + 1)

    def test_interview_order_matches_the_contract(self):
        self.assertEqual(INTERVIEW_ORDER[:15], (
            "scope", "goals", "stages", "tracker", "auto_file", "advisories", "owners", "privacy_words",
            "budget", "models", "live_checks", "blocker_fixes", "backups", "memory", "knowledge_sources"))
        self.assertEqual(INTERVIEW_ORDER[15:], tuple("permissions." + g for g in GROUPS))

    def test_next_walks_to_the_end(self):
        root = self.fresh()
        seen = []
        for _ in range(len(INTERVIEW_ORDER) + 1):
            out = run(root, "next")[1].strip()
            if out == "all questions answered":
                break
            seen.append(out)
            if out.startswith("permissions."):
                self.assertEqual(run(root, "grant", out.split(".", 1)[1], "no")[0], 0)
            elif out == "auto_file":
                run(root, "answer", out, "true")
            elif out == "blocker_fixes":
                run(root, "answer", out, '{"mode": "each"}')
            elif out == "memory":
                run(root, "answer", out, '{"kind": "none"}')
            else:
                run(root, "answer", out, "[]")
        self.assertEqual(tuple(seen), INTERVIEW_ORDER)

    def test_answer_records_the_users_words(self):
        root = self.fresh()
        code, out, err = run(root, "answer", "tracker.kind", "github-issues", "--words", "plain issues please")
        self.assertEqual(code, 0, err)
        cfg = self.config(root)
        self.assertEqual(cfg["tracker"]["kind"], "github-issues")
        row = cfg["answers"]["tracker.kind"]
        self.assertEqual((row["value"], row["words"]), ("github-issues", "plain issues please"))
        self.assertRegex(row["at"], r"^\d{4}-\d\d-\d\dT")

    def test_answer_refuses_unknown_keys(self):
        root = self.fresh()
        before = self.config(root)
        code, out, err = run(root, "answer", "colour", "red")
        self.assertEqual(code, 1)
        self.assertIn("unknown key", err)
        self.assertEqual(self.config(root), before)

    def test_answer_refuses_other_internal_keys(self):
        root = self.fresh()
        for key in ("confirmed", "version", "repos", "answers"):
            self.assertEqual(run(root, "answer", key, "true")[0], 1, key)
        self.assertFalse(self.config(root)["confirmed"])

    def test_answer_refuses_the_permission_section(self):
        root = self.fresh()
        code, out, err = run(root, "answer", "permissions.installs", '{"answer": "yes"}')
        self.assertEqual(code, 1)
        self.assertIn("crucible grant", err)

    def test_answer_parses_json_and_plain_strings(self):
        root = self.fresh()
        run(root, "answer", "stages", '["alpha", "beta"]')
        run(root, "answer", "advisories", "none")
        run(root, "answer", "budget.max_tokens", "200000")
        cfg = self.config(root)
        self.assertEqual(cfg["stages"], ["alpha", "beta"])
        self.assertEqual(cfg["advisories"], "none")
        self.assertEqual(cfg["budget"], {"max_tokens": 200000, "tokens_per_line": 34})

    def test_dict_answer_keeps_the_defaults_it_does_not_name(self):
        root = self.fresh()
        run(root, "answer", "blocker_fixes", '{"mode": "within_limits"}')
        self.assertEqual(self.config(root)["blocker_fixes"],
                         {"mode": "within_limits", "landing": "pr", "branch": None, "live_changes": "never"})

    def test_answer_validates_choices(self):
        root = self.fresh()
        for key, value in (("auto_file", "maybe"), ("blocker_fixes.mode", "sometimes"),
                           ("blocker_fixes.landing", "email"), ("memory.kind", "notes"),
                           ("blocker_fixes", '{"mode": "sometimes"}')):
            self.assertEqual(run(root, "answer", key, value)[0], 1, key)
        self.assertIsNone(self.config(root)["auto_file"])

    def test_answer_sets_auto_file_and_next_moves_on(self):
        root = self.fresh()
        self.assertEqual(run(root, "answer", "auto_file", "true", "--words", "yes, file them")[0], 0)
        self.assertIs(self.config(root)["auto_file"], True)

    def test_memory_command_counts_as_answering_memory(self):
        root = self.fresh()
        run(root, "memory", "none")
        order = []
        for _ in range(len(INTERVIEW_ORDER)):
            out = run(root, "next")[1].strip()
            order.append(out)
            if out.startswith("permissions."):
                break
            run(root, "answer", out, "true" if out == "auto_file" else '{"mode": "never"}' if out == "blocker_fixes" else "[]")
        self.assertNotIn("memory", order)

    def test_answer_works_before_confirm(self):
        root = self.fresh()
        self.assertEqual(run(root, "answer", "scope.skip", '["dist"]')[0], 0)
        self.assertEqual(self.config(root)["scope"]["skip"], ["dist"])


class BackupTests(CrucibleCase):
    def root_with(self, config=None):
        root, repo = self.make_root(FILES, config=config)
        return Root(root), repo

    def test_backup_before_change(self):
        root, repo = self.root_with()
        target_file = os.path.join(repo, "app.py")
        path = backup(root, "app.py", target_file)
        self.assertTrue(path.startswith(root.p("backups")), path)
        with open(path, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "x = 1\n")
        with open(target_file, "w", encoding="utf-8") as fh:
            fh.write("x = 2\n")
        with open(path, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "x = 1\n", "the copy keeps the old content after the change")
        rows = [json.loads(line) for line in self.read_text(root.p("actions.log")).splitlines()]
        self.assertEqual(rows[-1]["status"], "ok")
        self.assertEqual(rows[-1]["group"], "backups")
        self.assertIn(path, rows[-1]["result"])

    def test_backup_copies_a_folder(self):
        root, repo = self.root_with()
        path = backup(root, "repo", repo)
        self.assertTrue(os.path.isfile(os.path.join(path, "app.py")))

    def test_backup_saves_text(self):
        root, repo = self.root_with()
        path = backup(root, "board fields", '{"fields": ["Stage"]}')
        with open(path, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), '{"fields": ["Stage"]}')

    def test_backup_goes_to_the_users_path(self):
        target = os.path.join(self.tmp(), "elsewhere")
        root, repo = self.root_with()
        cfg = root.config()
        cfg["backups"]["path"] = target
        root.save_config(cfg)
        path = backup(root, "cfg", "text")
        self.assertTrue(path.startswith(target), path)

    def test_two_backups_with_one_label_do_not_overwrite(self):
        root, repo = self.root_with()
        first, second = backup(root, "same", "one"), backup(root, "same", "two")
        self.assertNotEqual(first, second)
        self.assertEqual(self.read_text(first), "one")

    def test_a_label_cannot_escape_the_backup_folder(self):
        root, repo = self.root_with()
        path = backup(root, "../../evil", "text")
        self.assertEqual(os.path.dirname(path), root.p("backups"))

    def test_backup_off_skips_and_says_so(self):
        root, repo = self.root_with()
        cfg = root.config()
        cfg["backups"]["enabled"] = False
        root.save_config(cfg)
        self.assertIsNone(backup(root, "x", "text"))
        self.assertFalse(os.path.exists(root.p("backups")))
        row = json.loads(self.read_text(root.p("actions.log")).splitlines()[-1])
        self.assertEqual(row["status"], "skipped")

    def test_a_failed_backup_raises_and_is_logged(self):
        root, repo = self.root_with()
        os.makedirs(os.path.join(root.path, "blocker"), exist_ok=True)
        with open(os.path.join(root.path, "backups"), "w", encoding="utf-8") as fh:
            fh.write("a file where the folder should be")
        with self.assertRaises(CrucibleError) as ctx:
            backup(root, "x", "text")
        self.assertIn("the change is not made", str(ctx.exception))
        row = json.loads(self.read_text(root.p("actions.log")).splitlines()[-1])
        self.assertEqual(row["status"], "failed")
