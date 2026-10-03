#!/usr/bin/env python3
"""The skill stays portable: no vocabulary from the projects it was written in.

SKILL.md ends on the rule: every example is drawn from constructs that exist
everywhere, a request handler, a config file, a deploy script, a worker. A rule
nobody checks leaks, so this test checks it. It scans every text file in the
skill: docs, code, fixtures and recorded replays. The list holds the home
projects' domain words and names; extend it when a new leak is found.
Standard library only: python3 -m unittest test_portability
"""

from __future__ import annotations

import hashlib
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Domain words of the first home project: matched as whole words.
DOMAIN_WORDS = re.compile(
    r"\b(player|playback|playlist|chapters?|subtitles?|lyrics|scrubber|seek|seeking|"
    r"autoplay|media server|encoder|transcod\w*|codec|hls|m3u8)\b",
    re.IGNORECASE,
)
# Names and tooling of the home projects. The private words are stored only as
# sha256 digests of the lowercased word, so this public file does not name them.
# Add one: python -c "import hashlib;print(hashlib.sha256(b'word').hexdigest())"
# A line is refused when any run of 5 or more letters or digits inside one of
# its words hashes into the set: that also catches a compound such as word84.
HOME_DIGESTS = frozenset(
    {
        "d63f4a0cdaab52726d1ce895e4ac8c3507049e617b0a97d0a0af508bdad34a8d",
        "7becf04360b642f45b6fb7f7ce10dadfc51bd5b6154373065ee35e690ed37c63",
        "dda3dabc3a047166da03ca66d076cc5a7faebd7981dea4a693b21c7d1734dff4",
        "d0348826f00b8dabd3c9d9e59992715711e11176f98764a6c4a5899d28ca6fc6",
        "fc3a2603a0795a7d1b192704a3af95fa661e1c5bc63b393ebf75904fa53d3683",
        "8d239f1bb5df744444daa2e2a7f3a21990c1f80e87bbca1340ddc95881b14c13",
    }
)
MIN_PART = 5
WORDS = re.compile(r"[a-z0-9]+")
# The publisher name and finding ids are not sensitive: kept as a plain pattern.
HOME_NAMES = re.compile(r"nomercy|AUD-\d", re.IGNORECASE)

# Public integrations and the publisher: stripped before matching.
ALLOWED_STRINGS = (
    "github.com/NoMercyLabs/grimoira",
    "NoMercyLabs/grimoira",
    "grimoira@nomercylabs",
    "NoMercyLabs/skills",
    "nomercylabs@nomercylabs",
    "Copyright (c) 2026 NoMercy Labs",
)
# Authorship and the homepage name the publisher, not the documented domain.
ALLOWED_LINE = re.compile(r"^\s*(author|homepage):", re.IGNORECASE)

SKIP_DIRS = {".git", "__pycache__", "node_modules"}
SELF = "test_portability.py"


def clean(line: str) -> str:
    for allowed in ALLOWED_STRINGS:
        line = line.replace(allowed, "")
    return line


def hashed_hits(line: str) -> list[str]:
    hits = []
    for word in WORDS.findall(line.lower()):
        for start in range(len(word)):
            for end in range(start + MIN_PART, len(word) + 1):
                part = word[start:end]
                if hashlib.sha256(part.encode()).hexdigest() in HOME_DIGESTS:
                    hits.append(part)
    return hits


def find_leaks(root: str) -> list[str]:
    leaks = []
    for base, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in names:
            if name == SELF:
                continue
            path = os.path.join(base, name)
            try:
                with open(path, encoding="utf-8") as handle:
                    lines = handle.readlines()
            except (UnicodeDecodeError, OSError):
                continue
            for number, line in enumerate(lines, start=1):
                if ALLOWED_LINE.match(line):
                    continue
                text = clean(line)
                for pattern in (DOMAIN_WORDS, HOME_NAMES):
                    for match in pattern.finditer(text):
                        leaks.append(f"{os.path.relpath(path, root)}:{number}: {match.group(0)}")
                for part in hashed_hits(text):
                    leaks.append(f"{os.path.relpath(path, root)}:{number}: {part}")
    return leaks


class PortabilityTests(unittest.TestCase):
    def test_no_home_project_vocabulary(self):
        leaks = find_leaks(ROOT)
        self.assertEqual(leaks, [], "home-project vocabulary in a portable skill:\n" + "\n".join(leaks))

    def test_checker_catches_a_leak(self):
        import tempfile

        folder = tempfile.mkdtemp()
        with open(os.path.join(folder, "page.md"), "w", encoding="utf-8") as handle:
            handle.write("The Key" + "cloak realm\nsee github.com/NoMercyLabs/grimoira\nfinding AUD-12\nnotes\n")
        leaks = find_leaks(folder)
        self.assertEqual(len(leaks), 2, leaks)
        self.assertIn("page.md:1: key" + "cloak", leaks)
        self.assertIn("page.md:3: AUD-1", leaks)


if __name__ == "__main__":
    unittest.main()
