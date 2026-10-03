import json
import os

from cruciblelib.common import CrucibleError, Root, mask_secrets
from cruciblelib.permissions import (GROUPS, authorize, grant, log_action, parse_bounds, record_dryrun,
                                     require_approved, run_action)

from .helpers import CrucibleCase, run

FILES = {"app.py": "x = 1\n"}


class PermissionCase(CrucibleCase):
    def granted(self, grants=None, auto_file="false"):
        """A confirmed root; grants maps group -> list of --bound items for a yes, every other group is a no."""
        grants = grants or {}
        root, repo = self.make_root(FILES, confirm=False)
        self.assertEqual(run(root, "answer", "auto_file", auto_file, "--words", "test")[0], 0)
        self.assertEqual(run(root, "answer", "blocker_fixes", '{"mode": "never"}', "--words", "test")[0], 0)
        self.answer_workspace(root)
        self.answer_fable(root)
        self.answer_visibility(root)
        for group in GROUPS:
            if group in grants:
                bounds = [x for item in grants[group] for x in ("--bound", item)]
                code, out, err = run(root, "grant", group, "yes", "--words", "yes please", *bounds)
            else:
                code, out, err = run(root, "grant", group, "no", "--words", "no thanks")
            self.assertEqual(code, 0, err)
        self.answer_brief(root)
        self.assertEqual(run(root, "confirm")[0], 0)
        return root

    def log_rows(self, root):
        with open(os.path.join(root, "actions.log"), encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]

    def refused(self, call, *needles):
        with self.assertRaises(CrucibleError) as ctx:
            call()
        for needle in needles:
            self.assertIn(needle, str(ctx.exception))
        self.assertTrue(str(ctx.exception).startswith("refused:"), str(ctx.exception))


class ConfirmGateTests(PermissionCase):
    def test_confirm_needs_every_grant(self):
        root, repo = self.make_root(FILES, confirm=False)
        self.assertEqual(run(root, "answer", "auto_file", "false", "--words", "test")[0], 0)
        self.assertEqual(run(root, "answer", "blocker_fixes", '{"mode": "never"}', "--words", "test")[0], 0)
        self.answer_workspace(root)
        self.answer_fable(root)
        self.answer_visibility(root)
        for group in GROUPS[:-1]:
            self.assertEqual(run(root, "grant", group, "no", "--words", "test")[0], 0)
        code, out, err = run(root, "confirm")
        self.assertEqual(code, 1)
        self.assertIn(f"missing: permissions.{GROUPS[-1]}", err)
        self.assertNotIn("permissions.local_reads", err)
        self.assertEqual(run(root, "grant", GROUPS[-1], "no", "--words", "test")[0], 0)
        self.answer_brief(root)
        self.assertEqual(run(root, "confirm")[0], 0, err)

    def test_confirm_lists_every_missing_answer(self):
        root, repo = self.make_root(FILES, confirm=False)
        code, out, err = run(root, "confirm")
        self.assertEqual(code, 1)
        for name in ("auto_file", "blocker_fixes", "permissions.local_reads", "permissions.publish_report"):
            self.assertIn(name, err)

    def test_confirm_refuses_without_auto_file(self):
        root, repo = self.make_root(FILES, confirm=False)
        self.assertEqual(run(root, "answer", "blocker_fixes", '{"mode": "each"}', "--words", "test")[0], 0)
        for group in GROUPS:
            run(root, "grant", group, "no", "--words", "test")
        code, out, err = run(root, "confirm")
        self.assertEqual(code, 1)
        self.assertIn("missing: auto_file", err)

    def test_confirm_refuses_while_blocker_fix_mode_is_unset(self):
        root, repo = self.make_root(FILES, confirm=False)
        self.assertEqual(run(root, "answer", "auto_file", "true", "--words", "test")[0], 0)
        for group in GROUPS:
            run(root, "grant", group, "no", "--words", "test")
        code, out, err = run(root, "confirm")
        self.assertEqual(code, 1)
        self.assertIn("missing: blocker_fixes", err)


class AuthorizeTests(PermissionCase):
    def test_action_without_grant_refused(self):
        root, repo = self.make_root(FILES, confirm=False)
        self.refused(lambda: authorize(Root(root), "tracker_issues", "create issue"), "no answer yet", "grant")
        rows = self.log_rows(root)
        self.assertEqual([r["status"] for r in rows], ["refused"])
        self.assertEqual(rows[0]["group"], "tracker_issues")

    def test_action_with_a_no_is_refused(self):
        root = self.granted()
        self.refused(lambda: authorize(Root(root), "tracker_issues", "create issue"), "answered no")

    def test_unknown_group_is_an_error(self):
        root = self.granted()
        with self.assertRaises(CrucibleError):
            authorize(Root(root), "tracker_wishes", "x")

    def test_yes_without_bounds_allows_an_action_that_wants_nothing_bounded(self):
        root = self.granted({"local_reads": []})
        authorize(Root(root), "local_reads", "read files")

    def test_outside_grant_bounds_refused_repo_not_listed(self):
        root = self.granted({"tracker_issues": ["repos=svc,web", "max_count=5"]})
        authorize(Root(root), "tracker_issues", "file", repos=["svc"], count=2)
        self.refused(lambda: authorize(Root(root), "tracker_issues", "file", repos=["svc", "ops"]),
                     "repos ops not granted")

    def test_outside_grant_bounds_refused_count_over_max(self):
        root = self.granted({"tracker_issues": ["repos=svc", "max_count=3"]})
        authorize(Root(root), "tracker_issues", "file", count=3)
        self.refused(lambda: authorize(Root(root), "tracker_issues", "file", count=4),
                     "count 4 is over the granted max_count 3")

    def test_outside_grant_bounds_refused_label_not_named(self):
        root = self.granted({"tracker_labels": ["labels=audit,severity-high"]})
        authorize(Root(root), "tracker_labels", "create", labels=["audit"])
        self.refused(lambda: authorize(Root(root), "tracker_labels", "create", labels=["audit", "wontfix"]),
                     "labels wontfix not granted")

    def test_outside_grant_bounds_refused_assignee_and_instance(self):
        root = self.granted({"tracker_assignees": ["assignees=ana"], "memory_writes": ["instance=work"]})
        self.refused(lambda: authorize(Root(root), "tracker_assignees", "assign", assignees=["bo"]),
                     "assignees bo not granted")
        authorize(Root(root), "memory_writes", "write", instance="work")
        self.refused(lambda: authorize(Root(root), "memory_writes", "write", instance="home"),
                     "instance home is not the granted work")

    def test_a_wanted_key_the_grant_never_named_is_refused(self):
        root = self.granted({"tracker_issues": ["repos=svc"]})
        self.refused(lambda: authorize(Root(root), "tracker_issues", "file", count=1),
                     "max_count is not in the granted bounds")

    def test_every_refusal_is_logged_with_its_reason(self):
        root = self.granted({"tracker_issues": ["repos=svc", "max_count=1"]})
        self.refused(lambda: authorize(Root(root), "tracker_issues", "file 9 issues", count=9))
        row = self.log_rows(root)[-1]
        self.assertEqual(row["status"], "refused")
        self.assertIn("file 9 issues", row["command"])
        self.assertIn("over the granted max_count", row["result"])

    def test_a_single_string_for_a_list_bound_is_treated_as_one_item(self):
        root = self.granted({"tracker_issues": ["repos=svc", "max_count=2"]})
        authorize(Root(root), "tracker_issues", "file", repos="svc")
        self.refused(lambda: authorize(Root(root), "tracker_issues", "file", repos="ops"))


class GrantTests(PermissionCase):
    def test_denied_grant_never_asked_again(self):
        root, repo = self.make_root(FILES, confirm=False)
        self.assertEqual(run(root, "grant", "tracker_issues", "no", "--words", "not now")[0], 0)
        code, out, err = run(root, "grant", "tracker_issues", "yes", "--words", "test")
        self.assertEqual(code, 1)
        self.assertIn("a no is final", err)
        code, out, err = run(root, "grant", "tracker_issues", "yes", "--reopen")
        self.assertEqual(code, 1, "reopen without the user's words is refused")
        with open(os.path.join(root, "config.json"), encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["permissions"]["tracker_issues"]["answer"], "no")
        code, out, err = run(root, "next")
        self.assertNotEqual(out.strip(), "permissions.tracker_issues")

    def test_a_denied_group_is_skipped_by_next(self):
        root, repo = self.make_root(FILES, confirm=False)
        run(root, "grant", "local_reads", "no", "--words", "test")
        for key in ("scope", "goals", "stages", "tracker", "auto_file", "advisories", "owners",
                    "privacy_words", "budget", "models", "live_checks", "blocker_fixes", "backups",
                    "memory", "knowledge_sources"):
            run(root, "answer", key, "{}" if key not in ("auto_file", "blocker_fixes", "memory") else
                {"auto_file": "false", "blocker_fixes": '{"mode": "never"}', "memory": '{"kind": "none"}'}[key],
                "--words", "test")
        self.answer_visibility(root)
        self.answer_workspace(root)
        self.answer_fable(root)
        code, out, err = run(root, "next")
        self.assertEqual(out.strip(), "permissions.agent_runs")

    def test_reopen_with_the_users_words_is_allowed_and_recorded(self):
        root, repo = self.make_root(FILES, confirm=False)
        run(root, "grant", "installs", "no", "--words", "test")
        code, out, err = run(root, "grant", "installs", "yes", "--reopen", "--words", "I changed my mind")
        self.assertEqual(code, 0, err)
        with open(os.path.join(root, "config.json"), encoding="utf-8") as fh:
            row = json.load(fh)["permissions"]["installs"]
        self.assertEqual((row["answer"], row["words"]), ("yes", "I changed my mind"))

    def test_a_yes_can_be_withdrawn(self):
        root, repo = self.make_root(FILES, confirm=False)
        run(root, "grant", "installs", "yes", "--words", "test")
        self.assertEqual(run(root, "grant", "installs", "no", "--words", "test")[0], 0)

    def test_grant_records_words_bounds_and_time(self):
        root, repo = self.make_root(FILES, confirm=False)
        code, out, err = run(root, "grant", "tracker_issues", "yes", "--words", "go ahead, 5 at most",
                             "--bound", "repos=svc,web", "--bound", "max_count=5")
        self.assertEqual(code, 0, err)
        with open(os.path.join(root, "config.json"), encoding="utf-8") as fh:
            row = json.load(fh)["permissions"]["tracker_issues"]
        self.assertEqual(row["answer"], "yes")
        self.assertEqual(row["words"], "go ahead, 5 at most")
        self.assertEqual(row["bounds"], {"repos": ["svc", "web"], "max_count": 5})
        self.assertRegex(row["at"], r"^\d{4}-\d\d-\d\dT")

    def test_grant_bounds_parse(self):
        self.assertEqual(parse_bounds(["repos=a, b", "repos=c", "max_count=3", "instance=work", "mode=each"]),
                         {"repos": ["a", "b", "c"], "max_count": 3, "instance": "work", "mode": "each"})
        self.assertEqual(parse_bounds(["labels=x", "assignees=ana", "kinds=file", "sources=docs",
                                       "targets=host1", "commands=ls"]),
                         {"labels": ["x"], "assignees": ["ana"], "kinds": ["file"], "sources": ["docs"],
                          "targets": ["host1"], "commands": ["ls"]})
        self.assertEqual(parse_bounds(None), {})

    def test_grant_bounds_parse_refuses_bad_input(self):
        for bad in (["repos"], ["colour=red"], ["max_count=many"], ["max_count=-1"]):
            with self.assertRaises(CrucibleError, msg=bad):
                parse_bounds(bad)

    def test_grant_refuses_an_unknown_group(self):
        root, repo = self.make_root(FILES, confirm=False)
        with self.assertRaises(CrucibleError):
            grant(Root(root), "tracker_wishes", "yes")


class ApproveTests(PermissionCase):
    def test_apply_needs_approved_plan_hash(self):
        root = self.granted(auto_file="false")
        record_dryrun(Root(root), "abc12345")
        self.refused(lambda: require_approved(Root(root), "abc12345"), "not approved", "crucible approve abc12345")
        self.assertEqual(run(root, "approve", "abc12345")[0], 0)
        require_approved(Root(root), "abc12345")

    def test_apply_with_a_wrong_hash_is_refused(self):
        root = self.granted(auto_file="false")
        record_dryrun(Root(root), "abc12345")
        self.assertEqual(run(root, "approve", "abc12345")[0], 0)
        self.refused(lambda: require_approved(Root(root), "ffff0000"), "not approved")
        self.assertEqual(self.log_rows(root)[-1]["status"], "refused")

    def test_apply_needs_no_approval_when_auto_file_is_true(self):
        root = self.granted(auto_file="true")
        require_approved(Root(root), "abc12345")

    def test_approve_refuses_a_value_that_is_not_a_hash(self):
        root = self.granted()
        code, out, err = run(root, "approve", "yes please")
        self.assertEqual(code, 1)
        self.assertIn("not a plan hash", err)

    def test_approving_twice_keeps_one_row(self):
        root = self.granted()
        record_dryrun(Root(root), "abc12345")
        run(root, "approve", "abc12345")
        run(root, "approve", "abc12345")
        with open(os.path.join(root, "approvals.json"), encoding="utf-8") as fh:
            self.assertEqual(len(json.load(fh)), 1)

    def test_a_changed_plan_needs_a_new_approval(self):
        root = self.granted()
        record_dryrun(Root(root), "abc12345")
        run(root, "approve", "abc12345")
        self.refused(lambda: require_approved(Root(root), "abc12346"))

    def test_approve_unknown_hash_refused(self):
        root = self.granted(auto_file="false")
        code, out, err = run(root, "approve", "abc12345")
        self.assertEqual(code, 1)
        self.assertIn("no `file --dry-run` produced plan abc12345", err)
        self.assertFalse(os.path.exists(os.path.join(root, "approvals.json")))
        self.refused(lambda: require_approved(Root(root), "abc12345"), "not approved")
        record_dryrun(Root(root), "abc12345")
        self.assertEqual(run(root, "approve", "abc12345")[0], 0)


class ActionLogTests(PermissionCase):
    def test_every_outward_action_logged(self):
        root = self.granted({"tracker_issues": ["repos=svc", "max_count=2"]})
        calls = []
        result = run_action(Root(root), "tracker_issues", "gh issue create --repo svc",
                            lambda: calls.append(1) or "https://example.test/1", repos=["svc"], count=1)
        self.assertEqual(result, "https://example.test/1")
        self.refused(lambda: run_action(Root(root), "tracker_issues", "gh issue create --repo ops",
                                        lambda: calls.append(2), repos=["ops"]))
        self.assertEqual(calls, [1], "the refused action never ran")
        rows = self.log_rows(root)
        self.assertEqual([r["status"] for r in rows], ["ok", "refused"])
        for row in rows:
            self.assertEqual(sorted(row), ["at", "command", "group", "result", "status"])
        self.assertEqual(rows[0]["result"], "https://example.test/1")

    def test_a_failed_action_is_logged_and_the_error_propagates(self):
        root = self.granted({"live_checks": ["targets=host1"]})

        def boom():
            raise RuntimeError("connection refused")

        with self.assertRaises(RuntimeError):
            run_action(Root(root), "live_checks", "probe host1", boom, targets=["host1"])
        row = self.log_rows(root)[-1]
        self.assertEqual(row["status"], "failed")
        self.assertIn("connection refused", row["result"])

    def test_secrets_are_masked_in_the_log(self):
        root = self.granted({"tracker_comments": []})
        token = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4"
        hexkey = "0123456789abcdef0123456789abcdef"
        log_action(Root(root), "tracker_comments", f"gh api -H 'Authorization: token {token}'",
                   f"key {hexkey} seen", "ok")
        text = self.read_text(os.path.join(root, "actions.log"))
        self.assertNotIn(token, text)
        self.assertNotIn(hexkey, text)
        self.assertIn("<masked>", text)

    def test_log_that_cannot_be_written_refuses_the_action(self):
        root = self.granted({"tracker_issues": ["repos=svc", "max_count=1"]})
        os.makedirs(os.path.join(root, "actions.log"))
        calls = []
        self.refused(lambda: run_action(Root(root), "tracker_issues", "file", lambda: calls.append(1),
                                        repos=["svc"], count=1), "cannot write", "not taken")
        self.assertEqual(calls, [], "the action did not run")

    def test_log_action_raises_when_the_log_cannot_be_written(self):
        root = self.granted()
        os.makedirs(os.path.join(root, "actions.log"))
        with self.assertRaises(CrucibleError):
            log_action(Root(root), "installs", "x", "y", "ok")

    def test_log_status_must_be_known(self):
        root = self.granted()
        with self.assertRaises(CrucibleError):
            log_action(Root(root), "installs", "x", "y", "maybe")

    def test_mask_secrets_keeps_ordinary_text_and_git_shas(self):
        sha = "9fceb02d0ae598e95dc970b74767f19372d61af1"
        text = f"commit {sha} in src/handlers/request_handler.py"
        self.assertEqual(mask_secrets(text), text)

    def test_mask_secrets_masks_every_key_shape(self):
        shapes = ["sk-" + "a" * 24, "AKIA" + "A" * 16, "-----BEGIN RSA PRIVATE KEY-----",
                  "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0", "aB3" * 16]
        for shape in shapes:
            self.assertNotIn(shape, mask_secrets(f"value {shape} end"), shape)
            self.assertIn("<masked>", mask_secrets(f"value {shape} end"))


class ReportTests(PermissionCase):
    def test_report_lists_refused_actions(self):
        root = self.granted({"tracker_issues": ["repos=svc", "max_count=1"]})
        run_action(Root(root), "tracker_issues", "gh issue create --repo svc", lambda: "created",
                   repos=["svc"], count=1)
        self.refused(lambda: authorize(Root(root), "tracker_issues", "gh issue create --repo ops", repos=["ops"]))
        log_action(Root(root), "knowledge_sources", "fetch wiki", "unreachable: export it as a folder", "skipped")
        code, out, err = run(root, "report")
        self.assertEqual(code, 0, err)
        self.assertIn("actions taken: 1", out)
        self.assertIn("gh issue create --repo svc", out)
        self.assertIn("actions refused or skipped: 2", out)
        self.assertIn("gh issue create --repo ops", out)
        self.assertIn("repos ops not granted", out)
        self.assertIn("unreachable: export it as a folder", out)

    def test_report_shows_coverage_and_tokens(self):
        root = self.granted()
        code, out, err = run(root, "report")
        self.assertEqual(code, 0, err)
        self.assertIn("coverage: 0 of 0 units done", out)
        self.assertIn("tokens: 0 of no cap", out)

    def test_report_reads_sources_absorbed_and_not_absorbed_from_state(self):
        root = self.granted()
        state = Root(root).state()
        state["knowledge"] = {"wiki": {"status": "absorbed", "count": 12},
                              "chat": {"status": "skipped", "reason": "unreachable; export a zip"}}
        Root(root).save_state(state)
        code, out, err = run(root, "report")
        self.assertIn("knowledge sources absorbed: 1", out)
        self.assertIn("wiki: 12 documents", out)
        self.assertIn("knowledge sources not absorbed: 1", out)
        self.assertIn("chat: unreachable; export a zip", out)

    def test_report_needs_a_confirmed_config(self):
        root, repo = self.make_root(FILES, confirm=False)
        code, out, err = run(root, "report")
        self.assertEqual(code, 1)
        self.assertIn("config not confirmed", err)

    def test_report_with_no_log_says_nothing_was_done(self):
        root = self.granted()
        code, out, err = run(root, "report")
        self.assertIn("actions taken: 0", out)
        self.assertIn("actions refused or skipped: 0", out)


class PlanTests(PermissionCase):
    def test_plan_lists_every_group_with_its_state_and_where_data_goes(self):
        root = self.granted({"tracker_issues": ["repos=svc", "max_count=2"]})
        code, out, err = run(root, "plan")
        self.assertEqual(code, 0, err)
        for group in GROUPS:
            self.assertIn(group + ":", out)
        self.assertIn("tracker_issues: yes", out)
        self.assertIn("bounds: repos=svc; max_count=2", out)
        self.assertIn("model provider", out)
        self.assertIn("dry run first", out)

    def test_plan_hash_changes_when_a_grant_changes(self):
        root = self.granted()
        first = run(root, "plan")[1].strip().splitlines()[-1]
        again = run(root, "plan")[1].strip().splitlines()[-1]
        self.assertEqual(first, again)
        root2 = self.granted({"installs": []})
        self.assertNotEqual(first, run(root2, "plan")[1].strip().splitlines()[-1])

    def test_plan_works_before_confirm(self):
        root, repo = self.make_root(FILES, confirm=False)
        code, out, err = run(root, "plan")
        self.assertEqual(code, 0, err)
        self.assertIn("local_reads: not answered", out)


class LsRemoteGrantTests(PermissionCase):
    def test_ls_remote_refuses_without_grant(self):
        from unittest import mock

        from cruciblelib import clones
        root = self.granted()
        with mock.patch("subprocess.run") as spawned:
            branch = clones.ls_remote_branch(Root(root), "https://example.invalid/a/b.git")
        self.assertEqual(branch, "unknown (not looked up: no workspace_clones permission)")
        spawned.assert_not_called()

    def test_ls_remote_runs_behind_the_grant(self):
        from unittest import mock

        from cruciblelib import clones
        root = self.granted({"workspace_clones": ["repos=a"]})
        done = mock.Mock(stdout="ref: refs/heads/main\tHEAD\n")
        with mock.patch("subprocess.run", return_value=done) as spawned:
            branch = clones.ls_remote_branch(Root(root), "https://example.invalid/a/b.git")
        self.assertEqual(branch, "main")
        self.assertEqual(spawned.call_args[0][0][:3], ["git", "ls-remote", "--symref"])
