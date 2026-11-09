#!/usr/bin/env python3
"""Tests for check_docs.py. Standard library only: python3 -m unittest test_check_docs.py"""

from __future__ import annotations

import contextlib
import io
import json
import os
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import check_batch  # noqa: E402
import check_docs  # noqa: E402
import test_check_page as page_tests  # noqa: E402

MAP = """# Map

| Page | Tier | Job | Owns | Assumes | Links to | Covers | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| /guide/example | reference | Explains the thing. | thing | - | - | src | reviewed |
"""


SURFACES = """# Surfaces

| Surface | Kind | Who | States | Page |
| --- | --- | --- | --- | --- |
| The settings screen | screen | anyone | empty, full | /guide/example |
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


class ReviewedPage(unittest.TestCase):
    """A real page with real review records, in a project with a map and a manifest."""

    def setUp(self) -> None:
        self.page = page_tests.GateTests()
        self.page.setUp()
        self.addCleanup(self.page.doCleanups)
        self.page.prepare_reviews()
        self.manifest = os.path.join(str(self.page.root), "manifest.json")
        entry = {
            "page": str(self.page.page),
            "card": str(self.page.card),
            "reviews": str(self.page.reviews),
            "result": os.path.join(str(self.page.root), "result.log"),
        }
        with open(self.manifest, "w", encoding="utf-8") as handle:
            json.dump([entry], handle)
        self.work = Workdir({"docs-work/toolchain.md": "answers\n", "src/a.py": "x = 1\n"})
        self.addCleanup(self.work.close)
        self.work.write("docs-work/map.md", MAP)
        self.rows, _ = check_docs.parse_map("docs-work/map.md")

    def accept(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()):
            check_batch.run(check_batch.load_manifest(pathlib.Path(self.manifest)), final=True)


class StatusTests(ReviewedPage):
    def setUp(self) -> None:
        super().setUp()
        self.accept()

        self.work.write("docs-work/surfaces.md", SURFACES)

    def status(self, srcs: list[str]) -> tuple[int, str]:
        return run(check_docs.emit_status, self.rows, self.manifest, "docs-work/slices", srcs, "docs-work/surfaces.md")

    def test_status_is_incomplete_when_the_manifest_holds_a_page_the_map_does_not(self) -> None:
        self.work.write("docs-work/slices/one.md", slice_report(["src/a.py"]))
        self.rows.clear()
        code, out = self.status(["src"])
        self.assertEqual(code, 1, out)
        self.assertIn("STATUS: INCOMPLETE", out)

    def test_status_is_incomplete_without_a_product_inventory(self) -> None:
        self.work.write("docs-work/slices/one.md", slice_report(["src/a.py"]))
        os.remove("docs-work/surfaces.md")
        code, out = self.status(["src"])
        self.assertEqual(code, 1, out)
        self.assertIn("Surfaces: FAIL", out)

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
        self.assertIn("Pages accepted: 1 of 1", out)
        self.assertIn("Coverage: PASS", out)

    def test_status_is_incomplete_when_the_page_changed_after_acceptance(self) -> None:
        self.work.write("docs-work/slices/one.md", slice_report(["src/a.py"]))
        self.page.card.write_text(self.page.card.read_text() + "\n", encoding="utf-8")
        code, out = self.status(["src"])
        self.assertEqual(code, 1, out)
        self.assertIn("STATUS: INCOMPLETE", out)
        self.assertIn("Pages accepted: 0 of 1", out)


class ReviewTests(ReviewedPage):
    """`reviews`: only an acceptance that still matches the page, card and render counts."""

    def reviews(self) -> tuple[int, str]:
        return run(check_docs.check_reviews, self.rows, self.manifest)

    def test_an_accepted_page_passes(self) -> None:
        self.accept()
        code, out = self.reviews()
        self.assertEqual(code, 0, out)

    def test_passing_reviews_without_final_acceptance_fail(self) -> None:
        code, out = self.reviews()
        self.assertEqual(code, 1, out)
        self.assertIn("/guide/example", out)

    def test_a_card_change_after_acceptance_forces_new_reviews(self) -> None:
        self.accept()
        self.page.card.write_text(self.page.card.read_text() + "\n", encoding="utf-8")
        code, out = self.reviews()
        self.assertEqual(code, 1, out)
        self.assertIn("/guide/example", out)

    def test_a_map_row_outside_the_manifest_fails(self) -> None:
        self.accept()
        self.rows[0]["page"] = "/guide/other"
        code, out = self.reviews()
        self.assertEqual(code, 1, out)
        self.assertIn("/guide/other: not in the manifest", out)

    def test_a_manifest_page_missing_from_the_map_fails(self) -> None:
        self.accept()
        self.rows.clear()
        code, out = self.reviews()
        self.assertEqual(code, 1, out)
        self.assertIn("/guide/example: in the manifest but not on the map", out)

    def test_a_missing_manifest_fails(self) -> None:
        code, out = run(check_docs.check_reviews, self.rows, "docs-work/no-such-manifest.json")
        self.assertEqual(code, 1, out)
        self.assertIn("manifest", out)

    def test_a_planned_page_fails_even_with_an_acceptance(self) -> None:
        self.accept()
        self.rows[0]["status"] = "planned"
        code, out = self.reviews()
        self.assertEqual(code, 1, out)
        self.assertIn("still planned", out)



class SurfaceTests(unittest.TestCase):
    """`surfaces`: everything a person can reach is claimed by a page or excluded."""

    def setUp(self) -> None:
        self.work = Workdir({})
        self.addCleanup(self.work.close)
        self.work.write("docs-work/map.md", MAP)
        self.rows, _ = check_docs.parse_map("docs-work/map.md")

    def check(self, body: str) -> tuple[int, str]:
        self.work.write("docs-work/surfaces.md", body)
        return run(check_docs.check_surfaces, "docs-work/surfaces.md", self.rows)

    def test_a_surface_on_a_mapped_page_passes(self) -> None:
        code, out = self.check(SURFACES)
        self.assertEqual(code, 0, out)

    def test_a_surface_on_an_unplanned_page_fails(self) -> None:
        code, out = self.check(SURFACES.replace("/guide/example", "/guide/nowhere"))
        self.assertEqual(code, 1, out)
        self.assertIn("/guide/nowhere", out)

    def test_an_exclusion_needs_a_reason(self) -> None:
        code, out = self.check(SURFACES.replace("/guide/example", "excluded:"))
        self.assertEqual(code, 1, out)
        self.assertIn("reason", out)

    def test_an_exclusion_with_a_reason_passes(self) -> None:
        code, out = self.check(SURFACES.replace("/guide/example", "excluded: internal only"))
        self.assertEqual(code, 0, out)

    def test_a_surface_without_roles_or_states_fails(self) -> None:
        code, out = self.check(SURFACES.replace("| anyone | empty, full |", "| - | - |"))
        self.assertEqual(code, 1, out)
        self.assertIn("names no", out)

    def test_an_unknown_kind_fails(self) -> None:
        code, out = self.check(SURFACES.replace("| screen |", "| widget |"))
        self.assertEqual(code, 1, out)
        self.assertIn("kind", out)

    def test_a_missing_inventory_fails(self) -> None:
        code, out = run(check_docs.check_surfaces, "docs-work/none.md", self.rows)
        self.assertEqual(code, 1, out)
        self.assertIn("surfaces", out)


class StyleTests(unittest.TestCase):
    """`style`: a heading that mixes words with a code span."""

    def check(self, body: str) -> tuple[int, str]:
        work = Workdir({"docs/page.md": body})
        try:
            return run(check_docs.check_style, "docs")
        finally:
            work.close()

    def test_code_span_in_a_prose_heading_fails(self):
        code, out = self.check("# Page\n\n## What `fetch` applies\n\nText.\n")
        self.assertEqual(code, 1)
        self.assertIn("code span in a heading", out)

    def test_plain_heading_passes(self):
        code, _ = self.check("# Page\n\n## What fetch applies\n\nThe `fetch` call applies it.\n")
        self.assertEqual(code, 0)

    def test_member_heading_passes(self):
        code, _ = self.check("# Methods\n\n### `addListener`\n\n### `resize(width)`\n")
        self.assertEqual(code, 0)

    def test_two_spans_in_a_heading_fail(self):
        code, _ = self.check("# Page\n\n### `on` and `off`\n")
        self.assertEqual(code, 1)

    def test_headings_inside_code_are_ignored(self):
        code, _ = self.check("# Page\n\n```md\n## What `x` does\n```\n")
        self.assertEqual(code, 0)

    def test_frontmatter_is_ignored(self):
        code, _ = self.check("---\ntitle: What `x` does\n---\n\n# Page\n")
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
