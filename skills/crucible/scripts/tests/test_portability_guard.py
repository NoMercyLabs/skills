"""The portability guard may not carry the private words it guards against.

The private names live in test_portability.py only as sha256 digests. These tests
check that no plain word in that file hashes into the set, and that a planted
line holding one of the words is still refused.
Standard library only: python3 -m unittest discover -s tests -t .
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
import unittest

import test_portability

GUARD = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "test_portability.py")

# Independent copy of the digests, so this test is red when a plain word is in the source.
KNOWN = {
    "d63f4a0cdaab52726d1ce895e4ac8c3507049e617b0a97d0a0af508bdad34a8d",
    "7becf04360b642f45b6fb7f7ce10dadfc51bd5b6154373065ee35e690ed37c63",
    "dda3dabc3a047166da03ca66d076cc5a7faebd7981dea4a693b21c7d1734dff4",
    "d0348826f00b8dabd3c9d9e59992715711e11176f98764a6c4a5899d28ca6fc6",
    "fc3a2603a0795a7d1b192704a3af95fa661e1c5bc63b393ebf75904fa53d3683",
    "8d239f1bb5df744444daa2e2a7f3a21990c1f80e87bbca1340ddc95881b14c13",
}


def plain_hits(text: str) -> list[str]:
    hits = []
    for word in re.findall(r"[a-z0-9]+", text.lower()):
        for start in range(len(word)):
            for end in range(start + 5, len(word) + 1):
                if hashlib.sha256(word[start:end].encode()).hexdigest() in KNOWN:
                    hits.append(word[start:end])
    return hits


class GuardNamesTests(unittest.TestCase):
    def test_portability_guard_names_not_in_source(self):
        with open(GUARD, encoding="utf-8") as handle:
            source = handle.read()
        for number, line in enumerate(source.splitlines(), start=1):
            hits = plain_hits(line)
            self.assertEqual(hits, [], f"private word in plain text at test_portability.py:{number}")

    def test_guard_holds_every_known_digest(self):
        self.assertTrue(KNOWN <= set(test_portability.HOME_DIGESTS))

    def test_planted_hashed_words_are_refused(self):
        words = ["stone" + "y", "fil" + "lz", "key" + "cloak", "drop" + "let", "moo" + "oom", "arc" + "anum"]
        lines = [f"The {words[0]} note\n", f"see {words[1]}84 here\n", f"{words[0]}eagle\n", "plain text\n"]
        lines += [f"a {w} b\n" for w in words[2:]]
        folder = tempfile.mkdtemp()
        with open(os.path.join(folder, "page.md"), "w", encoding="utf-8") as handle:
            handle.writelines(lines)
        leaks = test_portability.find_leaks(folder)
        flagged = {int(leak.split(":")[1]) for leak in leaks}
        self.assertEqual(flagged, {1, 2, 3, 5, 6, 7, 8}, leaks)


if __name__ == "__main__":
    unittest.main()
