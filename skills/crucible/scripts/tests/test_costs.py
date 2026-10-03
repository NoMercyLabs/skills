import json
import os
import time

from cruciblelib.common import CrucibleError, Root
from cruciblelib.costs import apply_move, find_costs
from cruciblelib.permissions import read_log

from .helpers import CrucibleCase, run
from .test_transcripts import OUTPUT, PROMPT, REPLY

DAY = 86400
RULES = "# Rules\n\nBe kind.\n\n"
RELEASE = "## Release steps\n\n" + "Tag, build, sign and upload the artifacts by hand. " * 160 + "\n"
USER_FILE = "# Mine\n\n" + "A long personal rule. " * 200 + "\n"


def turn(repo, index, model="model-small", tokens=100, tool=None, output="", error=False, sidechain=False):
    """An assistant row with usage, a tool call, and the result row of that call."""
    block = {"type": "text", "text": REPLY}
    rows = []
    content = [block]
    if tool:
        name, payload = tool
        content.append({"type": "tool_use", "id": f"t{index}", "name": name, "input": payload})
    message = {"id": f"m{index}", "role": "assistant", "model": model, "content": content,
               "usage": {"input_tokens": tokens, "output_tokens": 10}}
    rows.append({"type": "assistant", "cwd": repo, "isSidechain": sidechain, "message": message})
    if tool:
        part = {"type": "tool_result", "tool_use_id": f"t{index}", "content": output or OUTPUT}
        if error:
            part["is_error"] = True
            part["content"] = "Exit code 2\nboom"
        rows.append({"type": "user", "message": {"role": "user", "content": [part]}})
    return rows


class CostsCase(CrucibleCase):
    def setup_audit(self, files=None, grant="yes"):
        root, repo = self.make_root(files or {"CLAUDE.md": RULES + RELEASE})
        if grant == "yes":
            self.assertEqual(run(root, "grant", "transcripts", "yes", "--words", "test", "--bound", "repos=svc",
                                 "--reopen")[0], 0)
        return Root(root), root, repo

    def folder(self, *sessions, ages=None):
        """One transcript file per list of rows; ages are days old."""
        folder = self.tmp()
        for index, rows in enumerate(sessions):
            path = os.path.join(folder, f"s{index}.jsonl")
            with open(path, "w", encoding="utf-8") as fh:
                for row in rows:
                    fh.write(json.dumps(row) + "\n")
            if ages:
                moment = time.time() - ages[index] * DAY
                os.utime(path, (moment, moment))
        return folder

    def session(self, repo, **kw):
        return turn(repo, 0, tool=("Bash", {"command": "ls"}), **kw)


class Grant(CostsCase):
    def test_costs_needs_transcript_grant(self):
        root, path, repo = self.setup_audit(grant="none")
        with self.assertRaises(CrucibleError):
            find_costs(root, self.folder(self.session(repo)), ["svc"])

    def test_costs_refused_after_a_no(self):
        root, path, repo = self.setup_audit(grant="none")
        with self.assertRaises(CrucibleError):
            find_costs(root, self.folder(), ["svc"])
        self.assertEqual(read_log(root)[-1]["status"], "refused")

    def test_the_user_wide_file_needs_its_own_grant(self):
        root, path, repo = self.setup_audit()
        user = os.path.join(self.tmp(), "CLAUDE.md")
        with open(user, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(USER_FILE)
        folder = self.folder(self.session(repo))
        with self.assertRaises(CrucibleError):
            find_costs(root, folder, ["svc"], user_file=user)
        self.assertEqual(run(path, "grant", "user_instructions", "yes", "--words", "test", "--bound",
                             f"targets={user}", "--reopen")[0], 0)
        found = find_costs(root, folder, ["svc"], user_file=user)
        self.assertGreater(found["user_file"]["tokens"], 0)


class Measure(CostsCase):
    def test_costs_reads_usage_not_content(self):
        root, path, repo = self.setup_audit()
        rows = [{"type": "user", "cwd": repo, "message": {"role": "user", "content": PROMPT}}]
        rows += turn(repo, 0, tokens=900, tool=("Read", {"file_path": "a.py"}), output="x" * 60000)
        rows += turn(repo, 1, tokens=400, tool=("Bash", {"command": "ls"}))
        found = find_costs(root, self.folder(rows), ["svc"])
        self.assertEqual((found["sessions"], found["turns"], found["tokens"]), (1, 2, 1320))
        self.assertEqual(found["large_outputs"], {"count": 1, "tokens": 15000})
        text = json.dumps(found)
        for private in (PROMPT, REPLY, OUTPUT, "a.py"):
            self.assertNotIn(private, text)

    def test_sessions_outside_the_scope_are_not_counted(self):
        root, path, repo = self.setup_audit()
        other = os.path.join(self.tmp(), "elsewhere")
        found = find_costs(root, self.folder(self.session(repo), self.session(other)), ["svc"])
        self.assertEqual(found["sessions"], 1)

    def test_failures_agents_and_models_are_measured(self):
        root, path, repo = self.setup_audit()
        rows = turn(repo, 0, tool=("Bash", {"command": "make 1"}), error=True)
        rows += turn(repo, 1, tool=("Bash", {"command": "make 2"}))
        rows += turn(repo, 2, model="model-big", tokens=500, tool=("Task", {"prompt": "x"}), output="42")
        side = turn(repo, 9, tokens=3000, sidechain=True)
        found = find_costs(root, self.folder(rows, side), ["svc"])
        self.assertEqual((found["failed"], found["retried"]), (1, 1))
        self.assertEqual(found["agents"], {"starts": 1, "short_answers": 1, "start_tokens": 3010})
        self.assertEqual(found["models"]["model-big"], {"turns": 1, "tokens": 510})
        self.assertEqual(found["models"]["model-small"]["turns"], 3)


class Instructions(CostsCase):
    def test_always_loaded_instructions_measured(self):
        root, path, repo = self.setup_audit()
        found = find_costs(root, self.folder(self.session(repo), self.session(repo)), ["svc"])
        size = len(RULES + RELEASE)
        row = found["instructions"][0]
        self.assertEqual((row["file"], row["tokens"]), ("CLAUDE.md", size // 4))
        self.assertEqual(found["always_loaded"], 2 * (size // 4))

    def test_the_user_wide_file_counts_when_granted(self):
        root, path, repo = self.setup_audit()
        user = os.path.join(self.tmp(), "CLAUDE.md")
        with open(user, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(USER_FILE)
        run(path, "grant", "user_instructions", "yes", "--words", "test", "--bound", f"targets={user}", "--reopen")
        found = find_costs(root, self.folder(self.session(repo)), ["svc"], user_file=user)
        self.assertEqual(found["user_file"]["tokens"], len(USER_FILE) // 4)
        self.assertEqual(found["always_loaded"], len(RULES + RELEASE) // 4 + len(USER_FILE) // 4)


class Proposals(CostsCase):
    def test_proposal_has_measured_saving(self):
        root, path, repo = self.setup_audit()
        folder = self.folder(self.session(repo), self.session(repo), ages=[14, 0])
        found = find_costs(root, folder, ["svc"])
        moves = [p for p in found["proposals"] if p["kind"] == "move_section"]
        self.assertEqual([m["heading"] for m in moves], ["Release steps"])
        size = len(RELEASE) // 4
        self.assertEqual((moves[0]["tokens_per_session"], moves[0]["tokens_per_week"]), (size, size))
        self.assertTrue(moves[0]["target"].endswith("release-steps.md"))

    def test_prompt_lines_are_proposed_only_with_a_measured_saving(self):
        root, path, repo = self.setup_audit(files={"CLAUDE.md": RULES})
        quiet = find_costs(root, self.folder(self.session(repo)), ["svc"])
        self.assertEqual(quiet["proposals"], [])
        rows = turn(repo, 0, tool=("Read", {"file_path": "big.log"}), output="x" * 80000)
        loud = find_costs(root, self.folder(rows), ["svc"])
        lines = [p for p in loud["proposals"] if p["kind"] == "prompt_line"]
        self.assertEqual(len(lines), 1)
        self.assertIn("output", lines[0]["line"])
        self.assertEqual(lines[0]["tokens_per_session"], 15000)

    def test_the_command_prints_the_proposals_and_changes_nothing(self):
        root, path, repo = self.setup_audit()
        folder = self.folder(self.session(repo))
        with open(os.path.join(repo, "CLAUDE.md"), encoding="utf-8") as fh:
            before = fh.read()
        code, out, err = run(path, "costs", "--transcripts", folder)
        self.assertEqual(code, 0, err)
        self.assertIn("Release steps", out)
        self.assertIn("tokens per session", out)
        with open(os.path.join(repo, "CLAUDE.md"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), before)


class Moving(CostsCase):
    def test_instruction_text_moved_not_deleted(self):
        root, path, repo = self.setup_audit()
        file = os.path.join(repo, "CLAUDE.md")
        target = apply_move(root, repo, "CLAUDE.md", "Release steps")
        with open(file, encoding="utf-8") as fh:
            left = fh.read()
        with open(os.path.join(repo, target), encoding="utf-8") as fh:
            moved = fh.read()
        self.assertIn(RELEASE.split("\n", 2)[2].strip(), moved)
        self.assertNotIn("Tag, build, sign", left)
        self.assertIn("Be kind.", left)
        self.assertIn(target.replace(os.sep, "/"), left)
        backups = os.listdir(root.p("backups"))
        self.assertEqual(len(backups), 1)
        with open(os.path.join(root.p("backups"), backups[0]), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), RULES + RELEASE)

    def test_a_missing_heading_changes_nothing(self):
        root, path, repo = self.setup_audit()
        with self.assertRaises(CrucibleError):
            apply_move(root, repo, "CLAUDE.md", "No such heading")
        with open(os.path.join(repo, "CLAUDE.md"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), RULES + RELEASE)

    def test_the_command_moves_only_what_the_user_names(self):
        root, path, repo = self.setup_audit()
        code, out, err = run(path, "costs", "move", "--repo", "svc", "--file", "CLAUDE.md", "--heading", "Release steps")
        self.assertEqual(code, 0, err)
        self.assertIn("release-steps.md", out)
        self.assertEqual(run(path, "costs", "move", "--repo", "nope", "--file", "CLAUDE.md", "--heading", "x")[0], 1)


class BeforeAfter(CostsCase):
    def test_before_after_compared(self):
        root, path, repo = self.setup_audit()
        folder = self.folder(self.session(repo, tokens=1000))
        self.assertEqual(run(path, "costs", "--transcripts", folder)[0], 0)
        apply_move(root, repo, "CLAUDE.md", "Release steps")
        with open(os.path.join(repo, "CLAUDE.md"), encoding="utf-8") as fh:
            saved = len(RULES + RELEASE) // 4 - len(fh.read()) // 4
        later = self.folder(self.session(repo, tokens=400))
        code, out, err = run(path, "costs", "--transcripts", later)
        self.assertEqual(code, 0, err)
        self.assertIn(f"always-loaded tokens per session: saved {saved}", out)
        self.assertIn("tokens per session: saved 600", out)

    def test_a_proposal_that_saved_nothing_is_reported_as_such(self):
        root, path, repo = self.setup_audit()
        folder = self.folder(self.session(repo, tokens=500))
        run(path, "costs", "--transcripts", folder)
        code, out, err = run(path, "costs", "--transcripts", folder)
        self.assertEqual(code, 0, err)
        self.assertIn("saved nothing", out)

    def test_the_first_run_has_nothing_to_compare(self):
        root, path, repo = self.setup_audit()
        code, out, err = run(path, "costs", "--transcripts", self.folder(self.session(repo)))
        self.assertEqual(code, 0, err)
        self.assertNotIn("saved", out)
