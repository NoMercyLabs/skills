import json
import os

from cruciblelib.common import CrucibleError, Root
from cruciblelib.permissions import GROUPS, read_log
from cruciblelib.transcripts import scoped_commands

from .helpers import CrucibleCase, run

PROMPT = "PRIVATE-PROMPT-TEXT please never copy this"
REPLY = "PRIVATE-ASSISTANT-TEXT thinking aloud"
OUTPUT = "PRIVATE-TOOL-OUTPUT lines"


def use(cwd, tool_id, command, name="Bash"):
    return {"type": "assistant", "cwd": cwd, "message": {"role": "assistant", "content": [
        {"type": "text", "text": REPLY},
        {"type": "tool_use", "id": tool_id, "name": name, "input": {"command": command, "description": "x"}}]}}


def result(tool_id, text=OUTPUT, is_error=None):
    part = {"type": "tool_result", "tool_use_id": tool_id, "content": text}
    if is_error is not None:
        part["is_error"] = is_error
    return {"type": "user", "message": {"role": "user", "content": [part]}}


class TranscriptScope(CrucibleCase):
    def setup_audit(self, grant="yes", bounds=("repos=svc",)):
        root, repo = self.make_root({"app.py": "x = 1\n"})
        flags = [x for b in bounds for x in ("--bound", b)] + (["--reopen"] if grant == "yes" else [])
        self.assertEqual(run(root, "grant", "transcripts", grant, "--words", "test", *flags)[0], 0)
        return Root(root), repo

    def write(self, rows, raw=()):
        path = os.path.join(self.tmp(), "agent.jsonl")
        with open(path, "w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row) + "\n")
            for line in raw:
                fh.write(line + "\n")
        return path

    def test_the_group_exists_and_is_asked(self):
        self.assertIn("transcripts", GROUPS)

    def test_refused_without_a_grant(self):
        root, repo = self.make_root({"app.py": "x = 1\n"})
        path = self.write([use(repo, "t1", "ls"), result("t1")])
        with self.assertRaises(CrucibleError):
            scoped_commands(Root(root), path, ["svc"])

    def test_refused_after_a_no(self):
        root, repo = self.setup_audit(grant="no", bounds=())
        with self.assertRaises(CrucibleError):
            scoped_commands(root, self.write([]), ["svc"])
        self.assertEqual(read_log(root)[-1]["status"], "refused")

    def test_refused_for_a_repo_not_in_the_granted_bounds(self):
        root, repo = self.setup_audit(bounds=("repos=other",))
        with self.assertRaises(CrucibleError):
            scoped_commands(root, self.write([]), ["svc"])

    def test_refused_for_a_repo_not_in_the_scope(self):
        root, repo = self.setup_audit(bounds=("repos=svc,ghost",))
        with self.assertRaises(CrucibleError) as caught:
            scoped_commands(root, self.write([]), ["ghost"])
        self.assertIn("not in scope", str(caught.exception))

    def test_only_commands_run_inside_the_repo_folder_are_kept(self):
        root, repo = self.setup_audit()
        elsewhere = os.path.join(self.tmp(), "other-project")
        rows = [use(repo, "t1", "make build"), result("t1"),
                use(os.path.join(repo, "sub"), "t2", "ls sub"), result("t2"),
                use(elsewhere, "t3", "cat notes"), result("t3"),
                use(repo + "-sibling", "t4", "echo sibling"), result("t4")]
        found = scoped_commands(root, self.write(rows), ["svc"])
        self.assertEqual([c["command"] for c in found], ["make build", "ls sub"])

    def test_exit_status_comes_from_the_result(self):
        root, repo = self.setup_audit()
        rows = [use(repo, "t1", "ok"), result("t1", is_error=False),
                use(repo, "t2", "boom"), result("t2", "Exit code 2\nsome stderr", is_error=True),
                use(repo, "t3", "no-result"),
                use(repo, "t4", "plain", name="PowerShell"), result("t4")]
        found = scoped_commands(root, self.write(rows), ["svc"])
        self.assertEqual([(c["command"], c["exit"]) for c in found],
                         [("ok", 0), ("boom", 2), ("no-result", None), ("plain", 0)])

    def test_nothing_but_command_and_exit_comes_back(self):
        root, repo = self.setup_audit()
        rows = [{"type": "user", "cwd": repo, "message": {"role": "user", "content": PROMPT}},
                use(repo, "t1", "ls"), result("t1", OUTPUT + "\nExit code 1", is_error=True)]
        found = scoped_commands(root, self.write(rows), ["svc"])
        self.assertEqual(found, [{"command": "ls", "exit": 1}])
        text = json.dumps(found)
        for private in (PROMPT, REPLY, OUTPUT):
            self.assertNotIn(private, text)

    def test_tools_that_are_not_a_shell_are_ignored(self):
        root, repo = self.setup_audit()
        rows = [use(repo, "t1", "/etc/hosts", name="Read"), result("t1")]
        self.assertEqual(scoped_commands(root, self.write(rows), ["svc"]), [])

    def test_a_secret_in_a_command_is_masked(self):
        root, repo = self.setup_audit()
        token = "ghp_" + "a1B2c3D4e5" * 3
        rows = [use(repo, "t1", f"curl -H 'Authorization: {token}' x"), result("t1")]
        found = scoped_commands(root, self.write(rows), ["svc"])
        self.assertNotIn(token, found[0]["command"])
        self.assertIn("<masked>", found[0]["command"])

    def test_lines_that_are_not_json_are_skipped(self):
        root, repo = self.setup_audit()
        path = self.write([use(repo, "t1", "ls"), result("t1")], raw=["not json at all", "{broken"])
        self.assertEqual([c["command"] for c in scoped_commands(root, path, ["svc"])], ["ls"])

    def test_a_read_is_logged(self):
        root, repo = self.setup_audit()
        scoped_commands(root, self.write([use(repo, "t1", "ls"), result("t1")]), ["svc"])
        last = read_log(root)[-1]
        self.assertEqual((last["group"], last["status"]), ("transcripts", "ok"))
