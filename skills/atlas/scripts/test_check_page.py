"""Synthetic acceptance fixtures; these are not reviews of real documentation. SPDX-License-Identifier: MIT"""
import sys
sys.dont_write_bytecode = True
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).with_name("check_page.py")
SPEC = importlib.util.spec_from_file_location("reader_first_gate", SCRIPT)
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)
HTML = """<main><article><h1>Create a message</h1>
<p>You need moderator access.</p><ol><li>Open the editor.</li></ol>
<p>The saved message appears in chat.</p><p>Choose another saved message.</p>
</article></main>"""


class GateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="reader-first-tests-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.page = self.root / "page.mdx"
        self.card = self.root / "card.md"
        self.rendered = self.root / "dist/guide/example/index.html"
        self.rendered.parent.mkdir(parents=True)
        self.rendered.write_text(HTML, encoding="utf-8")
        self.page.write_text("A fixture page, not product documentation.", encoding="utf-8")
        (self.root / "voice.md").write_text("Synthetic test voice profile.", encoding="utf-8")
        (self.root / "source.txt").write_text("Moderators can create messages.\nA saved message appears in chat.\n", encoding="utf-8")
        self.reviews = self.root / "reviews"
        self.reviews.mkdir()
        command = [sys.executable, "-B", "-c", "from pathlib import Path; p=Path('checks.txt'); p.write_text(p.read_text()+'run\\n' if p.exists() else 'run\\n')"]
        self.write_card(command=command)

    def write_card(self, command=None, move=None):
        command = command or [sys.executable, "-B", "-c", "print('fixture check ran')"]
        moved = "- " + move if move else "- none"
        self.card.write_text(f"""Route: /guide/example
Reader: A moderator who has never used this product
Type: task
Arrives-with: Create a message
Goal: A saved message
Success: The saved message appears in chat
Application-case: Use a different saved message
Prerequisites: Moderator access
Project-root: {self.root}
Built-root: dist
Rendered: dist/guide/example/index.html
Voice: voice.md
Must know:
- access | Moderators can create messages | source.txt:1
Moves elsewhere:
{moved}
Checks:
- build: {json.dumps(command)}
""", encoding="utf-8")

    def cli(self, mode):
        return subprocess.run([sys.executable, "-B", str(SCRIPT), str(self.page), "--card", str(self.card), "--reviews", str(self.reviews), "--" + mode], capture_output=True, text=True, encoding="utf-8")

    def state(self):
        card = GATE.read_card(self.card)
        fingerprint, _, reading = GATE.snapshot(self.page, card)
        return card, fingerprint, reading

    def save(self, kind, value):
        path = GATE.review_path(GATE.read_card(self.card), self.reviews, kind)
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def prepare_reviews(self, release=True):
        card, fingerprint, reading = self.state()
        quotes = ["Open the editor.", "You need moderator access.", "The saved message appears in chat.", "Choose another saved message.", "", ""]
        self.reader = {
            "fingerprint": fingerprint, "verdict": "PENDING",
            "answers": [{"question": i, "answer": q or "None.", "quote": q} for i, q in enumerate(quotes, 1)],
            "findings": [], "warnings_released": False, "warning_review": [],
        }
        self.save("reader", self.reader)
        if release:
            result = self.cli("warnings")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.reader = json.loads(GATE.review_path(card, self.reviews, "reader").read_text())
        _, warnings = GATE.warnings_for(card, reading)
        self.reader["warning_review"] = [{"id": item["id"], "decision": "keep", "reason": "Synthetic fixture decision, not a usability claim."} for item in warnings]
        self.reader["verdict"] = "PASS"
        self.save("reader", self.reader)
        self.fact = {
            "fingerprint": fingerprint, "verdict": "PASS", "findings": [],
            "coverage": [{"id": item[0], "result": "supported", "evidence": item[2]} for item in card["_facts"]],
            "reader_answers": [{"question": i, "result": "supported", "evidence": "Synthetic fixture evidence."} for i in range(1, 5)],
        }
        self.save("fact", self.fact)

    def assert_rejected(self, mode="final", phrase=None):
        result = self.cli(mode)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertNotIn("ACCEPTED", result.stdout)
        self.assertNotIn("Traceback", result.stderr)
        if phrase:
            self.assertIn(phrase, result.stderr)
        return result

    def test_complete_cycle_executes_named_checks_and_accepts(self):
        result = self.cli("preflight")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.prepare_reviews()
        result = self.cli("final")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ACCEPTED /guide/example", result.stdout)
        self.assertEqual((self.root / "checks.txt").read_text().splitlines(), ["run", "run"])

    def test_preflight_requires_no_review_and_exposes_no_warnings(self):
        result = self.cli("preflight")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("not accepted", result.stdout)
        self.assertNotIn("non_code_words", result.stdout)
        self.assertNotIn('"warnings"', result.stdout)

    def test_reader_packet_has_no_card_rationale_or_metrics(self):
        result = self.cli("reader-input")
        self.assertEqual(result.returncode, 0, result.stderr)
        packet = json.loads(result.stdout)
        self.assertEqual(set(packet), {"fingerprint", "reader", "request", "application_case", "rendered_article"})
        self.assertIn("<article>", packet["rendered_article"])

    def test_warnings_refused_before_blind_answers_exist(self):
        result = self.assert_rejected("warnings", "invalid or missing JSON")
        self.assertNotIn("non_code_words", result.stdout)

    def test_incomplete_blind_answers_cannot_release_warnings(self):
        self.prepare_reviews(release=False)
        self.reader["answers"].pop()
        self.save("reader", self.reader)
        self.assert_rejected("warnings", "six blind answers")

    def test_final_refuses_unreleased_warnings_even_with_decisions(self):
        self.prepare_reviews(release=False)
        self.assert_rejected(phrase="run --warnings")

    def test_card_correction_invalidates_both_reviews(self):
        self.prepare_reviews()
        old_fact = dict(self.fact)
        self.card.write_text(self.card.read_text().replace("A saved message", "A corrected goal"), encoding="utf-8")
        self.assert_rejected(phrase="stale fingerprint")
        self.prepare_reviews()
        self.save("fact", old_fact)
        self.assert_rejected(phrase="stale fingerprint")

    def test_page_change_invalidates_reviews(self):
        self.prepare_reviews()
        self.page.write_text(self.page.read_text() + "\nChanged.", encoding="utf-8")
        self.assert_rejected(phrase="stale fingerprint")

    def test_rendered_include_change_invalidates_reviews(self):
        self.prepare_reviews()
        self.rendered.write_text(HTML.replace("</article>", "<p>New included content.</p></article>"), encoding="utf-8")
        self.assert_rejected(phrase="stale fingerprint")

    def test_outside_chrome_is_not_another_fingerprinted_input(self):
        self.prepare_reviews()
        self.rendered.write_text("<header>Different chrome</header>" + HTML, encoding="utf-8")
        self.assertEqual(self.cli("final").returncode, 0)

    def test_duplicate_verdict_keys_are_rejected(self):
        self.prepare_reviews()
        path = GATE.review_path(self.state()[0], self.reviews, "fact")
        text = path.read_text().replace('"verdict": "PASS"', '"verdict": "FAIL", "verdict": "PASS"')
        path.write_text(text, encoding="utf-8")
        self.assert_rejected(phrase="duplicate JSON key")

    def test_historical_pass_lines_do_not_pass(self):
        self.prepare_reviews()
        path = GATE.review_path(self.state()[0], self.reviews, "fact")
        path.write_text("Verdict: FAIL\nOld example:\nVerdict: PASS\n", encoding="utf-8")
        self.assert_rejected(phrase="invalid or missing JSON")

    def test_unexpected_review_fields_are_rejected(self):
        self.prepare_reviews()
        self.fact["historical_pass"] = "Verdict: PASS"
        self.save("fact", self.fact)
        self.assert_rejected(phrase="wrong review fields")

    def test_empty_evidence_or_coverage_cannot_pass(self):
        self.prepare_reviews()
        self.fact["coverage"][0]["evidence"] = ""
        self.save("fact", self.fact)
        self.assert_rejected(phrase="unsupported coverage")
        self.fact["coverage"] = []
        self.save("fact", self.fact)
        self.assert_rejected(phrase="missing or duplicate coverage")

    def test_failed_named_check_is_not_a_note(self):
        command = [sys.executable, "-B", "-c", "from pathlib import Path; import sys; sys.exit(7 if Path('fail').exists() else 0)"]
        self.write_card(command=command)
        self.prepare_reviews()
        (self.root / "fail").write_text("fail", encoding="utf-8")
        self.assert_rejected(phrase="check build failed with exit 7")

    def test_missing_named_executable_fails(self):
        self.write_card(command=["this-executable-does-not-exist-reader-first"])
        self.assert_rejected("preflight", "could not complete")

    def test_empty_check_list_and_arbitrary_length_override_are_rejected(self):
        self.card.write_text(self.card.read_text().split("Checks:")[0] + "Checks:\n- none\n", encoding="utf-8")
        self.assert_rejected("preflight", "exact checks")
        self.write_card()
        self.card.write_text(self.card.read_text() + "Long-because: x\n", encoding="utf-8")
        self.assert_rejected("preflight", "unknown field")

    def test_missing_or_invalid_source_evidence_fails(self):
        self.card.write_text(self.card.read_text().replace("source.txt:1", "absent.txt:1"), encoding="utf-8")
        self.assert_rejected("preflight", "evidence file does not exist")
        self.write_card()
        self.card.write_text(self.card.read_text().replace("source.txt:1", "source.txt:999"), encoding="utf-8")
        self.assert_rejected("preflight", "line range")

    def test_secret_reference_is_rejected_before_reading(self):
        self.card.write_text(self.card.read_text().replace("source.txt:1", ".env:1"), encoding="utf-8")
        self.assert_rejected("preflight", "live-secret evidence")

    def test_move_requires_a_real_built_route_and_fragment(self):
        self.write_card(move="detail | Other detail | source.txt:2 | /other#detail")
        self.assert_rejected("preflight", "no built page")
        other = self.root / "dist/other/index.html"
        other.parent.mkdir()
        other.write_text("<article><h1>Other</h1></article>", encoding="utf-8")
        self.assert_rejected("preflight", "no anchor")
        other.write_text('<article><h1 id="detail">Other</h1></article>', encoding="utf-8")
        self.assertEqual(self.cli("preflight").returncode, 0)
        self.prepare_reviews()
        self.fact["coverage"].pop()
        self.save("fact", self.fact)
        self.assert_rejected(phrase="missing or duplicate coverage")

    def test_permissions_and_ordinary_phrases_are_not_banned(self):
        self.rendered.write_text(HTML.replace("<h1>", "<h2>Permissions</h2><p>Whether you stream daily or weekly, choose <b>Unlock</b>.</p><h1>", 1), encoding="utf-8")
        self.assertEqual(self.cli("preflight").returncode, 0)

    def test_long_tables_are_counted_and_warned_only_after_blind_review(self):
        table = "<table>" + "".join("<tr><td>" + "word " * 50 + "</td></tr>" for _ in range(30)) + "</table>"
        self.rendered.write_text(HTML.replace("</article>", table + "</article>"), encoding="utf-8")
        self.assertNotIn("non_code_words", self.cli("preflight").stdout)
        self.prepare_reviews()
        card, _, reading = self.state()
        metrics, warnings = GATE.warnings_for(card, reading)
        self.assertGreaterEqual(metrics["non_code_words"], 1500)
        self.assertEqual(metrics["table_rows"], 30)
        self.assertIn("length", {item["id"] for item in warnings})
        self.reader["warning_review"] = []
        self.save("reader", self.reader)
        self.assert_rejected(phrase="judge every current warning")

    def test_mdx_details_prose_is_visible_to_diagnostics(self):
        details = "<details><summary>More</summary><p>" + "word " * 40 + "ends.</p></details>"
        self.rendered.write_text(HTML.replace("</article>", details + "</article>"), encoding="utf-8")
        card, _, reading = self.state()
        self.assertTrue(any(item["id"].startswith("sentence-") for item in GATE.warnings_for(card, reading)[1]))

    def test_rendered_commonmark_parenthesis_steps_are_recognized(self):
        self.page.write_text("1) Open the editor.", encoding="utf-8")
        card, _, reading = self.state()
        self.assertIsNotNone(GATE.warnings_for(card, reading)[0]["first_numbered_step_after_words"])
        self.assertEqual(self.cli("preflight").returncode, 0)

    def test_tilde_fenced_example_does_not_become_a_step(self):
        self.page.write_text("~~~text\n1. This is example content.\n~~~", encoding="utf-8")
        self.rendered.write_text("<article><pre><code>1. This is example content.</code></pre></article>", encoding="utf-8")
        card, _, reading = self.state()
        self.assertIsNone(GATE.warnings_for(card, reading)[0]["first_numbered_step_after_words"])

    def test_late_first_step_is_a_warning_not_a_failure(self):
        self.rendered.write_text(HTML.replace("<ol>", "<p>" + "prerequisite " * 160 + "</p><ol>"), encoding="utf-8")
        self.assertEqual(self.cli("preflight").returncode, 0)
        card, _, reading = self.state()
        self.assertIn("first-numbered-step", {item["id"] for item in GATE.warnings_for(card, reading)[1]})

    def test_unknown_answer_or_invented_quote_cannot_pass(self):
        self.prepare_reviews()
        for answer in ("UNKNOWN", "  UNKNOWN: missing instructions"):
            with self.subTest(answer=answer):
                self.reader["answers"][0]["answer"] = answer
                self.save("reader", self.reader)
                self.assert_rejected(phrase="unanswered required case")
        self.reader["answers"][0]["answer"] = "Open the editor."
        self.reader["answers"][0]["quote"] = "This text was invented."
        self.save("reader", self.reader)
        self.assert_rejected(phrase="quote not present")

    def test_application_answer_must_be_checked_by_fact_reviewer(self):
        self.prepare_reviews()
        self.fact["reader_answers"][-1]["result"] = "unsupported"
        self.save("fact", self.fact)
        self.assert_rejected(phrase="unsupported reader_answers")

    def test_separate_exact_excerpts_are_valid_evidence(self):
        self.prepare_reviews()
        self.reader["answers"][0]["quote"] = ["Open the editor.", "The saved message appears in chat."]
        self.save("reader", self.reader)
        result = self.cli("final")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_one_invented_excerpt_rejects_the_evidence_array(self):
        self.prepare_reviews()
        self.reader["answers"][0]["quote"] = ["Open the editor.", "This was invented."]
        self.save("reader", self.reader)
        self.assert_rejected(phrase="quote not present")

    def test_route_identity_avoids_basename_collisions(self):
        card = self.state()[0]
        first = GATE.review_path(card, self.reviews, "reader")
        card["Route"] = "/another/example"
        self.assertNotEqual(first, GATE.review_path(card, self.reviews, "reader"))

    def test_boolean_question_number_is_not_an_integer_id(self):
        self.prepare_reviews()
        self.reader["answers"][0]["question"] = True
        self.save("reader", self.reader)
        self.assert_rejected(phrase="questions 1 to 6")

    def test_non_string_verdict_is_rejected_without_a_traceback(self):
        self.prepare_reviews()
        self.reader["verdict"] = ["PASS"]
        self.save("reader", self.reader)
        self.assert_rejected(phrase="invalid verdict")

    def test_non_string_warning_id_is_rejected_without_a_traceback(self):
        self.prepare_reviews()
        self.reader["warning_review"] = [{"id": ["length"], "decision": "keep", "reason": "Malformed fixture"}]
        self.save("reader", self.reader)
        self.assert_rejected(phrase="warning decision values must be strings")

    def test_windows_legacy_console_can_print_unicode_check_output(self):
        self.write_card(command=[sys.executable, "-B", "-c", "import sys; sys.stdout.buffer.write(bytes.fromhex('e29c93'))"])
        environment = dict(os.environ, PYTHONIOENCODING="cp1252")
        result = subprocess.run([sys.executable, "-B", str(SCRIPT), str(self.page), "--card", str(self.card), "--preflight"], capture_output=True, text=True, encoding="utf-8", env=environment)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("\u2713", result.stdout)

    def test_validation_may_not_silently_correct_the_card(self):
        self.write_card(command=[sys.executable, "-B", "-c", "from pathlib import Path; p=Path('card.md'); p.write_text(p.read_text()+'\\n')"])
        self.assert_rejected("preflight", "changed the card")


if __name__ == "__main__":
    unittest.main()
