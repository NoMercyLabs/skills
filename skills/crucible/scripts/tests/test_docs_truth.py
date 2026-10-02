import glob
import os
import re
import unittest

from .helpers import CrucibleCase

SKILL = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SIBLINGS = (["HOW-IT-WORKS.md", "README.md", "SKILL.md", "SECURITY.md"]
            + sorted(os.path.relpath(p, SKILL) for p in glob.glob(os.path.join(SKILL, "references", "*.md")))
            + sorted(os.path.relpath(p, SKILL) for p in glob.glob(os.path.join(SKILL, "agents", "*.md")))
            + sorted(os.path.relpath(p, SKILL) for p in glob.glob(os.path.join(SKILL, "docs", "**", "*.md"), recursive=True)))
CLAIMS = re.compile(r"opens? no (?:network )?socket|never downloads?|does not download|no download"
                    r"|never fixes product code|imports no network module", re.IGNORECASE)
GRANTS = re.compile(r"blocker_fixes|blocker_pushes|workspace_clones|knowledge_clone|knowledge_sources")
HONEST = ("blocker_fixes", "blocker_pushes", "workspace_clones", "knowledge_clone", "knowledge_sources", "`git`", "`gh`")


def sentences(text):
    return [s for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]


class DocsTruthTests(CrucibleCase):
    def read(self, rel):
        return self.read_text(os.path.join(SKILL, rel))

    def test_docs_network_claim_names_grants(self):
        for rel in SIBLINGS:
            for sentence in sentences(self.read(rel)):
                if CLAIMS.search(sentence):
                    self.assertTrue(GRANTS.search(sentence), f"{rel}: claims no network or no fixes without a grant: {sentence!r}")
        for rel in ("HOW-IT-WORKS.md", "SECURITY.md"):
            text = self.read(rel)
            for name in HONEST:
                self.assertIn(name, text, f"{rel} does not name {name}")


if __name__ == "__main__":
    unittest.main()
