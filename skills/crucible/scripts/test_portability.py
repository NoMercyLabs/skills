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
# Names and tooling of the home projects: matched anywhere in a line.
HOME_NAMES = re.compile(r"keycloak|droplet|stoney|fillz|moooom|arcanum|nomercy|AUD-\d", re.IGNORECASE)

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
    return leaks


class PortabilityTests(unittest.TestCase):
    def test_no_home_project_vocabulary(self):
        leaks = find_leaks(ROOT)
        self.assertEqual(leaks, [], "home-project vocabulary in a portable skill:\n" + "\n".join(leaks))

    def test_checker_catches_a_leak(self):
        import tempfile

        folder = tempfile.mkdtemp()
        with open(os.path.join(folder, "page.md"), "w", encoding="utf-8") as handle:
            handle.write("The Keycloak realm\nsee github.com/NoMercyLabs/grimoira\nfinding AUD-12\nnotes\n")
        leaks = find_leaks(folder)
        self.assertEqual(len(leaks), 2, leaks)
        self.assertIn("page.md:1: Keycloak", leaks)
        self.assertIn("page.md:3: AUD-1", leaks)


if __name__ == "__main__":
    unittest.main()
