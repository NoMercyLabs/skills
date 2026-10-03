import json
import os

from cruciblelib.common import CrucibleError, Root
from cruciblelib.permissions import read_log
from cruciblelib.repeats import find_repeats, script_standard_checked, shape_of

from .helpers import CrucibleCase, run
from .test_transcripts import OUTPUT, PROMPT, REPLY, result, use

GOOD_SCRIPT = """#!/bin/sh
# one trigger: ./scripts/deploy.sh [--dry-run]
DRY=0
[ "$1" = "--dry-run" ] && DRY=1
cp config.yml config.yml.bak
[ "$DRY" = 1 ] || echo "deploy" > out.txt
if grep -q deploy out.txt; then echo "PASS: deployed"; else echo "FAIL: not deployed"; exit 1; fi
"""


class RepeatsCase(CrucibleCase):
    def setup_audit(self, grant="yes"):
        root, repo = self.make_root({"app.py": "x = 1\n"})
        flags = ["--bound", "repos=svc", "--reopen"] if grant == "yes" else []
        self.assertEqual(run(root, "grant", "transcripts", grant, "--words", "test", *flags)[0], 0)
        return Root(root), root, repo

    def folder(self, *transcripts):
        """One transcript file per list of rows."""
        folder = self.tmp()
        for index, rows in enumerate(transcripts):
            with open(os.path.join(folder, f"s{index}.jsonl"), "w", encoding="utf-8") as fh:
                for row in rows:
                    fh.write(json.dumps(row) + "\n")
        return folder

    def runs(self, repo, commands):
        """Rows for [(command, error?)]: each is one tool call and its result."""
        rows = []
        for index, (command, failed) in enumerate(commands):
            rows += [use(repo, f"t{index}", command),
                     result(f"t{index}", "Exit code 2\nboom" if failed else OUTPUT, is_error=bool(failed) or None)]
        return rows


class ShapeAndGroups(RepeatsCase):
    def test_shape_replaces_paths_ids_and_numbers(self):
        self.assertEqual(shape_of("ls /home/a/b 12"), shape_of("ls C:\\Users\\z\\q 7"))
        self.assertEqual(shape_of("git show 3fa9c2b1d"), shape_of("git show aa00bb11cc22"))
        self.assertEqual(shape_of("git commit -m 'one'"), shape_of('git commit -m "two words"'))
        self.assertNotEqual(shape_of("git push"), shape_of("git pull"))

    def test_repeats_groups_by_shape(self):
        root, path, repo = self.setup_audit()
        rows = self.runs(repo, [("deploy.sh --env staging --port 8080", 0), ("deploy.sh --env staging --port 9090", 0),
                                ("deploy.sh --env staging --port 7070", 0), ("ls", 0), ("ls", 0)])
        found = find_repeats(root, self.folder(rows), ["svc"])
        self.assertEqual([(r["runs"]) for r in found["repeats"]], [3])
        self.assertIn("deploy.sh", found["repeats"][0]["shape"])
        self.assertEqual(found["commands"], 5)

    def test_shapes_run_fewer_than_three_times_are_not_listed(self):
        root, path, repo = self.setup_audit()
        found = find_repeats(root, self.folder(self.runs(repo, [("make a", 0), ("make a", 0)])), ["svc"])
        self.assertEqual(found["repeats"], [])

    def test_runs_in_other_transcripts_add_up(self):
        root, path, repo = self.setup_audit()
        one = self.runs(repo, [("make build", 0), ("make build", 0)])
        two = self.runs(repo, [("make build", 0)])
        found = find_repeats(root, self.folder(one, two), ["svc"])
        self.assertEqual([r["runs"] for r in found["repeats"]], [3])

    def test_commands_outside_the_scope_are_not_counted(self):
        root, path, repo = self.setup_audit()
        elsewhere = os.path.join(self.tmp(), "other-project")
        rows = [use(elsewhere, f"t{i}", "make build") for i in range(4)]
        found = find_repeats(root, self.folder(rows), ["svc"])
        self.assertEqual((found["commands"], found["repeats"]), (0, []))

    def test_transcripts_scoped_to_project_cost_is_measured_from_usage(self):
        root, path, repo = self.setup_audit()
        rows = self.runs(repo, [("make build", 0)] * 3)
        for index, row in enumerate(rows):
            if row["type"] == "assistant":
                row["message"]["id"] = f"m{index}"
                row["message"]["usage"] = {"input_tokens": 100, "output_tokens": 50}
        found = find_repeats(root, self.folder(rows), ["svc"])
        self.assertEqual(found["repeats"][0]["tokens"], 3 * 150)

    def test_cost_is_none_without_usage(self):
        root, path, repo = self.setup_audit()
        found = find_repeats(root, self.folder(self.runs(repo, [("make build", 0)] * 3)), ["svc"])
        self.assertIsNone(found["repeats"][0]["tokens"])

    def test_transcript_reads_commands_only_nothing_private_comes_out(self):
        root, path, repo = self.setup_audit()
        rows = [{"type": "user", "cwd": repo, "message": {"role": "user", "content": PROMPT}}]
        rows += self.runs(repo, [("make build", 0)] * 3)
        text = json.dumps(find_repeats(root, self.folder(rows), ["svc"]))
        for private in (PROMPT, REPLY, OUTPUT):
            self.assertNotIn(private, text)


class FailedRetries(RepeatsCase):
    def test_failed_retry_counted(self):
        root, path, repo = self.setup_audit()
        rows = self.runs(repo, [("deploy.sh 1", 1), ("deploy.sh 2", 1), ("deploy.sh 3", 0), ("deploy.sh 4", 0)])
        row = find_repeats(root, self.folder(rows), ["svc"])["repeats"][0]
        self.assertEqual((row["runs"], row["failed"], row["retried"]), (4, 2, 2))

    def test_a_failure_with_no_later_run_is_not_a_retry(self):
        root, path, repo = self.setup_audit()
        rows = self.runs(repo, [("deploy.sh 1", 0), ("deploy.sh 2", 0), ("deploy.sh 3", 1)])
        row = find_repeats(root, self.folder(rows), ["svc"])["repeats"][0]
        self.assertEqual((row["failed"], row["retried"]), (1, 0))

    def test_a_retry_in_another_transcript_is_not_counted(self):
        root, path, repo = self.setup_audit()
        one = self.runs(repo, [("deploy.sh 1", 1), ("deploy.sh 2", 0)])
        two = self.runs(repo, [("deploy.sh 3", 0)])
        row = find_repeats(root, self.folder(one, two), ["svc"])["repeats"][0]
        self.assertEqual((row["failed"], row["retried"]), (1, 1))


class Grant(RepeatsCase):
    def test_repeats_needs_transcript_grant(self):
        root, repo = self.make_root({"app.py": "x = 1\n"})
        with self.assertRaises(CrucibleError):
            find_repeats(Root(root), self.folder(self.runs(repo, [("ls", 0)])), ["svc"])

    def test_repeats_refused_after_a_no_even_for_an_empty_folder(self):
        root, path, repo = self.setup_audit(grant="no")
        with self.assertRaises(CrucibleError):
            find_repeats(root, self.folder(), ["svc"])
        self.assertEqual(read_log(root)[-1]["status"], "refused")

    def test_the_command_runs_and_prints_counts(self):
        root, path, repo = self.setup_audit()
        folder = self.folder(self.runs(repo, [("make build 1", 1), ("make build 2", 0), ("make build 3", 0)]))
        code, out, err = run(path, "repeats", "--transcripts", folder)
        self.assertEqual(code, 0, err)
        self.assertIn("3 runs", out)
        self.assertIn("1 failed", out)
        self.assertEqual(run(path, "repeats", "--transcripts", folder, "--repo", "nope")[0], 1)


class ScriptStandard(RepeatsCase):
    def script(self, text, test=True, name="deploy.sh"):
        folder = self.tmp()
        path = os.path.join(folder, name)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        if test:
            with open(os.path.join(folder, "test_deploy.sh"), "w", encoding="utf-8") as fh:
                fh.write("# fails before the script exists\n")
        return path, os.path.join(folder, "test_deploy.sh")

    def test_script_standard_checked_passes_a_script_that_meets_it(self):
        path, test = self.script(GOOD_SCRIPT)
        self.assertEqual(script_standard_checked(path, test), [])

    def test_script_standard_checked_names_every_missing_part(self):
        bad = "#!/bin/sh\nread -p 'sure? ' A\nrm -rf /var/data\ncp x /srv/app/x\necho done\n"
        path, _ = self.script(bad, test=False)
        problems = " | ".join(script_standard_checked(path, path + ".missing"))
        for word in ("PASS", "FAIL", "question", "dry-run", "backup", "absolute path", "test"):
            self.assertIn(word, problems)

    def test_script_standard_checked_python_input_is_a_question(self):
        text = GOOD_SCRIPT + "x = input('ok? ')\n"
        path, test = self.script(text, name="job.py")
        self.assertTrue(any("question" in p for p in script_standard_checked(path, test)))

    def test_script_standard_checked_a_read_only_script_needs_no_dry_run_or_backup(self):
        text = "#!/bin/sh\nif ls . >/dev/null; then echo PASS; else echo FAIL; fi\n"
        path, test = self.script(text)
        self.assertEqual(script_standard_checked(path, test), [])


class UnusedScripts(RepeatsCase):
    def index(self, entries):
        path = os.path.join(self.tmp(), "index.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"scripts": entries}, fh)
        return path

    def test_unused_script_reported(self):
        root, path, repo = self.setup_audit()
        rows = self.runs(repo, [("docker compose up -d web", 0)] * 3)
        index = self.index([{"script": "scripts/up.sh", "shape": "docker compose up -d web"}])
        found = find_repeats(root, self.folder(rows), ["svc"], index=index)
        self.assertEqual(found["scripts"], [{"script": "scripts/up.sh", "used": 0, "hand": 3, "unused": True}])

    def test_a_used_script_is_not_reported_unused(self):
        root, path, repo = self.setup_audit()
        rows = self.runs(repo, [("docker compose up -d web", 0), ("sh scripts/up.sh", 0), ("scripts/up.sh --dry-run", 0)])
        index = self.index([{"script": "scripts/up.sh", "shape": "docker compose up -d web"}])
        row = find_repeats(root, self.folder(rows), ["svc"], index=index)["scripts"][0]
        self.assertEqual((row["used"], row["hand"], row["unused"]), (2, 1, False))

    def test_the_command_prints_the_unused_script(self):
        root, path, repo = self.setup_audit()
        folder = self.folder(self.runs(repo, [("docker compose up -d web", 0)] * 3))
        index = self.index([{"script": "scripts/up.sh", "shape": "docker compose up -d web"}])
        code, out, err = run(path, "repeats", "--transcripts", folder, "--scripts", index)
        self.assertEqual(code, 0, err)
        self.assertIn("unused script: scripts/up.sh", out)

    def test_a_bad_index_is_an_error(self):
        root, path, repo = self.setup_audit()
        index = os.path.join(self.tmp(), "index.json")
        with open(index, "w", encoding="utf-8") as fh:
            fh.write("[1]")
        with self.assertRaises(CrucibleError):
            find_repeats(root, self.folder(), ["svc"], index=index)
