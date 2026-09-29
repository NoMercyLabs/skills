#!/usr/bin/env python3
"""The skill stays portable: no vocabulary from the project it was written in.

SKILL.md ends on the rule: every example is drawn from constructs that exist
everywhere, a request, an element, a worker, a config file. A rule nobody
checks leaked twice (a playback comment, then a whole section about a media
player's chapters, previews and autoplay), so this test checks it. The list
holds the home project's domain words; extend it when a new leak is found.
Standard library only: python3 -m unittest test_portability.py
"""

from __future__ import annotations

import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

HOME_PROJECT_WORDS = re.compile(
    r"\b(player|playback|playlist|chapters?|subtitles?|lyrics|scrubber|seek|seeking|"
    r"autoplay|media server|encoder|transcod\w*|codec|hls|m3u8|nomercy)\b",
    re.IGNORECASE,
)
# Authorship and the homepage name the publisher, not the documented domain.
ALLOWED_LINE = re.compile(r"^\s*(author|homepage):", re.IGNORECASE)


class PortabilityTests(unittest.TestCase):
    def test_no_home_project_vocabulary(self):
        leaks = []
        for base, _dirs, names in os.walk(ROOT):
            for name in names:
                if not name.endswith((".md", ".py")) or name == "test_portability.py":
                    continue
                path = os.path.join(base, name)
                with open(path, encoding="utf-8") as handle:
                    for number, line in enumerate(handle, start=1):
                        if ALLOWED_LINE.match(line):
                            continue
                        for word in HOME_PROJECT_WORDS.findall(line):
                            leaks.append(f"{os.path.relpath(path, ROOT)}:{number}: {word}")
        self.assertEqual(leaks, [], "home-project vocabulary in a portable skill:/n" + "\n".join(leaks))


if __name__ == "__main__":
    unittest.main()
