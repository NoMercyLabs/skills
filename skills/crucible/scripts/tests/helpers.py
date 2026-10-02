import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest

from cruciblelib import cli
from cruciblelib.common import Root, source_id
from cruciblelib.visibility import required_slugs
from cruciblelib.permissions import GROUPS


def run(root, *args):
    """Run the CLI in-process; returns (exit code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(["--root", root, *args])
    return code, out.getvalue(), err.getvalue()


class CrucibleCase(unittest.TestCase):
    def tmp(self):
        path = tempfile.mkdtemp(prefix="crucible-test-")
        self.addCleanup(shutil.rmtree, path, True)
        return path

    def make_repo(self, files, name="svc"):
        """files: {relative path: str or bytes}. Returns the repo folder."""
        repo = os.path.join(self.tmp(), name)
        for rel, content in files.items():
            full = os.path.join(repo, *rel.split("/"))
            os.makedirs(os.path.dirname(full), exist_ok=True)
            data = content if isinstance(content, bytes) else content.encode("utf-8")
            with open(full, "wb") as fh:
                fh.write(data)
        os.makedirs(repo, exist_ok=True)
        return repo

    def make_root(self, files, confirm=True, name="svc", config=None, memory=True):
        """Init an audit folder over a fresh repo; optionally confirm and patch config."""
        repo = self.make_repo(files, name)
        root = os.path.join(self.tmp(), "audit")
        code, out, err = run(root, "init", "--repo", repo)
        self.assertEqual(code, 0, err)
        config = dict(config or {})
        if memory and "memory" not in config:
            self.assertEqual(run(root, "memory", "none", "--words", "test default")[0], 0)
        if config:
            path = os.path.join(root, "config.json")
            with open(path, encoding="utf-8") as fh:
                cfg = json.load(fh)
            cfg.update(config)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(cfg, fh)
        if confirm:
            self.answer_everything(root)
            code, out, err = run(root, "confirm")
            self.assertEqual(code, 0, err)
        return root, repo

    def answer_brief(self, root):
        """The project brief questions, answered and confirmed through the CLI."""
        for field in ("purpose", "good", "intentional", "must_never_change", "accepted_risks", "out_of_scope",
                      "known_issues"):
            code, out, err = run(root, "brief", "answer", field, "--words", "test default")
            self.assertEqual(code, 0, err)
        code, out, err = run(root, "brief", "confirm")
        self.assertEqual(code, 0, err)

    def answer_everything(self, root, brief=True):
        """Answer the questions confirm needs, through the CLI, the way the interview does."""
        if brief:
            self.answer_brief(root)
        for command in (["answer", "auto_file", "false"], ["answer", "blocker_fixes", '{"mode": "never"}']):
            code, out, err = run(root, *command, "--words", "test default")
            self.assertEqual(code, 0, err)
        for group in GROUPS:
            code, out, err = run(root, "grant", group, "no", "--words", "test default")
            self.assertEqual(code, 0, err)
        self.answer_visibility(root)

    def answer_visibility(self, root, value="private", pointers="false", destination='{"kind": "local_report"}'):
        """The public/private questions: every repo and board confirmed, the yes/no flags, the private destination."""
        for flag in ("public_board_items", "collaborators_see_security"):
            self.assertEqual(run(root, "answer", f"visibility.{flag}", "false", "--words", "test default")[0], 0)
        self.assertEqual(run(root, "answer", "visibility.pointers", pointers, "--words", "test default")[0], 0)
        if destination:
            self.assertEqual(run(root, "answer", "private_destination", destination, "--words", "test default")[0], 0)
        for slug in required_slugs(Root(root).config()):
            code, out, err = run(root, "visibility", "confirm", slug, value, "--words", "test default")
            self.assertEqual(code, 0, err)

    def make_inventoried(self, files, config=None):
        root, repo = self.make_root(files, config=config)
        code, out, err = run(root, "inventory")
        self.assertEqual(code, 0, err)
        return root

    def transcript(self, root, unit, files, path=None, drop_line=None):
        """Write a JSONL transcript holding the show output of every page of each file."""
        path = path or os.path.join(self.tmp(), "transcript.jsonl")
        rows = []
        for rel in files:
            page = 1
            while True:
                code, out, err = run(root, "show", unit, rel, "--page", str(page))
                self.assertEqual(code, 0, err)
                if drop_line is not None and page == 1:
                    kept = [ln for ln in out.split("\n") if not ln.startswith("%5d|" % drop_line)]
                    out = "\n".join(kept)
                rows.append({"message": {"role": "user", "content": [
                    {"type": "tool_result", "content": out}]}})
                if "=== NEXT:" not in out:
                    break
                page += 1
        with open(path, "w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row) + "\n")
        return path

    def write_ledger(self, root, unit, read, skipped=None, leads=None):
        os.makedirs(os.path.join(root, "ledger"), exist_ok=True)
        with open(os.path.join(root, "ledger", unit + ".json"), "w", encoding="utf-8") as fh:
            json.dump({"unit": unit, "read": read, "skipped": skipped or {},
                       "leads": [] if leads is None else leads}, fh)

    def read_text(self, path):
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def write(self, root, relative, data):
        path = os.path.join(root, *relative.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)

    def read(self, root, relative):
        with open(os.path.join(root, *relative.split("/")), encoding="utf-8") as fh:
            return json.load(fh)

    def prepared_unit(self, candidates, verdicts=None, leads=None, files=None, config=None, prove=True):
        """An inventoried one-unit audit whose reader proof passed, with candidates and verdicts on disk."""
        files = files or {"app.py": "import os\nTOKEN_PATH = os.environ['X']\nrun(query)\n"}
        root = self.make_inventoried(files, config=config)
        unit = "svc-u01"
        self.write_ledger(root, unit, sorted(files), leads=leads)
        if prove:
            code, out, err = run(root, "proof", unit, self.transcript(root, unit, sorted(files)))
            self.assertEqual(code, 0, out + err)
        self.write(root, f"candidates/{unit}.json", candidates)
        if verdicts is not None:
            self.write(root, f"review/verdicts-{unit}.json", verdicts)
        return root, unit


def good_finding(title="Handler reads its token path unchecked", **over):
    finding = {
        "id": "CAND", "repo": "svc", "title": title, "area": "config", "goal": 3, "severity": "medium",
        "size": "S", "stage": "none",
        "who": {"affected": "operators", "owner": "platform team"},
        "what": {"summary": "The token path is read without a default.", "observed": "KeyError at start",
                 "expected": "a clear message"},
        "where": [{"kind": "file", "ref": "app.py:2"}],
        "when": {"trigger": "the variable X is unset", "frequency": "sometimes"},
        "why": {"cause": "os.environ[...] raises when the key is missing", "verified": True},
        "how": {"reproduce": ["unset X", "start the app"], "fix": "use os.environ.get with a message",
                "prove": "a test starting without X"},
        "evidence": [{"kind": "file_line", "ref": "app.py:2", "quote": "TOKEN_PATH = os.environ['X']"}],
        "siblings": ["searched: os.environ[, 0 more"], "not_checked": [], "labels": [], "visibility": "public",
        "intent": "no conflict with the brief",
    }
    finding.update(over)
    return finding


def verdict(kind="accept", **over):
    out = {"verdict": kind, "reason": "the line does what the finding says", "checked": ["app.py:2"]}
    if kind == "reject":
        out["other_defect"] = "none"
    out.update(over)
    return out


def src(unit, finding):
    return source_id(unit, finding)
