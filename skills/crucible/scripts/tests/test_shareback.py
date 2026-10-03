import json
import os
import unittest

from cruciblelib import shareback
from cruciblelib.common import CrucibleError, Root
from cruciblelib.permissions import read_log

from .helpers import CrucibleCase, run

PLANTED = ("C:/Users/jane/code/payments-api/src/billing.py", "payments-api", "Jane Doe",
           "https://git.example.org/acme/payments-api/issues/7", "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8")


def lesson(**over):
    row = {"id": "L-1a2b3c4d", "target": "audit", "kind": "unit_size", "signature": PLANTED[0], "state": "proposed",
           "general": True,
           "evidence": {"count": 4, "records": [f"actions.log:{p}" for p in PLANTED]},
           "change": {"unit_size_factor": 0.75, "reader_addendum": f"skip {PLANTED[1]} owned by {PLANTED[2]}"},
           "expected": {"metric": f"failures in {PLANTED[1]} {PLANTED[3]}", "before": 4, "after": 0},
           "check": f"look at {PLANTED[0]} with {PLANTED[4]}"}
    row.update(over)
    return row


class ShareBackTests(CrucibleCase):
    def setUp(self):
        self.root = Root(self.make_root({"a.py": "x = 1\n"})[0])

    def test_share_back_off_by_default(self):
        self.assertIsNone(shareback.offer(self.root, lesson()))
        self.assertNotIn("share_back", self.root.config())
        with self.assertRaises(CrucibleError):
            shareback.answer(self.root, lesson(), "yes", "sure")
        shareback.enable(self.root, "the user said so")
        offered = shareback.offer(self.root, lesson())
        self.assertIn("public issue", offered["question"])
        self.assertIsNone(shareback.offer(self.root, lesson(general=False)))
        self.assertIsNone(shareback.offer(self.root, lesson(target="workflow")))

    def test_share_back_text_has_no_project_detail(self):
        shareback.enable(self.root, "the user said so")
        text = shareback.offer(self.root, lesson())["text"]
        self.assertIn("unit_size_factor", text)
        self.assertIn("4", text)
        for planted in PLANTED + ("billing", "jane", "acme", "example.org"):
            self.assertNotIn(planted.lower(), text.lower())
        with self.assertRaises(CrucibleError):
            shareback.offer(self.root, lesson(kind=PLANTED[0]))
        with self.assertRaises(CrucibleError):
            shareback.offer(self.root, lesson(change={"model_tier": PLANTED[4]}))

    def test_share_back_refuses_a_draft_with_a_privacy_word(self):
        cfg = self.root.config()
        cfg["privacy_words"] = ["acme"]
        self.root.save_config(cfg)
        shareback.enable(self.root, "the user said so")
        with self.assertRaises(CrucibleError) as caught:
            shareback.offer(self.root, lesson(change={"recovery": "acme_retry"}))
        self.assertIn("privacy word acme", str(caught.exception))
        with self.assertRaises(CrucibleError):
            shareback.answer(self.root, lesson(change={"recovery": "acme_retry"}), "yes", "go ahead")
        self.assertIn("unit_size_factor", shareback.offer(self.root, lesson())["text"])

    def test_share_back_needs_yes(self):
        shareback.enable(self.root, "the user said so")
        with self.assertRaises(CrucibleError):
            shareback.final_text(self.root, lesson())
        with self.assertRaises(CrucibleError):
            shareback.answer(self.root, lesson(), "yes", "")
        with self.assertRaises(CrucibleError):
            shareback.answer(self.root, lesson(), "maybe", "unsure")
        self.assertEqual(read_log(self.root), [])
        self.assertIsNone(shareback.answer(self.root, lesson(), "no", "not this one"))
        self.assertIsNone(shareback.offer(self.root, lesson()))
        with self.assertRaises(CrucibleError):
            shareback.answer(self.root, lesson(), "yes", "changed my mind")
        with self.assertRaises(CrucibleError):
            shareback.final_text(self.root, lesson())
        other = lesson(id="L-9z9z9z9z")
        text = shareback.answer(self.root, other, "yes", "go ahead")
        self.assertEqual(text, shareback.final_text(self.root, other))
        self.assertIn("nothing was sent", read_log(self.root)[-1]["result"])
        with open(os.path.join(self.root.path, "config.json"), encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["share_back"]["answers"]["L-1a2b3c4d"]["answer"], "no")


class ReportOfferTests(CrucibleCase):
    def report(self, enabled, change):
        config = {"share_back": {"enabled": True, "answers": {}}} if enabled else None
        root = self.make_root({"a.py": "x = 1\n"}, config=config)[0]
        folder = os.path.join(root, "lessons")
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "L-1a2b3c4d.json"), "w", encoding="utf-8") as fh:
            json.dump({"id": "L-1a2b3c4d", "target": "audit", "kind": "unit_size", "signature": "x", "state": "active",
                       "evidence": {"count": 3, "records": ["actions.log#0"]}, "change": change,
                       "expected": {"metric": "failures per run", "before": 3, "after": 0},
                       "check": "run learn review"}, fh)
        code, out, err = run(root, "report")
        self.assertEqual(code, 0, err)
        return out

    def test_report_offers_shareback_when_enabled(self):
        out = self.report(True, {"unit_size_factor": 0.75})
        self.assertIn("shareback offer L-1a2b3c4d", out)
        self.assertIn("nothing is sent without your yes", out)
        self.assertNotIn("shareback offer", self.report(False, {"unit_size_factor": 0.75}))
        self.assertNotIn("shareback offer", self.report(True, {"reader_addendum": "skip src/billing.py"}))


if __name__ == "__main__":
    unittest.main()
