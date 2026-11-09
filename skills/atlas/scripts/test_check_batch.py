"""Batch freshness and resume tests. SPDX-License-Identifier: MIT"""
import json
from pathlib import Path
import subprocess
import sys
import unittest

sys.dont_write_bytecode = True
import test_check_page as page_tests


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.fixture = page_tests.GateTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.script = Path(__file__).with_name("check_batch.py")
        first = {"page": str(self.fixture.page), "card": str(self.fixture.card), "reviews": str(self.fixture.reviews), "result": str(self.root / "first.log")}
        self.fixture.prepare_reviews()
        card = self.root / "second.md"
        card.write_text(self.fixture.card.read_text().replace("/guide/example", "/guide/second"), encoding="utf-8")
        page = self.root / "second.mdx"
        page.write_text(self.fixture.page.read_text(), encoding="utf-8")
        rendered = self.root / "dist/guide/second/index.html"
        rendered.parent.mkdir(parents=True)
        rendered.write_text(page_tests.HTML, encoding="utf-8")
        self.fixture.card, self.fixture.page, self.fixture.rendered = card, page, rendered
        self.fixture.prepare_reviews()
        second = {"page": str(page), "card": str(card), "reviews": str(self.fixture.reviews), "result": str(self.root / "second.log")}
        self.entries = [first, second]
        self.manifest = self.root / "manifest.json"
        self.manifest.write_text(json.dumps(self.entries), encoding="utf-8")
        self.progress = self.root / "progress.md"

    def cli(self, mode=None, *routes):
        argv = [sys.executable, "-B", str(self.script), str(self.manifest), "--checkpoint", str(self.progress)]
        if mode:
            argv.append("--" + mode)
        if routes:
            argv += ["--routes", *routes]
        return subprocess.run(argv, capture_output=True, text=True, encoding="utf-8")

    def test_reviews_alone_do_not_complete_scope(self):
        result = self.cli()
        self.assertEqual(result.returncode, 1)
        text = self.progress.read_text()
        self.assertIn("Accepted: 0 of 2.", text)
        self.assertIn("Resume: /guide/example", text)

    def test_shared_checks_run_once_and_checkpoint_resumes_stale_page(self):
        result = self.cli("final")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / "checks.txt").read_text().count("run"), 1)
        self.assertIn("Accepted: 2 of 2.", self.progress.read_text())
        Path(self.entries[1]["card"]).write_text(Path(self.entries[1]["card"]).read_text() + "\n", encoding="utf-8")
        self.assertEqual(self.cli().returncode, 1)
        text = self.progress.read_text()
        self.assertIn("Accepted: 1 of 2.", text)
        self.assertIn("Resume: /guide/second", text)

    def test_one_reviewed_batch_is_accepted_while_later_pages_wait(self):
        Path(self.entries[1]["reviews"], "guide%2Fsecond.reader.json").unlink()
        result = self.cli("final", "/guide/example")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ACCEPTED /guide/example", result.stdout)
        text = self.progress.read_text()
        self.assertIn("Accepted: 1 of 2.", text)
        self.assertIn("Resume: /guide/second", text)
        self.assertEqual(self.cli().returncode, 1)

    def test_a_batch_cannot_name_a_route_outside_the_inventory(self):
        result = self.cli("final", "/guide/missing")
        self.assertEqual(result.returncode, 1)
        self.assertIn("not in the manifest: /guide/missing", result.stderr)

    def test_preflight_does_not_accept_reviews(self):
        result = self.cli("preflight")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("ACCEPTED", result.stdout)
        self.assertIn("Accepted: 0 of 2.", self.progress.read_text())

    def test_duplicate_route_cannot_hide_an_inventory_entry(self):
        self.entries[1] = self.entries[0].copy()
        self.manifest.write_text(json.dumps(self.entries), encoding="utf-8")
        result = self.cli()
        self.assertEqual(result.returncode, 1)
        self.assertIn("duplicate route", result.stderr)

    def test_failed_second_page_never_creates_partial_acceptance(self):
        self.fixture.reader["findings"] = ["Synthetic unresolved prerequisite"]
        self.fixture.save("reader", self.fixture.reader)
        result = self.cli("final")
        self.assertEqual(result.returncode, 1)
        self.assertFalse(Path(self.entries[0]["result"]).exists())
        self.assertFalse((self.root / "checks.txt").exists())


if __name__ == "__main__":
    unittest.main()
