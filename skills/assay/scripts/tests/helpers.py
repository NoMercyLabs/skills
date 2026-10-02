import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest

from assaylib import cli


def run(root, *args):
    """Run the CLI in-process; returns (exit code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(["--root", root, *args])
    return code, out.getvalue(), err.getvalue()


class AssayCase(unittest.TestCase):
    def tmp(self):
        path = tempfile.mkdtemp(prefix="assay-test-")
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

    def make_root(self, files, confirm=True, name="svc", config=None):
        """Init an audit folder over a fresh repo; optionally confirm and patch config."""
        repo = self.make_repo(files, name)
        root = os.path.join(self.tmp(), "audit")
        code, out, err = run(root, "init", "--repo", repo)
        self.assertEqual(code, 0, err)
        if config:
            path = os.path.join(root, "config.json")
            with open(path, encoding="utf-8") as fh:
                cfg = json.load(fh)
            cfg.update(config)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(cfg, fh)
        if confirm:
            code, out, err = run(root, "confirm")
            self.assertEqual(code, 0, err)
        return root, repo

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
