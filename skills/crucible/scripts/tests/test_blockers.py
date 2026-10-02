import json
import os
import sys
from unittest import mock

from cruciblelib.common import Root
from cruciblelib.trackers import github

from .helpers import CrucibleCase, run

PY = sys.executable.replace("\\", "/")
FILES = {"app.py": "def start():\n    return load()\n", "lib.py": "def load():\n    return 'broken'\n"}
CHANGE = f'{PY} -c "open(\'lib.py\', \'w\').write(\'FIXED\')"'
PROOF = f'{PY} -c "import sys; sys.exit(0 if open(\'lib.py\').read() == \'FIXED\' else 1)"'


class BlockerCase(CrucibleCase):
    def setUp(self):
        self.root, self.repo = self.make_root(FILES)

    def allow(self, mode="within_limits", grant=True, **extra):
        words = ["--words", "test words"]
        self.assertEqual(run(self.root, "answer", "blocker_fixes", json.dumps({"mode": mode, **extra}), *words)[0], 0)
        if grant:
            self.assertEqual(run(self.root, "grant", "blocker_fixes", "yes", "--reopen", *words)[0], 0)

    def add(self, text="the readers cannot load the module", stage="inventory"):
        code, out, err = run(self.root, "blocker", "add", text, "--stage", stage)
        self.assertEqual(code, 0, err)
        return out.split()[0]

    def plan_args(self, blocker, **over):
        opts = {"cause": "load() never returns the module", "evidence": "lib.py:2 return 'broken'",
                "root_cause": "lib.py:2", "touch": "lib.py", "test": "test_load=lib.py:2", "change": CHANGE,
                "proof": PROOF, "why": "a retry in app.py would still read the broken value"}
        opts.update(over)
        args = ["fix", "plan", blocker]
        for key, value in opts.items():
            if value is not None:
                args += [f"--{key.replace('_', '-')}", value]
        return args

    def planned(self, **over):
        blocker = self.add()
        code, out, err = run(self.root, *self.plan_args(blocker, **over))
        self.assertEqual(code, 0, out + err)
        return blocker

    def log(self):
        return [json.loads(line) for line in self.read_text(os.path.join(self.root, "actions.log")).splitlines()]

    def lib_text(self):
        return self.read_text(os.path.join(self.repo, "lib.py"))


class BlockerRecordTests(BlockerCase):
    def test_blocker_add_and_list(self):
        first = self.add()
        second = self.add("the board has no Severity field", stage="filing")
        self.assertNotEqual(first, second)
        code, out, err = run(self.root, "blocker", "list")
        self.assertEqual(code, 0, err)
        self.assertIn("readers cannot load", out)
        self.assertIn("filing", out)
        self.assertIn("open", out)

    def test_fix_plan_writes_the_plan_file(self):
        self.allow(landing="local_branch")
        blocker = self.planned()
        plan = self.read(self.root, f"fixes/{blocker}.json")
        self.assertEqual(plan["root_cause"], "lib.py:2")
        self.assertEqual(plan["touches"], ["lib.py"])
        self.assertEqual(plan["landing"], "local_branch")
        self.assertEqual(plan["tests"], [{"name": "test_load", "target": "lib.py:2"}])
        self.assertEqual(plan["backup"], ["lib.py"])
        self.assertIn("retry", plan["why_symptom_patch_not_enough"])
        self.assertTrue(plan["proof"] and plan["change"])

    def test_fix_plan_unknown_blocker_refused(self):
        code, out, err = run(self.root, *self.plan_args("B-99"))
        self.assertEqual(code, 1)
        self.assertIn("B-99", err)


class FixLandingTests(BlockerCase):
    def setUp(self):
        super().setUp()
        cfg = Root(self.root).config()
        cfg["repos"][0]["remote"] = "git@host.test:acme/svc.git"
        Root(self.root).save_config(cfg)
        self.gh_calls = []
        patcher = mock.patch.object(github, "run_gh", self.fake_gh)
        patcher.start()
        self.addCleanup(patcher.stop)

    def fake_gh(self, args, stdin=None):
        self.gh_calls.append(list(args))
        if args[:2] == ["pr", "create"]:
            return f"https://host.test/acme/svc/pull/{len(self.gh_calls)}\n"
        raise AssertionError(f"unexpected gh call {args}")

    def pr_calls(self):
        return [c for c in self.gh_calls if c[:2] == ["pr", "create"]]

    def landing(self):
        return self.read(self.root, "fixes/B-001.json")["landing"]

    def test_fix_plan_default_landing_is_pr(self):
        self.planned()
        self.assertEqual(self.landing(), "pr")

    def test_fix_plan_answered_landing_is_kept(self):
        for choice in ("local_branch", "push_branch"):
            with self.subTest(landing=choice):
                code, out, err = run(self.root, "answer", "blocker_fixes.landing", choice, "--words", "test words")
                self.assertEqual(code, 0, err)
                blocker = self.add()
                self.assertEqual(run(self.root, *self.plan_args(blocker))[0], 0)
                self.assertEqual(self.read(self.root, f"fixes/{blocker}.json")["landing"], choice)

    def test_fix_default_landing_one_pr_per_fix(self):
        self.allow()
        first, second = self.planned(), self.planned()
        for blocker in (first, second):
            code, out, err = run(self.root, "fix", "run", blocker)
            self.assertEqual(code, 0, out + err)
        calls = self.pr_calls()
        self.assertEqual(len(calls), 2)
        heads = [c[c.index("--head") + 1] for c in calls]
        self.assertEqual(len(set(heads)), 2)
        for blocker, call, head in zip((first, second), calls, heads):
            self.assertIn(blocker.lower(), head)
            self.assertIn(blocker, call[call.index("--title") + 1])
            self.assertEqual(call[call.index("--repo") + 1], "acme/svc")
        self.assertEqual([r["command"] for r in self.log() if r["status"] == "ok" and "pr create" in r["command"]],
                         [f"pr create {first}", f"pr create {second}"])

    def test_fix_local_branch_landing_makes_no_pr(self):
        self.allow(landing="local_branch")
        blocker = self.planned()
        code, out, err = run(self.root, "fix", "run", blocker)
        self.assertEqual(code, 0, out + err)
        self.assertEqual(self.pr_calls(), [])

    def test_failed_fix_opens_no_pr(self):
        self.allow()
        blocker = self.planned(change=f'{PY} -c "pass"')
        code, out, err = run(self.root, "fix", "run", blocker)
        self.assertEqual(code, 1)
        self.assertEqual(self.pr_calls(), [])


class FixPlanRefusalTests(BlockerCase):
    def refused(self, text, **over):
        blocker = self.add()
        code, out, err = run(self.root, *self.plan_args(blocker, **over))
        self.assertEqual(code, 1, out)
        self.assertIn(text, err)
        self.assertFalse(os.path.exists(os.path.join(self.root, "fixes", blocker + ".json")))

    def test_symptom_only_fix_refused(self):
        self.refused("root cause", touch="app.py")

    def test_fix_test_targets_cause(self):
        self.refused("test", test="test_start=app.py:2")

    def test_fix_plan_needs_why_a_symptom_patch_is_not_enough(self):
        self.refused("why", why=" ")

    def test_fix_plan_needs_evidence(self):
        self.refused("evidence", evidence=None)

    def test_fix_command_with_network_verb_refused(self):
        for command in ("git push origin main", "git -C . clone https://example.com/x.git", "gh pr create", "curl -O x",
                        "wget x", "ssh host ls", "scp a b:c", "nc host 80", "/usr/bin/curl x", "curl.exe x"):
            for field in ("change", "proof"):
                with self.subTest(command=command, field=field):
                    blocker = self.add()
                    code, out, err = run(self.root, *self.plan_args(blocker, **{field: command}))
                    self.assertEqual(code, 1, out)
                    self.assertIn(command.split()[0], err)
                    self.assertIn("you run it yourself", err)
                    self.assertFalse(os.path.exists(os.path.join(self.root, "fixes", blocker + ".json")))

    def test_fix_touching_must_not_change_refused_at_plan(self):
        run(self.root, "brief", "answer", "must_never_change", "--words", "lib.py stays as it is")
        self.refused("must never change")


class FixRunTests(BlockerCase):
    def test_blocker_fix_needs_grant(self):
        blocker = self.planned()
        code, out, err = run(self.root, "fix", "run", blocker)
        self.assertEqual(code, 1)
        self.assertIn("refused: blocker_fixes", err)
        self.assertIn("broken", self.lib_text())
        self.assertEqual(self.log()[-1]["status"], "refused")

    def test_fix_run_mode_never_refused(self):
        self.allow("never")
        blocker = self.planned()
        code, out, err = run(self.root, "fix", "run", blocker, "--yes-words", "yes please")
        self.assertEqual(code, 1)
        self.assertIn("never", err)
        self.assertIn("broken", self.lib_text())

    def test_fix_run_mode_each_needs_yes_words(self):
        self.allow("each")
        blocker = self.planned()
        code, out, err = run(self.root, "fix", "run", blocker)
        self.assertEqual(code, 1)
        self.assertIn("--yes-words", err)
        self.assertIn("broken", self.lib_text())
        code, out, err = run(self.root, "fix", "run", blocker, "--yes-words", "yes, fix that one")
        self.assertEqual(code, 0, out + err)
        self.assertEqual(self.lib_text(), "FIXED")

    def test_backup_before_change_in_fix_run(self):
        self.allow()
        blocker = self.planned()
        code, out, err = run(self.root, "fix", "run", blocker)
        self.assertEqual(code, 0, out + err)
        rows = self.log()
        groups = [r["group"] for r in rows if r["status"] == "ok"]
        self.assertLess(groups.index("backups"), groups.index("blocker_fixes"))
        copies = os.listdir(os.path.join(self.root, "backups"))
        self.assertEqual(len(copies), 1)
        self.assertIn("broken", self.read_text(os.path.join(self.root, "backups", copies[0])))
        self.assertEqual(self.lib_text(), "FIXED")

    def test_fix_run_aborts_when_backup_fails(self):
        blocked = os.path.join(self.tmp(), "not-a-folder")
        with open(blocked, "w", encoding="utf-8") as fh:
            fh.write("a file, so a backup folder cannot be made here")
        cfg = Root(self.root).config()
        cfg["backups"] = {"enabled": True, "path": os.path.join(blocked, "inside")}
        Root(self.root).save_config(cfg)
        self.allow()
        blocker = self.planned()
        code, out, err = run(self.root, "fix", "run", blocker)
        self.assertEqual(code, 1)
        self.assertIn("backup", err)
        self.assertIn("broken", self.lib_text())
        self.assertEqual(self.read(self.root, "blockers.json")[0]["status"], "open")

    def test_blocked_stage_rerun_proves_fix(self):
        self.allow()
        blocker = self.planned()
        code, out, err = run(self.root, "fix", "run", blocker)
        self.assertEqual(code, 0, out + err)
        self.assertEqual(self.read(self.root, "blockers.json")[0]["status"], "fixed")
        last = self.log()[-1]
        self.assertEqual((last["group"], last["status"]), ("blocker_fixes", "ok"))

    def test_blocked_stage_rerun_failing_marks_failed(self):
        self.allow()
        blocker = self.planned(change=f'{PY} -c "pass"')
        code, out, err = run(self.root, "fix", "run", blocker)
        self.assertEqual(code, 1)
        self.assertEqual(self.read(self.root, "blockers.json")[0]["status"], "failed")
        self.assertEqual(self.log()[-1]["status"], "failed")
        self.assertIn("failed", out + err)

    def test_fix_run_refuses_a_network_command_in_a_stored_plan(self):
        self.allow()
        blocker = self.planned()
        path = os.path.join(self.root, "fixes", blocker + ".json")
        plan = self.read(self.root, f"fixes/{blocker}.json")
        plan["change"] = ["git", "push", "origin", "main"]
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(plan, fh)
        code, out, err = run(self.root, "fix", "run", blocker)
        self.assertEqual(code, 1)
        self.assertIn("git push", err)
        self.assertIn("broken", self.lib_text())
        self.assertEqual(self.read(self.root, "blockers.json")[0]["status"], "open")

    def test_fix_touching_must_not_change_refused(self):
        self.allow()
        blocker = self.planned()
        run(self.root, "brief", "answer", "must_never_change", "--words", "lib.py stays as it is")
        code, out, err = run(self.root, "fix", "run", blocker)
        self.assertEqual(code, 1)
        self.assertIn("must never change", err)
        self.assertIn("broken", self.lib_text())


class BlockerReportTests(BlockerCase):
    def test_report_lists_blockers(self):
        first = self.add("the readers cannot load the module", stage="inventory")
        self.add("the board has no Severity field", stage="filing")
        rows = self.read(self.root, "blockers.json")
        rows[0]["status"] = "failed"
        with open(os.path.join(self.root, "blockers.json"), "w", encoding="utf-8", newline="\n") as fh:
            json.dump(rows, fh)
        third = self.add("a fixed one", stage="gate")
        rows = self.read(self.root, "blockers.json")
        rows[2]["status"] = "fixed"
        with open(os.path.join(self.root, "blockers.json"), "w", encoding="utf-8", newline="\n") as fh:
            json.dump(rows, fh)
        code, out, err = run(self.root, "report")
        self.assertEqual(code, 0, err)
        self.assertIn("blockers: 3 (open 1, fixed 1, failed 1)", out)
        self.assertIn(f"  {first} inventory: the readers cannot load the module", out)
        self.assertIn("  B-002 filing: the board has no Severity field", out)
        self.assertNotIn(third + " gate", out)
