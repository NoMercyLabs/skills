import json
import os
import re
import shutil
import subprocess
import unittest

from .helpers import AssayCase, run


class ConfigTests(AssayCase):
    def read_config(self, root):
        with open(os.path.join(root, "config.json"), encoding="utf-8") as fh:
            return json.load(fh)

    def test_init_writes_key_and_unconfirmed_config(self):
        root, repo = self.make_root({"app.py": "print(1)\n"}, confirm=False)
        cfg = self.read_config(root)
        self.assertFalse(cfg["confirmed"])
        self.assertEqual(cfg["version"], 1)
        self.assertEqual(cfg["repos"][0]["name"], "svc")
        with open(os.path.join(root, "private", "key"), encoding="utf-8") as fh:
            key = fh.read().strip()
        self.assertRegex(key, r"^[0-9a-f]{64}$")

    def test_init_never_prints_the_key(self):
        repo = self.make_repo({"app.py": "print(1)\n"})
        root = os.path.join(self.tmp(), "audit")
        code, out, err = run(root, "init", "--repo", repo)
        with open(os.path.join(root, "private", "key"), encoding="utf-8") as fh:
            key = fh.read().strip()
        self.assertEqual(code, 0)
        self.assertNotIn(key, out + err)
        code, out, err = run(root, "summary")
        self.assertNotIn(key, out + err)

    def test_confirm_flips_it(self):
        root, repo = self.make_root({"app.py": "x = 1\n"}, confirm=False)
        code, out, err = run(root, "confirm")
        self.assertEqual(code, 0)
        self.assertTrue(self.read_config(root)["confirmed"])

    def test_unconfirmed_config_refused(self):
        root, repo = self.make_root({"app.py": "x = 1\n"}, confirm=False)
        for command in (["inventory"], ["estimate"], ["show", "svc-u01", "app.py"],
                        ["proof", "svc-u01", "none.jsonl"], ["status"]):
            code, out, err = run(root, *command)
            self.assertEqual(code, 1, command)
            self.assertIn("config not confirmed", err, command)
            self.assertIn("assay confirm", err, command)

    def test_init_allowed_commands_work_unconfirmed(self):
        root, repo = self.make_root({"app.py": "x = 1\n"}, confirm=False)
        for command in (["detect"], ["summary"], ["confirm"]):
            code, out, err = run(root, *command)
            self.assertEqual(code, 0, (command, err))

    def test_init_default_goals_order(self):
        root, repo = self.make_root({"app.py": "x = 1\n"}, confirm=False)
        goals = self.read_config(root)["goals"]
        self.assertEqual([g["id"] for g in goals], [1, 2, 3, 4])
        self.assertEqual(goals[0]["name"], "users can use the product without help")
        self.assertEqual([g["name"] for g in goals[1:]], ["security", "stability", "features"])

    def test_init_defaults_match_contract(self):
        root, repo = self.make_root({"app.py": "x = 1\n"}, confirm=False)
        cfg = self.read_config(root)
        self.assertEqual(cfg["budget"], {"max_tokens": 0, "tokens_per_line": 34})
        self.assertEqual(cfg["models"], {"reader": "balanced", "verifier": "balanced",
                                         "check": "fast", "judge": "strong"})
        self.assertEqual(cfg["advisories"], "draft")
        self.assertEqual(cfg["unit_bytes"], 92160)
        self.assertFalse(cfg["live_checks"]["enabled"])
        self.assertEqual(cfg["scope"], {"include": [], "skip": []})

    def test_init_counts_languages_and_ci_files(self):
        root, repo = self.make_root({
            "api/handler.py": "a = 1\nb = 2\nc = 3\n",
            "web/app.js": "let x = 1;\n",
            ".github/workflows/ci.yml": "on: push\n",
            "deploy.sh": "echo hi\n",
        }, confirm=False)
        detected = self.read_config(root)["repos"][0]["detected"]
        self.assertEqual(detected["languages"]["Python"], 3)
        self.assertEqual(detected["languages"]["JavaScript"], 1)
        self.assertEqual(detected["languages"]["Shell"], 1)
        self.assertEqual(detected["ci"], [".github/workflows/ci.yml"])

    @unittest.skipUnless(shutil.which("git"), "git not installed")
    def test_init_detects_git_remote_and_owner(self):
        repo = self.make_repo({"app.py": "x = 1\n"}, name="widgets")
        subprocess.run(["git", "-C", repo, "init", "-q"], check=True)
        subprocess.run(["git", "-C", repo, "remote", "add", "origin",
                        "https://github.com/acme/widgets.git"], check=True)
        root = os.path.join(self.tmp(), "audit")
        code, out, err = run(root, "init", "--repo", repo)
        self.assertEqual(code, 0, err)
        entry = self.read_config(root)["repos"][0]
        self.assertEqual(entry["remote"], "https://github.com/acme/widgets.git")
        self.assertEqual(entry["owner"], "acme")
        self.assertIn("acme/widgets", out)

    def test_init_without_git_keeps_only_the_path(self):
        root, repo = self.make_root({"app.py": "x = 1\n"}, confirm=False)
        entry = self.read_config(root)["repos"][0]
        self.assertEqual(entry["remote"], "")
        self.assertEqual(os.path.realpath(entry["path"]), os.path.realpath(repo))

    def test_init_twice_refused_and_key_kept(self):
        root, repo = self.make_root({"app.py": "x = 1\n"}, confirm=False)
        with open(os.path.join(root, "private", "key"), encoding="utf-8") as fh:
            before = fh.read()
        code, out, err = run(root, "init", "--repo", repo)
        self.assertEqual(code, 1)
        self.assertIn("already", err)
        with open(os.path.join(root, "private", "key"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), before)

    def test_init_refuses_missing_repo_folder(self):
        root = os.path.join(self.tmp(), "audit")
        code, out, err = run(root, "init", "--repo", os.path.join(self.tmp(), "nope"))
        self.assertEqual(code, 1)
        self.assertIn("not a folder", err)

    def test_detect_suggests_skips_without_applying_them(self):
        root, repo = self.make_root({"app.py": "x = 1\n", "dist/out.js": "var a;\n"}, confirm=False)
        code, out, err = run(root, "detect")
        self.assertIn("dist", out)
        self.assertEqual(self.read_config(root)["scope"]["skip"], [])


if __name__ == "__main__":
    unittest.main()
