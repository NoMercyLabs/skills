#!/usr/bin/env python3
"""Tests for check_docs.py. Standard library only: python3 -m unittest test_check_docs.py"""

from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import check_docs  # noqa: E402

MAP = """# Map

| Page | Tier | Job | Owns | Assumes | Links to | Covers | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| /guide | reference | Explains the thing. | thing | - | - | src | reviewed |
"""


def slice_report(paths: list[str], given: int | None = None, opened: int | None = None) -> str:
    given = len(paths) if given is None else given
    opened = len(paths) if opened is None else opened
    listed = "\n".join(f"- {path}" for path in paths)
    return (
        f"# Slice: one\nFiles given: {given}\nFiles opened: {opened}\n\n"
        f"## Files opened\n{listed}\n\n"
        "## Traps\n- see src/a.py for the default\n"
    )


class Workdir:
    """A throwaway project: source files, a docs-work folder, and the cwd set to it."""

    def __init__(self, files: dict[str, str]):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        for path, body in files.items():
            self.write(path, body)
        self._cwd = os.getcwd()
        os.chdir(self.root)

    def write(self, path: str, body: str) -> None:
        full = os.path.join(self.root, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as handle:
            handle.write(body)

    def close(self) -> None:
        os.chdir(self._cwd)
        self._tmp.cleanup()


def run(func, *args) -> tuple[int, str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = func(*args)
    return code, out.getvalue()


class CoverageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.work = Workdir({"docs-work/toolchain.md": "answers\n"})

    def tearDown(self) -> None:
        self.work.close()

    def test_dotless_source_file_listed_in_a_slice_counts_as_read(self) -> None:
        self.work.write("pkg/DEBIAN/postinst", "#!/bin/sh\n")
        self.work.write("pkg/PKGBUILD", "pkgname=x\n")
        self.work.write("docs-work/slices/one.md", slice_report(["pkg/DEBIAN/postinst", "pkg/PKGBUILD"]))
        code, out = run(check_docs.check_slices, "docs-work/slices", ["pkg"])
        self.assertEqual(code, 0, out)

    def test_file_under_a_dot_directory_matches_the_walk(self) -> None:
        self.work.write(".github/actions/deploy/action.yml", "name: build\n")
        self.work.write("docs-work/slices/one.md", slice_report([".github/actions/deploy/action.yml"]))
        code, out = run(check_docs.check_slices, "docs-work/slices", [".github"])
        self.assertEqual(code, 0, out)

    def test_leading_dot_slash_is_still_accepted(self) -> None:
        self.work.write("src/a.py", "x = 1\n")
        self.work.write("docs-work/slices/one.md", slice_report(["./src/a.py"]))
        code, out = run(check_docs.check_slices, "docs-work/slices", ["src"])
        self.assertEqual(code, 0, out)

    def test_bullets_outside_the_files_opened_section_are_not_counted_as_read(self) -> None:
        self.work.write("src/a.py", "x = 1\n")
        self.work.write("src/b.py", "y = 2\n")
        report = slice_report(["src/b.py"]) + "\n## Public surface\n- src/a.py\n"
        self.work.write("docs-work/slices/one.md", report)
        code, out = run(check_docs.check_slices, "docs-work/slices", ["src"])
        self.assertEqual(code, 1, out)
        self.assertIn("src/a.py", out)

    def test_typed_counts_that_disagree_with_the_list_warn_but_the_walk_decides(self) -> None:
        self.work.write("src/a.py", "x = 1\n")
        self.work.write("src/b.py", "y = 2\n")
        self.work.write("docs-work/slices/one.md", slice_report(["src/a.py", "src/b.py"], given=1, opened=1))
        code, out = run(check_docs.check_slices, "docs-work/slices", ["src"])
        self.assertEqual(code, 0, out)
        self.assertIn("warning", out)
        self.assertIn("the list names 2", out)

    def test_an_unread_file_still_fails(self) -> None:
        self.work.write("src/a.py", "x = 1\n")
        self.work.write("src/b.py", "y = 2\n")
        self.work.write("docs-work/slices/one.md", slice_report(["src/a.py"]))
        code, out = run(check_docs.check_slices, "docs-work/slices", ["src"])
        self.assertEqual(code, 1, out)
        self.assertIn("src/b.py", out)

    def test_coverage_fails_without_a_source_root(self) -> None:
        self.work.write("docs-work/slices/one.md", slice_report(["src/a.py"]))
        code, out = run(check_docs.check_slices, "docs-work/slices", [])
        self.assertEqual(code, 1, out)
        self.assertIn("--src", out)

    def test_coverage_fails_when_the_source_root_holds_no_source(self) -> None:
        self.work.write("docs-work/slices/one.md", slice_report(["src/a.py"]))
        code, out = run(check_docs.check_slices, "docs-work/slices", ["missing"])
        self.assertEqual(code, 1, out)
        self.assertIn("no source files", out)

    def test_a_report_without_a_files_opened_section_fails(self) -> None:
        self.work.write("src/a.py", "x = 1\n")
        self.work.write("docs-work/slices/one.md", "# Slice: one\nFiles given: 1\nFiles opened: 1\n- src/a.py\n")
        code, out = run(check_docs.check_slices, "docs-work/slices", ["src"])
        self.assertEqual(code, 1, out)
        self.assertIn("## Files opened", out)


class StatusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.work = Workdir({"docs-work/toolchain.md": "answers\n", "src/a.py": "x = 1\n", "docs/guide.md": "# Guide\n"})
        self.work.write("docs-work/map.md", MAP)
        for kind in ("factcheck", "reader"):
            digest = check_docs.page_digest("docs/guide.md")
            self.work.write(
                f"docs-work/reviews/guide.{kind}.md",
                f"Verdict: PASS\nReviewed: docs/guide.md\nReviewed-SHA: {digest}\n",
            )
        self.rows, _ = check_docs.parse_map("docs-work/map.md")

    def tearDown(self) -> None:
        self.work.close()

    def status(self, srcs: list[str]) -> tuple[int, str]:
        return run(check_docs.emit_status, self.rows, "docs-work/reviews", "docs-work/slices", srcs)

    def test_status_is_incomplete_when_no_slice_was_scanned(self) -> None:
        code, out = self.status(["src"])
        self.assertEqual(code, 1, out)
        self.assertIn("STATUS: INCOMPLETE", out)
        self.assertIn("Coverage: FAIL", out)

    def test_status_is_incomplete_when_coverage_was_not_given_a_source_root(self) -> None:
        self.work.write("docs-work/slices/one.md", slice_report(["src/a.py"]))
        code, out = self.status([])
        self.assertEqual(code, 1, out)
        self.assertIn("Coverage: not run", out)

    def test_status_is_incomplete_when_a_file_went_unread(self) -> None:
        self.work.write("src/b.py", "y = 2\n")
        self.work.write("docs-work/slices/one.md", slice_report(["src/a.py"]))
        code, out = self.status(["src"])
        self.assertEqual(code, 1, out)
        self.assertIn("Coverage: FAIL", out)

    def test_status_is_delivered_when_coverage_and_reviews_pass(self) -> None:
        self.work.write("docs-work/slices/one.md", slice_report(["src/a.py"]))
        code, out = self.status(["src"])
        self.assertEqual(code, 0, out)
        self.assertIn("STATUS: DELIVERED", out)
        self.assertIn("Coverage: PASS", out)


if __name__ == "__main__":
    unittest.main()
