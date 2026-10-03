import json
import os
import subprocess
import sys
from unittest import mock

from cruciblelib.common import Root
from cruciblelib.trackers import github

from .helpers import CrucibleCase, run

PY = sys.executable.replace("\\", "/")
FILES = {"app.py": "def start():\n    return load()\n", "lib.py": "def load():\n    return 'broken'\n"}
CHANGE = f'{PY} -c "open(\'lib.py\', \'w\').write(\'FIXED\')"'
PROOF = f'{PY} -c "import sys; sys.exit(0 if open(\'lib.py\').read() == \'FIXED\' else 1)"'
CHANGE_APP = f'{PY} -c "open(\'app.py\', \'w\').write(\'FIXED2\')"'
PROOF_APP = f'{PY} -c "import sys; sys.exit(0 if open(\'app.py\').read() == \'FIXED2\' else 1)"'

EMAIL ="dev@example.test"


def git(repo, *args):
    done = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


class BlockerCase(CrucibleCase):
    def setUp(self):
        # The caller's git identity variables would override the repo config the tests assert on.
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        for key in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL"):
            os.environ.pop(key, None)
        self.root, self.repo = self.make_root(FILES)
        self.remote = os.path.join(self.tmp(), "remote.git")
        git(self.repo, "init", "-q")
        git(self.repo, "config", "user.name", "Dev User")
        git(self.repo, "config", "user.email", EMAIL)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "start")
        git(self.repo, "init", "-q", "--bare", self.remote)
        git(self.repo, "remote", "add", "origin", self.remote)
        cfg = Root(self.root).config()
        cfg["repos"][0]["remote"] = "git@host.test:acme/svc.git"
        Root(self.root).save_config(cfg)
        self.gh_calls = []
        self.base = git(self.repo, "rev-parse", "--abbrev-ref", "HEAD")
        patcher = mock.patch.object(github, "run_gh", self.fake_gh)
        patcher.start()
        self.addCleanup(patcher.stop)

    def back_to_base(self):
        git(self.repo, "checkout", "-q", self.base)

    def fake_gh(self, args, stdin=None):
        self.gh_calls.append(list(args))
        if args[:2] == ["pr", "create"]:
            return f"https://host.test/acme/svc/pull/{len(self.gh_calls)}\n"
        raise AssertionError(f"unexpected gh call {args}")

    def allow(self, mode="within_limits", grant=True, push=True, **extra):
        words = ["--words", "test words"]
        self.assertEqual(run(self.root, "answer", "blocker_fixes", json.dumps({"mode": mode, **extra}), *words)[0], 0)
        if grant:
            self.assertEqual(run(self.root, "grant", "blocker_fixes", "yes", "--reopen", *words)[0], 0)
        if push:
            self.assertEqual(run(self.root, "grant", "blocker_pushes", "yes", "--reopen", *words)[0], 0)

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
        code, out, err = run(self.root, "answer", "blocker_fixes.branch", "crucible/shared", "--words", "test words")
        self.assertEqual(code, 0, err)
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
            self.back_to_base()
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


class FixBranchTests(BlockerCase):
    BRANCH = "crucible/fix-b-001"

    def remote_branches(self):
        return git(self.remote, "branch", "--list").split()

    def test_fix_run_commits_on_branch(self):
        self.allow(landing="local_branch")
        blocker = self.planned()
        code, out, err = run(self.root, "fix", "run", blocker)
        self.assertEqual(code, 0, out + err)
        self.assertEqual(git(self.repo, "branch", "--list", self.BRANCH).split()[-1], self.BRANCH)
        self.assertEqual(git(self.repo, "show", f"{self.BRANCH}:lib.py"), "FIXED")
        self.assertEqual(git(self.repo, "log", "-1", "--format=%ae", self.BRANCH), EMAIL)
        self.assertEqual(git(self.repo, "status", "--porcelain", "--", "lib.py"), "")
        self.assertEqual(self.remote_branches(), [])
        self.assertEqual(self.read(self.root, "blockers.json")[0]["status"], "fixed")
        self.assertTrue(any(r["command"] == f"commit {blocker}" and r["status"] == "ok" for r in self.log()))

    def test_fix_run_honours_the_callers_git_author_env(self):
        self.allow(landing="local_branch")
        blocker = self.planned()
        with mock.patch.dict(os.environ, {"GIT_AUTHOR_EMAIL": "other@example.test"}):
            code, out, err = run(self.root, "fix", "run", blocker)
        self.assertEqual(code, 0, out + err)
        self.assertEqual(git(self.repo, "log", "-1", "--format=%ae", self.BRANCH), "other@example.test")

    def test_push_needs_own_grant(self):
        self.allow(push=False)
        blocker = self.planned()
        code, out, err = run(self.root, "fix", "run", blocker)
        self.assertEqual(code, 1)
        self.assertEqual(self.remote_branches(), [])
        self.assertEqual(git(self.repo, "show", f"{self.BRANCH}:lib.py"), "FIXED")
        self.assertEqual(self.gh_calls, [])
        self.assertEqual(self.read(self.root, "blockers.json")[0]["status"], "fixed-local")
        self.assertIn("blocker_pushes", out + err)
        self.assertTrue(any(r["group"] == "blocker_pushes" and r["status"] == "refused" for r in self.log()))
        self.assertEqual(run(self.root, "grant", "blocker_pushes", "yes", "--reopen", "--words", "test words")[0], 0)
        self.back_to_base()
        blocker = self.planned()
        self.assertEqual(run(self.root, "fix", "run", blocker)[0], 0)
        self.assertEqual(self.remote_branches(), ["crucible/fix-b-002"])
        self.assertEqual(len(self.gh_calls), 1)

    def test_pr_failure_keeps_blocker_fixed_local(self):
        self.allow()
        blocker = self.planned()
        with mock.patch.object(github, "run_gh", side_effect=RuntimeError("gh is down")):
            code, out, err = run(self.root, "fix", "run", blocker)
        self.assertEqual(code, 1)
        self.assertEqual(self.remote_branches(), [self.BRANCH])
        self.assertEqual(self.read(self.root, "blockers.json")[0]["status"], "fixed-local")
        self.assertIn("gh is down", out + err)
        self.assertTrue(any(r["command"] == f"pr create {blocker}" and r["status"] == "failed" for r in self.log()))

    def test_each_fix_pr_contains_only_its_fix(self):
        self.allow(landing="local_branch")
        first = self.planned()
        second = self.planned(root_cause="app.py:1", touch="app.py", test="test_start=app.py:1", change=CHANGE_APP,
                              proof=PROOF_APP)
        for blocker in (first, second):
            self.assertEqual(run(self.root, "fix", "run", blocker)[0], 0)
        self.assertEqual(git(self.repo, "diff", "--name-only", f"{self.base}..crucible/fix-b-001").split(), ["lib.py"])
        self.assertEqual(git(self.repo, "diff", "--name-only", f"{self.base}..crucible/fix-b-002").split(), ["app.py"])
        self.assertEqual(git(self.repo, "rev-parse", "--abbrev-ref", "HEAD"), "crucible/audit-fixes")
        self.assertEqual(git(self.repo, "show", "crucible/audit-fixes:lib.py"), "FIXED")
        self.assertEqual(git(self.repo, "show", "crucible/audit-fixes:app.py"), "FIXED2")
        self.assertEqual(self.remote_branches(), [])
        self.assertTrue(any(r["command"] == f"merge {second}" and r["status"] == "ok" for r in self.log()))


    def test_proof_runs_on_fix_branch_alone(self):
        self.allow(landing="local_branch")
        first = self.planned()
        alone = (f'{PY} -c "import sys; sys.exit(0 if open(\'app.py\').read() == \'FIXED2\' '
                 f'and open(\'lib.py\').read() != \'FIXED\' else 1)"')
        second = self.planned(root_cause="app.py:1", touch="app.py", test="test_start=app.py:1", change=CHANGE_APP,
                              proof=alone)
        self.assertEqual(run(self.root, "fix", "run", first)[0], 0)
        self.assertEqual(git(self.repo, "rev-parse", "--abbrev-ref", "HEAD"), "crucible/audit-fixes")
        code, out, err = run(self.root, "fix", "run", second)
        self.assertEqual(code, 0, out + err)
        self.assertEqual(self.read(self.root, "blockers.json")[1]["status"], "fixed")
        self.assertEqual(git(self.repo, "show", "crucible/fix-b-002:lib.py"), git(self.repo, "show", f"{self.base}:lib.py"))

    def test_merge_conflict_keeps_fixed_local(self):
        self.allow(landing="local_branch")
        first = self.planned()
        other = f'{PY} -c "open(\'lib.py\', \'w\').write(\'FIXED-B\')"'
        other_proof = f'{PY} -c "import sys; sys.exit(0 if open(\'lib.py\').read() == \'FIXED-B\' else 1)"'
        second = self.planned(change=other, proof=other_proof)
        self.assertEqual(run(self.root, "fix", "run", first)[0], 0)
        before = git(self.repo, "rev-parse", "crucible/audit-fixes")
        code, out, err = run(self.root, "fix", "run", second)
        self.assertEqual(code, 1, out + err)
        self.assertEqual(self.read(self.root, "blockers.json")[1]["status"], "fixed-local")
        self.assertIn(f"conflicts with {first}", out + err)
        self.assertEqual(git(self.repo, "rev-parse", "crucible/audit-fixes"), before)
        self.assertEqual(git(self.repo, "status", "--porcelain"), "")
        self.assertEqual(git(self.repo, "show", "crucible/audit-fixes:lib.py"), "FIXED")
        self.assertEqual(git(self.repo, "show", "crucible/fix-b-002:lib.py"), "FIXED-B")

    def test_failed_proof_rerun_starts_clean(self):
        self.allow(landing="local_branch")
        blocker = self.planned(proof=f'{PY} -c "import sys; sys.exit(1)"')
        code, out, err = run(self.root, "fix", "run", blocker)
        self.assertEqual(code, 1, out + err)
        self.assertEqual(self.read(self.root, "blockers.json")[0]["status"], "failed")
        self.assertEqual(git(self.repo, "rev-parse", "--abbrev-ref", "HEAD"), self.base)
        self.assertIn("broken", self.lib_text())
        self.assertEqual(git(self.repo, "status", "--porcelain"), "")
        self.assertEqual(git(self.repo, "branch", "--list", self.BRANCH), "")
        code, out, err = run(self.root, *self.plan_args(blocker))
        self.assertEqual(code, 0, out + err)
        code, out, err = run(self.root, "fix", "run", blocker)
        self.assertEqual(code, 0, out + err)
        self.assertEqual(self.read(self.root, "blockers.json")[0]["status"], "fixed")
        self.assertEqual(git(self.repo, "show", f"{self.BRANCH}:lib.py"), "FIXED")

    def test_failed_proof_keeps_unrelated_uncommitted_work(self):
        self.allow(landing="local_branch")
        with open(os.path.join(self.repo, "app.py"), "w", encoding="utf-8") as fh:
            fh.write("DIRTY WORK")
        blocker = self.planned(proof=f'{PY} -c "import sys; sys.exit(1)"')
        code, out, err = run(self.root, "fix", "run", blocker)
        self.assertEqual(code, 1, out + err)
        self.assertEqual(self.read_text(os.path.join(self.repo, "app.py")), "DIRTY WORK")
        self.assertIn("broken", self.lib_text())
        self.assertEqual(git(self.repo, "rev-parse", "--abbrev-ref", "HEAD"), self.base)
        self.assertEqual(git(self.repo, "branch", "--list", self.BRANCH), "")

    def test_leave_failed_fix_dirty_checkout_reported(self):
        self.allow(landing="local_branch")
        first = self.planned()
        self.assertEqual(run(self.root, "fix", "run", first)[0], 0)
        dirty = f'{PY} -c "open(\'lib.py\', \'w\').write(\'DIRTY-LIB\'); open(\'app.py\', \'w\').write(\'X\')"'
        second = self.planned(root_cause="app.py:1", touch="app.py", test="test_start=app.py:1", change=dirty,
                              proof=f'{PY} -c "import sys; sys.exit(1)"')
        code, out, err = run(self.root, "fix", "run", second)
        self.assertEqual(code, 1, out + err)
        self.assertEqual(self.read(self.root, "blockers.json")[1]["status"], "failed")
        self.assertEqual(self.lib_text(), "DIRTY-LIB")
        entry = [r for r in self.log() if r["command"] == f"fix run {second}"][-1]
        self.assertEqual(entry["status"], "failed")
        self.assertIn("the checkout was not cleaned", json.dumps(entry))

    def test_failed_proof_removes_created_file(self):
        self.allow(landing="local_branch")
        create = PY + """ -c "open('new.py', 'x').write('NEW')" """.rstrip()
        proof = PY + """ -c "import sys; sys.exit(0 if open('new.py').read() == 'NEW' else 1)" """.rstrip()
        failing = f'{PY} -c "import sys; sys.exit(1)"'
        over = {"root_cause": "new.py:1", "touch": "new.py", "test": "test_new=new.py:1", "change": create}
        blocker = self.planned(proof=failing, **over)
        code, out, err = run(self.root, "fix", "run", blocker)
        self.assertEqual(code, 1, out + err)
        self.assertFalse(os.path.exists(os.path.join(self.repo, "new.py")))
        self.assertEqual(git(self.repo, "status", "--porcelain"), "")
        self.assertEqual(git(self.repo, "rev-parse", "--abbrev-ref", "HEAD"), self.base)
        code, out, err = run(self.root, *self.plan_args(blocker, proof=proof, **over))
        self.assertEqual(code, 0, out + err)
        code, out, err = run(self.root, "fix", "run", blocker)
        self.assertEqual(code, 0, out + err)
        self.assertEqual(git(self.repo, "show", f"{self.BRANCH}:new.py"), "NEW")


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

    def test_push_branch_without_branch_refused_at_plan(self):
        self.allow(landing="push_branch")
        blocker = self.add()
        code, out, err = run(self.root, *self.plan_args(blocker))
        self.assertEqual(code, 1, out)
        self.assertIn("branch", err)
        self.assertIn("push_branch", err)
        self.assertFalse(os.path.exists(os.path.join(self.root, "fixes", blocker + ".json")))
        self.assertEqual(self.read(self.root, "blockers.json")[0]["status"], "open")

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
