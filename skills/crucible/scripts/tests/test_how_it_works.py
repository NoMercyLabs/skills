import json
import os
import re
import unittest

from .helpers import CrucibleCase

SKILL = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SECTIONS = ("What crucible does", "The stages", "What it asks before acting", "What it never does",
            "Models and cost", "Self-heal and lessons", "The measured limits")
NUMBER = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


def numbers_in(value):
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from numbers_in(item)
    elif isinstance(value, list):
        for item in value:
            yield from numbers_in(item)
    elif isinstance(value, str):
        for token in NUMBER.findall(value):
            yield float(token.replace(",", ""))


def section(text, title):
    match = re.search(r"^## " + re.escape(title) + r"\s*$", text, re.M)
    if not match:
        return None
    rest = text[match.end():]
    nxt = re.search(r"^## ", rest, re.M)
    return rest[:nxt.start()] if nxt else rest


class HowItWorksTests(CrucibleCase):
    def text(self):
        return self.read_text(os.path.join(SKILL, "HOW-IT-WORKS.md"))

    def test_how_it_works_has_all_sections(self):
        text = self.text()
        for title in SECTIONS:
            body = section(text, title)
            self.assertIsNotNone(body, f"missing section: {title}")
            self.assertGreater(len(body.split()), 20, f"section too short: {title}")

    def test_how_it_works_numbers_match_calibration(self):
        calibration = json.load(open(os.path.join(SKILL, "references", "calibration.json"), encoding="utf-8"))
        known = {round(abs(n), 4) for n in numbers_in(calibration)}
        known |= {round(abs(n) * 100, 2) for n in numbers_in(calibration)}
        body = section(self.text(), "Models and cost")
        self.assertIsNotNone(body)
        found = [t for t in NUMBER.findall(body)]
        self.assertTrue(found, "the cost section states no numbers")
        for token in found:
            value = round(abs(float(token.replace(",", ""))), 4)
            self.assertIn(value, known, f"{token} is not in calibration.json")
        for key in ("recall", "invented", "coverage_percent", "cost_tokens", "forecast_error"):
            for tier in ("balanced", "fast"):
                value = calibration["selftest"][tier][key]
                shown = [str(value), f"{value:,}" if isinstance(value, int) else str(value)]
                if key == "recall":
                    shown = [str(calibration["selftest"][tier]["found"])]
                self.assertTrue(any(s in body for s in shown), f"{tier} {key} ({shown}) not stated")

    def test_how_it_works_is_generic(self):
        text = self.text()
        for word in ("NoMercy", "Stoney", "Fillz", "C:/Users", "C:\\"):
            self.assertNotIn(word, text)


if __name__ == "__main__":
    unittest.main()
