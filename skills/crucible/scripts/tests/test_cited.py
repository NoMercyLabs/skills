import hashlib
import json
import os

from tests.helpers import CrucibleCase, good_finding, run

LINES = ["line %02d of the module" % n for n in range(1, 41)]


class CitedCase(CrucibleCase):
    def cited_root(self):
        files = {"app.py": "\n".join(LINES) + "\n", "other.py": "alpha\nbeta\ngamma\n"}
        finding = good_finding(
            title="Handler reads its token path unchecked",
            evidence=[{"kind": "file_line", "ref": "app.py:20", "quote": LINES[19]}])
        finding["chain"]["mechanism"][0].update(ref="other.py:2", evidence={
            "kind": "file_line", "ref": "other.py:2", "quote": "beta"})
        finding["chain"]["root_cause"].update(ref="app.py:30", evidence={
            "kind": "file_line", "ref": "app.py:30", "quote": LINES[29]})
        root = self.make_inventoried(files)
        unit = "svc-u01"
        self.write_ledger(root, unit, sorted(files), leads=[
            {"ref": "app.py:5", "suspect": "a dropped suspect", "dropped_because": "a stated reason"}])
        self.write(root, f"candidates/{unit}.json", [finding])
        return root, unit

    def test_cited_prints_only_cited_lines(self):
        root, unit = self.cited_root()
        code, out, err = run(root, "cited", unit)
        self.assertEqual(code, 0, err)
        want = "svc-u01#" + hashlib.sha1("Handler reads its token path unchecked".encode()).hexdigest()[:8]
        self.assertIn(want, out)
        self.assertIn("line 20 of the module", out)
        self.assertIn("line 17 of the module", out)
        self.assertIn("line 23 of the module", out)
        self.assertIn("line 30 of the module", out)
        self.assertIn("beta", out)
        self.assertIn("a dropped suspect", out)
        self.assertNotIn("line 10 of the module", out)
        self.assertNotIn("line 26 of the module", out)
        self.assertNotIn("line 40 of the module", out)
        self.assertRegex(out, r"\b20\|")

    def test_cited_prints_verdict_shape(self):
        root, unit = self.cited_root()
        code, out, err = run(root, "cited", unit)
        self.assertEqual(code, 0, err)
        self.assertIn('"verdict": "accept|reject|fix"', out)
        self.assertIn("other_defect", out)
        self.assertIn("root_cause_verified", out)
        self.assertLess(out.index("=== END cited ==="), out.index('"verdict": "accept|reject|fix"'))

    def test_cited_selects_several_candidates(self):
        root, unit = self.cited_root()
        second = good_finding(title="Second candidate here",
                              evidence=[{"kind": "file_line", "ref": "other.py:1", "quote": "alpha"}])
        first = json.loads(self.read_text(os.path.join(root, "candidates", f"{unit}.json")))[0]
        self.write(root, f"candidates/{unit}.json", [first, second])
        ids = ["svc-u01#" + hashlib.sha1(t.encode()).hexdigest()[:8]
               for t in ("Handler reads its token path unchecked", "Second candidate here")]
        code, out, err = run(root, "cited", unit, ids[1])
        self.assertEqual(code, 0, err)
        self.assertIn("Second candidate here", out)
        self.assertNotIn("Handler reads its token path unchecked", out)
        code, out, err = run(root, "cited", unit, *ids)
        self.assertIn("Handler reads its token path unchecked", out)
        self.assertIn("Second candidate here", out)
        code, out, err = run(root, "cited", unit, "svc-u01#00000000")
        self.assertEqual(code, 1)
        self.assertIn("unknown candidate", err)

    def test_cited_refuses_unknown_unit(self):
        root, unit = self.cited_root()
        code, out, err = run(root, "cited", "nope-u99")
        self.assertEqual(code, 1)
        self.assertIn("unknown unit", err)
        self.assertNotIn("Traceback", out + err)

    def test_verifier_brief_starts_with_cited(self):
        base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        text = self.read_text(os.path.join(base, "agents", "verifier.md"))
        cited = text.index("crucible.py --root ROOT cited UNIT")
        for other in ("crucible.py --root ROOT explore", "crucible.py --root ROOT show"):
            self.assertLess(cited, text.index(other))
        self.assertNotIn("hashlib.sha1", text)
