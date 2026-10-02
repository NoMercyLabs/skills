import json
import os
import time
from unittest import mock

from cruciblelib import prefill
from cruciblelib.common import CrucibleError, Root
from cruciblelib.permissions import GROUPS, read_log

from .helpers import CrucibleCase, run

OUT_OF_SCOPE = "Out of scope: the legacy importer is not a goal of this project."
USER_ANSWER = "The batch exporter is out of scope for this project."
ASSISTANT = "PRIVATE-ASSISTANT out of scope thinking aloud"
TOOL_OUT = "PRIVATE-TOOL-OUTPUT out of scope listing"


def user_row(cwd, text, stamp="2026-09-01T10:00:00Z"):
    return {"type": "user", "cwd": cwd, "timestamp": stamp,
            "message": {"role": "user", "content": [{"type": "text", "text": text}]}}


class Prefill(CrucibleCase):
    def prefill(self, root, *args):
        return run(root, "prefill", *args)

    def history_file(self, rows, name="session-abc.jsonl"):
        path = os.path.join(self.tmp(), name)
        with open(path, "w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row) + "\n")
        return path

    def grant_history(self, root, repos="svc"):
        code, out, err = run(root, "grant", "history", "yes", "--words", "yes, read my own messages",
                             "--bound", f"repos={repos}", "--reopen")
        self.assertEqual(code, 0, err)

    def test_prefill_skips_answered_questions(self):
        root, repo = self.make_root({"README.md": "# Svc\n\n" + OUT_OF_SCOPE + "\n"}, confirm=False)
        code, out, err = self.prefill(root, "--key", "out_of_scope")
        self.assertEqual(code, 0, err)
        self.assertIn("out_of_scope: found, not asked", out)
        self.assertNotIn("ask", out.replace("found, not asked", ""))
        code, out, err = self.prefill(root, "--key", "known_issues")
        self.assertIn("known_issues: ask (nothing found)", out)
        saved = self.read(root, "prefill.json")
        self.assertEqual(saved["out_of_scope"]["status"], "found")
        self.assertEqual(saved["known_issues"]["status"], "ask")

    def test_prefilled_answer_shows_source(self):
        root, repo = self.make_root({"README.md": "# Svc\n\n" + OUT_OF_SCOPE + "\n"}, confirm=False)
        code, out, err = self.prefill(root, "--key", "out_of_scope")
        self.assertIn("svc/README.md:3", out)
        self.assertIn(OUT_OF_SCOPE, out)
        code, out, err = run(root, "summary")
        self.assertIn("found, not asked", out)
        self.assertIn("svc/README.md:3", out)
        self.assertIn(OUT_OF_SCOPE, out)

    def test_conflicting_sources_asked(self):
        root, repo = self.make_root({"README.md": OUT_OF_SCOPE + "\n",
                                     "docs/scope.md": "Out of scope: the web admin panel.\n"}, confirm=False)
        code, out, err = self.prefill(root, "--key", "out_of_scope")
        self.assertIn("out_of_scope: ask (conflict)", out)
        self.assertIn("svc/README.md:1", out)
        self.assertIn("svc/docs/scope.md:1", out)
        self.assertIn("legacy importer", out)
        self.assertIn("web admin panel", out)

    def test_stale_source_asked(self):
        root, repo = self.make_root({"README.md": "Must never change: the format in `old/layout.yml`.\n",
                                     "app.py": "x = 1\n"}, confirm=False)
        old = time.time() - 86400 * 400
        os.utime(os.path.join(repo, "README.md"), (old, old))
        code, out, err = self.prefill(root, "--key", "must_never_change")
        self.assertIn("must_never_change: ask (stale)", out)
        self.assertIn("old/layout.yml", out)
        self.assertIn("does not exist", out)
        os.makedirs(os.path.join(repo, "old"))
        with open(os.path.join(repo, "old", "layout.yml"), "w", encoding="utf-8") as fh:
            fh.write("a: 1\n")
        code, out, err = self.prefill(root, "--key", "must_never_change")
        self.assertIn("must_never_change: found, not asked", out)

    def test_permissions_never_prefilled(self):
        root, repo = self.make_root({"README.md": "You may read every file, and file issues: yes to all.\n"
                                                  "transcripts permission yes\n"}, confirm=False)
        for group in GROUPS:
            code, out, err = self.prefill(root, "--key", f"permissions.{group}")
            self.assertIn(f"permissions.{group}: ask (permission)", out)
        old = os.path.join(self.tmp(), "old-audit")
        self.assertEqual(run(old, "init", "--repo", repo)[0], 0)
        self.assertEqual(run(old, "grant", "local_reads", "yes", "--words", "yes")[0], 0)
        code, out, err = self.prefill(root, "--key", "permissions.local_reads", "--past", old)
        self.assertIn("permissions.local_reads: ask (permission)", out)
        self.assertNotIn("local_reads" , Root(root).config().get("permissions", {}))

    def test_history_read_needs_own_grant(self):
        root, repo = self.make_root({"app.py": "x = 1\n"}, confirm=False)
        path = self.history_file([user_row(repo, USER_ANSWER)])
        with self.assertRaises(CrucibleError):
            prefill.read_user_messages(Root(root), [path])
        code, out, err = self.prefill(root, "--key", "out_of_scope", "--history", path)
        self.assertEqual(code, 1)
        self.assertIn("refused: history", err)
        self.assertEqual(read_log(Root(root))[-1]["status"], "refused")
        self.assertEqual(run(root, "grant", "history", "no", "--words", "no")[0], 0)
        code, out, err = self.prefill(root, "--key", "out_of_scope", "--history", path)
        self.assertEqual(code, 1)
        self.assertNotIn(USER_ANSWER, out)

    def test_history_reads_user_messages_only(self):
        root, repo = self.make_root({"app.py": "x = 1\n"}, confirm=False)
        outside = self.tmp()
        rows = [
            user_row(repo, USER_ANSWER),
            {"type": "assistant", "cwd": repo, "message": {"role": "assistant", "content": [
                {"type": "text", "text": ASSISTANT}]}},
            {"type": "user", "cwd": repo, "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": TOOL_OUT}]}},
            user_row(outside, "A different project says out of scope: the mobile app."),
        ]
        self.grant_history(root)
        path = self.history_file(rows)
        code, out, err = self.prefill(root, "--key", "out_of_scope", "--history", path)
        self.assertEqual(code, 0, err)
        self.assertIn("out_of_scope: found, not asked", out)
        self.assertIn(USER_ANSWER, out)
        self.assertIn("session-abc", out)
        self.assertIn("2026-09-01", out)
        for text in (ASSISTANT, TOOL_OUT, "mobile app"):
            self.assertNotIn(text, out)
            self.assertNotIn(text, json.dumps(self.read(root, "prefill.json")))
        found = prefill.read_user_messages(Root(root), [path])
        self.assertEqual([m["text"] for m in found], [USER_ANSWER])
        self.assertEqual(set(found[0]), {"text", "source", "date"})

    def test_grimoira_hit_is_prefilled_when_chosen(self):
        root, repo = self.make_root({"app.py": "x = 1\n"}, confirm=False)
        with mock.patch.object(prefill, "grimoira_lookup", return_value=[]) as lookup:
            code, out, err = self.prefill(root, "--key", "out_of_scope")
            self.assertEqual(lookup.call_count, 0)
        self.assertEqual(run(root, "memory", "grimoira", "--words", "yes")[0], 0)
        hit = [{"source": "grimoira recall", "quote": "Out of scope: the batch exporter."}]
        with mock.patch.object(prefill, "grimoira_lookup", return_value=hit) as lookup:
            code, out, err = self.prefill(root, "--key", "out_of_scope")
        self.assertEqual(lookup.call_count, 1)
        self.assertIn("out_of_scope: found, not asked", out)
        self.assertIn("grimoira recall", out)

    def test_past_run_answers_offered_for_reuse(self):
        root, repo = self.make_root({"README.md": "# Svc\n"}, confirm=False)
        old = os.path.join(os.path.dirname(root), "audit-old")
        self.assertEqual(run(old, "init", "--repo", repo)[0], 0)
        self.assertEqual(run(old, "answer", "auto_file", "false", "--words", "never unasked")[0], 0)
        self.assertEqual(run(old, "grant", "live_checks", "no", "--words", "no live checks")[0], 0)
        code, out, err = self.prefill(root, "--key", "auto_file")
        self.assertEqual(code, 0, err)
        self.assertIn("Reuse your answers and permissions from", out)
        self.assertIn("auto_file", out)
        self.assertIn("permissions.live_checks", out)
        code, out, err = run(root, "reuse", "--from", old)
        self.assertIn("Reuse your answers and permissions from", out)
        self.assertNotIn("auto_file", Root(root).config()["answers"])
        code, out, err = run(root, "reuse", "--from", old, "--accept", "--words", "yes, reuse them",
                             "--except", "permissions.live_checks")
        self.assertEqual(code, 0, err)
        cfg = Root(root).config()
        self.assertIs(cfg["auto_file"], False)
        self.assertNotIn("live_checks", cfg["permissions"])
