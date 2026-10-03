import json
import os

from .helpers import CrucibleCase, run

FILES = {"app.py": "x = 1\n"}

POLICY_ANSWERS = (("auto_file", "true"), ("blocker_fixes", '{"mode": "each"}'), ("blocker_fixes.mode", "each"),
                  ("memory", '{"kind": "none"}'), ("live_checks", '{"enabled": false, "targets": []}'),
                  ("backups", '{"enabled": true}'), ("knowledge_sources", "[]"),
                  ("models", '{"reader": "fast"}'))
FACT_ANSWERS = (("scope", '{"include": [], "skip": []}'), ("stages", "[]"), ("privacy_words", "[]"),
                ("tracker.kind", "markdown"))


class WordsRequiredTests(CrucibleCase):
    def fresh(self):
        root, repo = self.make_root(FILES, confirm=False, memory=False)
        return root

    def config(self, root):
        with open(os.path.join(root, "config.json"), encoding="utf-8") as fh:
            return json.load(fh)

    def test_words_required_on_every_grant(self):
        root = self.fresh()
        for words in (None, "", "   "):
            args = ["grant", "installs", "yes"] + (["--words", words] if words is not None else [])
            code, out, err = run(root, *args)
            self.assertEqual(code, 1, args)
            self.assertIn("--words", err)
        self.assertEqual(self.config(root)["permissions"], {})
        self.assertEqual(run(root, "grant", "installs", "yes", "--words", "go ahead")[0], 0)

    def test_words_required_on_a_no_as_well(self):
        root = self.fresh()
        self.assertEqual(run(root, "grant", "installs", "no")[0], 1)

    def test_words_required_on_every_policy_answer(self):
        root = self.fresh()
        before = self.config(root)
        for key, value in POLICY_ANSWERS:
            code, out, err = run(root, "answer", key, value)
            self.assertEqual(code, 1, key)
            self.assertIn("--words", err, key)
        self.assertEqual(self.config(root), before)
        for key, value in POLICY_ANSWERS:
            self.assertEqual(run(root, "answer", key, value, "--words", "the user said so")[0], 0, key)

    def test_words_required_on_the_memory_choice(self):
        root = self.fresh()
        self.assertEqual(run(root, "memory", "none")[0], 1)
        self.assertIsNone(self.config(root)["memory"])
        self.assertEqual(run(root, "memory", "none", "--words", "no memory please")[0], 0)

    def test_words_optional_for_plain_facts(self):
        root = self.fresh()
        for key, value in FACT_ANSWERS:
            code, out, err = run(root, "answer", key, value)
            self.assertEqual(code, 0, (key, err))


class BlockerModeTests(CrucibleCase):
    def test_blocker_fixes_mode_stays_unset_until_answered(self):
        root, repo = self.make_root(FILES, confirm=False)
        for value in ('"never"', "null", "[]", "7"):
            code, out, err = run(root, "answer", "blocker_fixes", value, "--words", "x")
            self.assertEqual(code, 1, value)
            self.assertIn("blocker_fixes", err)
        with open(os.path.join(root, "config.json"), encoding="utf-8") as fh:
            cfg = json.load(fh)
        self.assertIsNone(cfg["blocker_fixes"]["mode"])
        run(root, "answer", "blocker_fixes", '{"landing": "local_branch"}', "--words", "branches only")
        self.assertEqual(run(root, "answer", "auto_file", "false", "--words", "ask me")[0], 0)
        from cruciblelib.permissions import GROUPS
        for group in GROUPS:
            run(root, "grant", group, "no", "--words", "no")
        code, out, err = run(root, "confirm")
        self.assertEqual(code, 1)
        self.assertIn("blocker_fixes", err)


class SecretFileTests(CrucibleCase):
    def test_env_templates_are_readable_every_other_env_file_is_a_secret(self):
        from cruciblelib.common import is_secret_file
        for name in (".env.example", ".env.sample", ".env.template", ".env.dist", "config/.env.example"):
            self.assertFalse(is_secret_file(name), name)
        for name in (".env", ".env.local", ".env.production", ".env.example.bak", "sub/.env", ".env.dist.local"):
            self.assertTrue(is_secret_file(name), name)
        self.assertFalse(is_secret_file("environment.py"))
        self.assertFalse(is_secret_file("app.py"))

    def test_inventory_never_snapshots_a_secret_env_file(self):
        root = self.make_inventoried({"app.py": "x = 1\n", ".env": "KEY=value\n", ".env.local": "A=b\n",
                                      ".env.example": "KEY=\n"})
        snap = os.path.join(root, "snapshot", "svc")
        self.assertTrue(os.path.exists(os.path.join(snap, ".env.example")))
        self.assertFalse(os.path.exists(os.path.join(snap, ".env")))
        self.assertFalse(os.path.exists(os.path.join(snap, ".env.local")))
