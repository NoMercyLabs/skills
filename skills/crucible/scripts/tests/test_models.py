import json
import os

from .helpers import CrucibleCase, run

FILES = {
    "auth/login.py": "def login(request):\n    password = request.form['password']\n    return session_token(password)\n",
    "app.py": "def total(items):\n    return sum(items)\n",
    "docs/guide.md": "# Guide\n\nHow to run it.\n",
}
FABLE_JOBS = {"group_by_cause", "verify_critical", "blocker_root_cause", "priority_order"}


class ModelPlanTests(CrucibleCase):
    def setup_root(self, confirm=False):
        root, repo = self.make_root(FILES, confirm=confirm, config={"unit_bytes": 1})
        return root

    def plan(self, root):
        code, out, err = run(root, "models")
        self.assertEqual(code, 0, err)
        with open(os.path.join(root, "model-plan.json"), encoding="utf-8") as fh:
            return json.load(fh), out

    def allow_fable(self, root, value):
        code, out, err = run(root, "answer", "models.fable", value, "--words", "the user said so")
        self.assertEqual(code, 0, err)

    def test_model_plan_explains_each_role(self):
        plan, out = self.plan(self.setup_root())
        for role in ("reader", "verifier", "blocker_fix"):
            entry = plan["roles"][role]
            self.assertTrue(entry["tier"] in ("fast", "balanced", "strong", "top"), role)
            self.assertTrue(entry["reason"].strip(), role)
            self.assertIsInstance(entry["tokens"], int, role)
            self.assertIn(role, out)
        self.assertEqual(set(plan["complex_jobs"]), FABLE_JOBS)
        for job in plan["complex_jobs"].values():
            self.assertTrue(job["reason"].strip())
        self.assertIn("model availability was not checked", out)

    def test_risk_sets_reader_tier(self):
        plan, out = self.plan(self.setup_root())
        risks = {u["files"][0]: (u["risk"], u["reader_tier"]) for u in plan["units"]}
        self.assertEqual(risks["auth/login.py"], ("high", "balanced"))
        self.assertEqual(risks["app.py"], ("normal", "balanced"))
        self.assertEqual(risks["docs/guide.md"], ("low", "fast"))
        self.assertEqual(plan["roles"]["reader"]["units_per_tier"], {"balanced": 2, "fast": 1})
        self.assertIn("fast: 1 units", out)

    def test_critical_gets_strong_verifier(self):
        plan, out = self.plan(self.setup_root())
        self.assertEqual(plan["roles"]["verifier"]["tier"], "balanced")
        self.assertEqual(plan["roles"]["verifier"]["critical_tier"], "strong")

    def test_verifier_gets_cited_lines_only(self):
        plan, out = self.plan(self.setup_root())
        verifier = plan["roles"]["verifier"]
        self.assertEqual(verifier["input"], "cited_lines_only")
        self.assertIn("cited line", verifier["reason"])
        self.assertLess(verifier["tokens"], plan["roles"]["reader"]["tokens"])

    def test_estimate_follows_model_plan(self):
        root = self.setup_root(confirm=True)
        self.assertEqual(run(root, "inventory")[0], 0)
        code, out, err = run(root, "estimate")
        self.assertEqual(code, 0, err)
        self.assertIn("tier fast:", out)
        self.assertIn("tier balanced:", out)
        self.assertNotIn("tier top:", out)
        self.allow_fable(root, "true")
        code, out, err = run(root, "estimate")
        self.assertIn("tier top:", out)
        run(root, "answer", "models", '{"reader": "strong"}', "--words", "stronger readers")
        code, out, err = run(root, "estimate")
        self.assertIn("tier strong:", out)

    def test_fable_needs_user_permission(self):
        root = self.setup_root()
        code, out, err = run(root, "answer", "models.fable", "true")
        self.assertEqual(code, 1)
        self.assertIn("--words", err)
        code, out, err = run(root, "answer", "models.fable", "maybe", "--words", "x")
        self.assertEqual(code, 1)
        root2 = self.make_root(FILES, confirm=False)[0]
        self.answer_everything(root2)
        run(root2, "answer", "models.fable", "true", "--words", "x")
        self.assertEqual(run(root2, "confirm")[0], 0)
        root3 = self.make_root(FILES, confirm=False)[0]
        for command in (["answer", "auto_file", "false"], ["answer", "blocker_fixes", '{"mode": "never"}']):
            run(root3, *command, "--words", "x")
        self.answer_brief(root3)
        self.answer_visibility(root3)
        self.answer_workspace(root3)
        from cruciblelib.permissions import GROUPS
        for group in GROUPS:
            run(root3, "grant", group, "no", "--words", "x")
        code, out, err = run(root3, "confirm")
        self.assertEqual(code, 1)
        self.assertIn("models.fable", err)

    def test_fable_only_for_listed_complex_tasks(self):
        root = self.setup_root()
        self.allow_fable(root, "true")
        plan, out = self.plan(root)
        self.assertTrue(plan["fable"])
        self.assertEqual({n for n, j in plan["complex_jobs"].items() if j["tier"] == "top"}, FABLE_JOBS)
        for role, entry in plan["roles"].items():
            self.assertNotEqual(entry["tier"], "top", role)
        self.assertNotIn("top", plan["roles"]["reader"]["units_per_tier"])
        self.assertEqual(plan["roles"]["verifier"]["critical_tier"], "top")
        self.assertIn("with Fable", out)
        self.assertIn("without Fable", out)

    def test_no_fable_falls_back_to_strong(self):
        for answer in (None, "false"):
            root = self.setup_root()
            if answer:
                self.allow_fable(root, answer)
            plan, out = self.plan(root)
            self.assertFalse(plan["fable"])
            self.assertEqual({j["tier"] for j in plan["complex_jobs"].values()}, {"strong"})
            self.assertEqual(plan["roles"]["verifier"]["critical_tier"], "strong")
            self.assertNotIn('"top"', json.dumps(plan["roles"]))
            if answer is None:
                self.assertIn("not answered", out)
