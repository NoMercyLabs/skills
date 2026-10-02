import json
import os

from cruciblelib import brief
from cruciblelib.gate import check_finding
from cruciblelib.common import Root

from .helpers import CrucibleCase, good_finding, run, verdict, src

FILES = {
    "README.md": "# Tool\nA small tool.\n",
    "docs/guide.md": "guide\n",
    "docs/adr/0001-choice.md": "decision\n",
    "docs/server.key": "PRIVATE KEY MATERIAL\n",
    "CONTRIBUTING.md": "how to contribute\n",
    "SECURITY.md": "report here\n",
    "package.json": '{"name": "tool", "description": "x"}\n',
    ".env": "SECRET_VALUE=abc\n",
    "app.py": "x = 1\n",
}
FIELDS = ("purpose", "good", "intentional", "must_never_change", "accepted_risks", "out_of_scope", "known_issues")


def answer_all(case, root, **words):
    for field in FIELDS:
        code, out, err = run(root, "brief", "answer", field, "--words", words.get(field, f"my words for {field}"))
        case.assertEqual(code, 0, err)


def fresh(case, files=None):
    root, repo = case.make_root(files or FILES, confirm=False)
    case.answer_everything(root, brief=False)
    return root


class BriefCollectTests(CrucibleCase):
    def test_brief_collect_lists_self_description_paths_only(self):
        root = fresh(self)
        code, out, err = run(root, "brief", "collect")
        self.assertEqual(code, 0, err)
        for path in ("README.md", "docs/guide.md", "docs/adr/0001-choice.md", "CONTRIBUTING.md", "SECURITY.md",
                     "package.json"):
            self.assertIn(path, out)
        self.assertNotIn("app.py", out)
        self.assertNotIn("A small tool", out)

    def test_brief_collect_skips_secret_files(self):
        root = fresh(self)
        code, out, err = run(root, "brief", "collect")
        self.assertEqual(code, 0, err)
        self.assertNotIn(".env", out)
        self.assertNotIn("server.key", out)
        self.assertNotIn("SECRET_VALUE", out)
        self.assertNotIn("server.key", json.dumps(Root(root).p()) + self.read_text(os.path.join(root, "brief.json")))


class BriefAnswerTests(CrucibleCase):
    def test_brief_answer_needs_the_users_words(self):
        root = fresh(self)
        code, out, err = run(root, "brief", "answer", "purpose")
        self.assertNotEqual(code, 0)
        code, out, err = run(root, "brief", "answer", "purpose", "--words", "  ")
        self.assertEqual(code, 1)
        self.assertIn("--words", err)

    def test_brief_answer_refuses_an_unknown_field(self):
        root = fresh(self)
        code, out, err = run(root, "brief", "answer", "colour", "--words", "blue")
        self.assertEqual(code, 1)
        self.assertIn("purpose", err)

    def test_brief_show_prints_answers_and_status(self):
        root = fresh(self)
        run(root, "brief", "answer", "purpose", "--words", "keeps the logs tidy for ops")
        code, out, err = run(root, "brief", "show")
        self.assertEqual(code, 0, err)
        self.assertIn("keeps the logs tidy for ops", out)
        self.assertIn("not confirmed", out)
        self.assertIn("must_never_change", out)

    def test_brief_confirm_refuses_with_a_question_unanswered(self):
        root = fresh(self)
        run(root, "brief", "answer", "purpose", "--words", "w")
        code, out, err = run(root, "brief", "confirm")
        self.assertEqual(code, 1)
        self.assertIn("good", err)

    def test_brief_confirm_stores_answers_verbatim_and_labelled_summary(self):
        root = fresh(self)
        run(root, "brief", "collect")
        answer_all(self, root, purpose="Tijd voor 'quotes' & <tags> é")
        summary = os.path.join(self.tmp(), "summary.json")
        with open(summary, "w", encoding="utf-8") as fh:
            json.dump([{"line": "A small tool.", "source": "README.md"}], fh)
        code, out, err = run(root, "brief", "summary", summary)
        self.assertEqual(code, 0, err)
        code, out, err = run(root, "brief", "confirm")
        self.assertEqual(code, 0, err)
        text = self.read_text(os.path.join(root, "project-brief.md"))
        self.assertIn("Tijd voor 'quotes' & <tags> é", text)
        self.assertIn("agent-written, not confirmed", text)
        self.assertIn("A small tool. (README.md)", text)
        self.assertIn("intentional", text.lower())
        self.assertIn("confirmed by the user", text)

    def test_brief_summary_refuses_a_source_that_was_not_collected(self):
        root = fresh(self)
        run(root, "brief", "collect")
        summary = os.path.join(self.tmp(), "summary.json")
        with open(summary, "w", encoding="utf-8") as fh:
            json.dump([{"line": "invented", "source": "nowhere.md"}], fh)
        code, out, err = run(root, "brief", "summary", summary)
        self.assertEqual(code, 1)
        self.assertIn("nowhere.md", err)

    def test_brief_answer_after_confirm_needs_a_new_confirm(self):
        root = fresh(self)
        answer_all(self, root)
        self.assertEqual(run(root, "brief", "confirm")[0], 0)
        run(root, "brief", "answer", "purpose", "--words", "changed my mind")
        self.assertIn("not confirmed", run(root, "brief", "show")[1])


class ConfirmNeedsBriefTests(CrucibleCase):
    def test_confirm_needs_confirmed_brief(self):
        root = fresh(self)
        code, out, err = run(root, "confirm")
        self.assertEqual(code, 1)
        self.assertIn("brief", err)
        self.assertFalse(Root(root).config()["confirmed"])
        answer_all(self, root)
        self.assertEqual(run(root, "confirm")[0], 1)
        self.assertEqual(run(root, "brief", "confirm")[0], 0)
        self.assertEqual(run(root, "confirm")[0], 0)


def intent_problems(root, finding):
    """Only the intent problems of the gate: the sample finding's evidence needs an inventoried snapshot."""
    return [p for p in check_finding(Root(root), finding) if p.startswith("intent")]


class IntentFieldTests(CrucibleCase):
    def root(self):
        root, repo = self.make_root({"app.py": "import os\nTOKEN_PATH = os.environ['X']\nrun(query)\n"})
        return root

    def test_intent_field_required(self):
        root = self.root()
        finding = good_finding()
        del finding["intent"]
        problems = intent_problems(root, finding)
        self.assertTrue(any(p.startswith("intent") for p in problems), problems)
        finding["intent"] = "  "
        self.assertTrue(any(p.startswith("intent") for p in intent_problems(root, finding)))
        finding["intent"] = brief.NO_CONFLICT
        self.assertEqual(intent_problems(root, finding), [])

    def test_intent_field_accepts_a_brief_line_with_its_kind(self):
        root = self.root()
        finding = good_finding(intent="accepted_risks: tokens live in the environment",
                               intent_kind="accepted_risk")
        run(root, "brief", "answer", "accepted_risks", "--words", "tokens live in the environment")
        self.assertEqual(intent_problems(root, finding), [])

    def test_intent_field_refuses_a_line_that_is_not_in_the_brief(self):
        root = self.root()
        finding = good_finding(intent="invented line nobody said", intent_kind="conflicts_intent")
        problems = intent_problems(root, finding)
        self.assertTrue(any("brief" in p for p in problems), problems)

    def test_intent_field_needs_a_kind_with_a_brief_line_and_none_without(self):
        root = self.root()
        run(root, "brief", "answer", "intentional", "--words", "odd sorting on purpose")
        no_kind = good_finding(intent="intentional: odd sorting on purpose")
        self.assertTrue(any("intent_kind" in p for p in intent_problems(root, no_kind)))
        stray = good_finding(intent_kind="out_of_scope")
        self.assertTrue(any("intent_kind" in p for p in intent_problems(root, stray)))


class IntentRoutingTests(CrucibleCase):
    FILES = {"app.py": "import os\nTOKEN_PATH = os.environ['X']\nrun(query)\n"}

    def accepted(self, **over):
        finding = good_finding(**over)
        root, unit = self.prepared_unit([finding], files=self.FILES)
        run(root, "brief", "answer", "intentional", "--words", "tokens come from the environment")
        run(root, "brief", "answer", "accepted_risks", "--words", "a missing variable stops the start")
        run(root, "brief", "answer", "out_of_scope", "--words", "windows service wrappers")
        self.write(root, f"review/verdicts-{unit}.json", {src(unit, finding): verdict()})
        return root, unit

    def accept(self, root, unit, *extra):
        code, out, err = run(root, "accept", unit, *extra)
        return code, out, err

    def test_plain_finding_with_no_conflict_is_filed(self):
        root, unit = self.accepted()
        code, out, err = self.accept(root, unit)
        self.assertEqual(code, 0, out + err)
        self.assertEqual(len(Root(root).findings()), 1)

    def test_finding_against_intent_becomes_question(self):
        root, unit = self.accepted(intent="intentional: tokens come from the environment",
                                   intent_kind="conflicts_intent")
        code, out, err = self.accept(root, unit)
        self.assertEqual(code, 0, out + err)
        self.assertEqual(Root(root).findings(), {})
        code, out, err = run(root, "report")
        self.assertIn("questions for you", out)
        self.assertIn("you said", out)
        self.assertIn("tokens come from the environment", out)
        self.assertIn("Handler reads its token path unchecked", out)

    def test_accepted_risk_not_filed(self):
        root, unit = self.accepted(intent="accepted_risks: a missing variable stops the start",
                                   intent_kind="accepted_risk")
        code, out, err = self.accept(root, unit)
        self.assertEqual(code, 0, out + err)
        self.assertEqual(Root(root).findings(), {})
        report = run(root, "report")[1]
        self.assertIn("accepted by you", report)

    def test_accepted_risk_filed_when_the_user_asks(self):
        root, unit = self.accepted(intent="accepted_risks: a missing variable stops the start",
                                   intent_kind="accepted_risk")
        code, out, err = self.accept(root, unit, "--file-accepted-risks")
        self.assertEqual(code, 0, out + err)
        self.assertEqual(len(Root(root).findings()), 1)

    def test_out_of_scope_finding_not_filed(self):
        root, unit = self.accepted(intent="out_of_scope: windows service wrappers", intent_kind="out_of_scope")
        code, out, err = self.accept(root, unit)
        self.assertEqual(code, 0, out + err)
        self.assertEqual(Root(root).findings(), {})
        report = run(root, "report")[1]
        self.assertIn("out of scope", report)
        self.assertIn("Handler reads its token path unchecked", report)

    def test_routed_finding_with_a_bad_intent_still_fails_the_gate(self):
        root, unit = self.accepted(intent="invented", intent_kind="out_of_scope")
        code, out, err = self.accept(root, unit)
        self.assertEqual(code, 1, out + err)
        self.assertEqual(Root(root).findings(), {})


class FixPlanTests(CrucibleCase):
    def root(self):
        root, repo = self.make_root({"app.py": "x = 1\n"})
        run(root, "brief", "answer", "must_never_change",
            "--words", "the /v1/users response format; config/app.json keys")
        return Root(root)

    def test_fix_touching_must_not_change_refused(self):
        root = self.root()
        problems = brief.fix_plan_problems(root, {"touches": ["config/app.json"]})
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("must never change", problems[0])
        problems = brief.fix_plan_problems(root, {"touches": ["src/routes/v1/users.py", "the /v1/users response format"]})
        self.assertTrue(problems)

    def test_fix_touching_something_else_passes(self):
        root = self.root()
        self.assertEqual(brief.fix_plan_problems(root, {"touches": ["app.py", "docs/readme.md"]}), [])

    def test_fix_plan_without_a_touches_list_is_refused(self):
        root = self.root()
        self.assertTrue(brief.fix_plan_problems(root, {}))
        self.assertTrue(brief.fix_plan_problems(root, {"touches": []}))


class BriefShapeTests(CrucibleCase):
    def test_briefs_for_agents_and_references_name_the_brief_by_path(self):
        base = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        for rel in ("agents/reader.md", "agents/verifier.md", "references/project-brief.md",
                    "references/finding-schema.md"):
            text = self.read_text(os.path.join(base, *rel.split("/")))
            self.assertIn("project-brief", text, rel)
        interview = self.read_text(os.path.join(base, "references", "interview.md"))
        self.assertLess(interview.index("## 0."), interview.index("## 1. Scope"))
        verifier = self.read_text(os.path.join(base, "agents", "verifier.md"))
        for kind in ("conflicts_intent", "accepted_risk", "out_of_scope"):
            self.assertIn(kind, verifier)
