import hashlib
import json
import os
import unittest
from unittest import mock

from cruciblelib import lessons
from cruciblelib.common import CrucibleError, Root
from cruciblelib.permissions import log_action

from .helpers import CrucibleCase, run

SKILL = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PASSED = (True, "SELFTEST PASS")
SHAPE = "deploy.sh --env <str> --build <n>"


def skill_hashes():
    """A hash per file of the skill itself: a lesson must never change one."""
    found = {}
    for base, _dirs, names in os.walk(SKILL):
        if "__pycache__" in base:
            continue
        for name in names:
            with open(os.path.join(base, name), "rb") as fh:
                found[os.path.join(base, name)] = hashlib.sha256(fh.read()).hexdigest()
    return found


class LessonCase(CrucibleCase):
    def audit(self, files=None):
        return self.make_root(files or {"CLAUDE.md": "# Rules\n\nBe kind.\n"})

    def fail_rows(self, root, count, group="agent_runs", result="reader timed out after {n} seconds"):
        for n in range(count):
            log_action(Root(root), group, "reader unit-1", result.format(n=30 + n), "failed")

    def proposed(self, root, count=3):
        self.fail_rows(root, count)
        made = lessons.propose(Root(root))
        self.assertEqual(len(made), 1)
        return made[0]

    def write_lesson(self, root, lesson_id, change, target="audit"):
        path = os.path.join(root, "lessons", lesson_id + ".json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"id": lesson_id, "target": target, "kind": "hand", "signature": "x", "state": "proposed",
                       "evidence": {"count": 3, "records": ["actions.log#0", "actions.log#1", "actions.log#2"]},
                       "change": change, "expected": {"metric": "failures per run", "before": 3, "after": 0},
                       "check": "run learn review"}, fh)

    def log_at(self, root, at, result, count):
        with open(os.path.join(root, "actions.log"), "a", encoding="utf-8") as fh:
            for _ in range(count):
                fh.write(json.dumps({"at": at, "group": "agent_runs", "command": "reader unit-1",
                                     "result": result, "status": "failed"}) + "\n")


class LessonTests(LessonCase):
    def test_pattern_needs_three_occurrences(self):
        root, _ = self.audit()
        self.fail_rows(root, 2)
        self.assertEqual(lessons.find_patterns(Root(root)), [])
        self.assertEqual(lessons.propose(Root(root)), [])
        self.fail_rows(root, 1)
        found = lessons.find_patterns(Root(root))
        self.assertEqual([p["count"] for p in found], [3])
        self.assertEqual(len(lessons.propose(Root(root))), 1)

    def test_lesson_has_measured_evidence(self):
        root, _ = self.audit()
        lesson = self.proposed(root, count=4)
        self.assertEqual(lesson["evidence"]["count"], 4)
        self.assertEqual(len(lesson["evidence"]["records"]), 4)
        self.assertTrue(all(r.startswith("actions.log#") for r in lesson["evidence"]["records"]))
        self.assertEqual(lesson["expected"]["before"], 4)
        self.assertIsInstance(lesson["expected"]["after"], int)
        self.assertTrue(lesson["check"])
        self.assertTrue(lesson["change"])
        self.assertEqual(lesson["state"], "proposed")

    def test_lesson_applied_only_with_yes(self):
        root, _ = self.audit()
        lesson = self.proposed(root)
        with mock.patch.object(lessons, "run_selftest", return_value=PASSED):
            with self.assertRaises(CrucibleError):
                lessons.apply(Root(root), lesson["id"])
            self.assertEqual(lessons.load_lesson(Root(root), lesson["id"])["state"], "proposed")
            self.assertEqual(lessons.active(Root(root)), [])
            code, out, err = run(root, "learn", "apply", lesson["id"])
            self.assertNotEqual(code, 0)
            self.assertEqual(lessons.active(Root(root)), [])
            lessons.apply(Root(root), lesson["id"], yes=True)
        self.assertEqual([x["id"] for x in lessons.active(Root(root))], [lesson["id"]])

    def test_audit_lesson_in_local_layer_not_skill_files(self):
        root, _ = self.audit()
        lesson = self.proposed(root)
        before = skill_hashes()
        with mock.patch.object(lessons, "run_selftest", return_value=PASSED):
            lessons.apply(Root(root), lesson["id"], yes=True)
        self.assertEqual(skill_hashes(), before)
        path = os.path.join(root, "lessons", lesson["id"] + ".json")
        self.assertTrue(os.path.isfile(path))
        with open(path, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["state"], "active")

    def test_workflow_lesson_goes_through_user_change_flow(self):
        root, repo = self.audit()
        found = {"commands": 9, "scripts": [], "repeats": [
            {"shape": SHAPE, "runs": 4, "failed": 1, "retried": 1, "tokens": 800}]}
        made = lessons.propose(Root(root), repeats=found)
        self.assertEqual([m["target"] for m in made], ["workflow"])
        lesson_id = made[0]["id"]
        path = os.path.join(repo, "CLAUDE.md")
        with open(path, encoding="utf-8") as fh:
            original = fh.read()
        with self.assertRaises(CrucibleError):
            lessons.apply(Root(root), lesson_id, yes=True, repo=repo, rel="CLAUDE.md")
        plan = lessons.apply(Root(root), lesson_id, repo=repo, rel="CLAUDE.md", dry_run=True)
        self.assertIn("+", plan["diff"])
        with open(path, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), original)
        with self.assertRaises(CrucibleError):
            lessons.apply(Root(root), lesson_id, repo=repo, rel="CLAUDE.md")
        lessons.apply(Root(root), lesson_id, yes=True, repo=repo, rel="CLAUDE.md")
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        self.assertTrue(text.startswith(original))
        self.assertIn(SHAPE, text)
        self.assertTrue(os.listdir(os.path.join(root, "backups")))
        self.assertEqual(lessons.active(Root(root)), [])
        self.assertEqual(lessons.load_lesson(Root(root), lesson_id)["state"], "applied")

    def test_lesson_cannot_loosen_safety(self):
        root, _ = self.audit()
        bad = {"permissions": {"transcripts": "yes"}, "gate": "off", "visibility": "public",
               "privacy": False, "root_cause": "skip", "mystery": 1,
               "unit_size_factor": 2, "model_tier": {"low": "top"}}
        for number, (key, value) in enumerate(bad.items()):
            lesson_id = f"L-bad{number}"
            self.write_lesson(root, lesson_id, {key: value})
            with self.assertRaises(CrucibleError, msg=key):
                lessons.load_lesson(Root(root), lesson_id)
            with mock.patch.object(lessons, "run_selftest", return_value=PASSED):
                with self.assertRaises(CrucibleError, msg=key):
                    lessons.apply(Root(root), lesson_id, yes=True)
        self.write_lesson(root, "L-fine", {"unit_size_factor": 0.5})
        self.assertEqual(lessons.load_lesson(Root(root), "L-fine")["change"], {"unit_size_factor": 0.5})

    def test_lesson_must_pass_selftest(self):
        root, _ = self.audit()
        lesson = self.proposed(root)
        with mock.patch.object(lessons, "run_selftest", return_value=(False, "SELFTEST FAIL: found 3 of 12")):
            with self.assertRaises(CrucibleError) as caught:
                lessons.apply(Root(root), lesson["id"], yes=True)
        self.assertIn("SELFTEST FAIL: found 3 of 12", str(caught.exception))
        self.assertEqual(lessons.load_lesson(Root(root), lesson["id"])["state"], "proposed")
        self.assertEqual(lessons.active(Root(root)), [])
        ok, output = lessons.run_selftest(Root(root), lesson)
        self.assertTrue(ok, output)
        self.assertIn("SELFTEST PASS", output)

    def test_lesson_revert_by_id(self):
        root, _ = self.audit()
        lesson = self.proposed(root)
        with mock.patch.object(lessons, "run_selftest", return_value=PASSED):
            lessons.apply(Root(root), lesson["id"], yes=True)
        with self.assertRaises(CrucibleError):
            lessons.revert(Root(root), "L-nothing")
        code, out, err = run(root, "learn", "revert", lesson["id"])
        self.assertEqual(code, 0, err)
        self.assertEqual(lessons.active(Root(root)), [])
        self.assertEqual(lessons.load_lesson(Root(root), lesson["id"])["state"], "reverted")
        self.assertTrue(os.listdir(os.path.join(root, "backups")))
        code, out, err = run(root, "learn", "list")
        self.assertIn(f"{lesson['id']} reverted", out)

    def test_worse_lesson_proposed_for_revert(self):
        root, _ = self.audit()
        worse = self.proposed(root, count=3)
        with mock.patch.object(lessons, "run_selftest", return_value=PASSED):
            lessons.apply(Root(root), worse["id"], yes=True)
        path = os.path.join(root, "lessons", worse["id"] + ".json")
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        data["applied_at"] = "2030-01-01T00:00:00+00:00"
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        result = "reader timed out after 99 seconds"
        self.log_at(root, "2030-01-02T00:00:00+00:00", result, 4)
        first = lessons.review(Root(root), at="2030-01-02T12:00:00+00:00")
        self.assertEqual(first["revert"], [])
        self.log_at(root, "2030-01-03T00:00:00+00:00", result, 5)
        second = lessons.review(Root(root), at="2030-01-03T12:00:00+00:00")
        self.assertEqual(second["revert"], [worse["id"]])
        self.assertEqual(lessons.load_lesson(Root(root), worse["id"])["state"], "active")
        self.log_at(root, "2030-01-04T00:00:00+00:00", result, 1)
        third = lessons.review(Root(root), at="2030-01-04T12:00:00+00:00")
        self.assertEqual(third["revert"], [])


if __name__ == "__main__":
    unittest.main()
