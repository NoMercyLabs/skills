import json
import os
from unittest import mock

from cruciblelib import clones, knowledge
from cruciblelib.common import CrucibleError, Root

from .helpers import CrucibleCase, run

FILES = {"app.py": "x = 1\n"}
FAKE_KEY = "sk-" + "A1b2C3d4E5f6G7h8I9j0"


class KnowledgeCase(CrucibleCase):
    def export(self, files):
        folder = self.tmp()
        for rel, text in files.items():
            full = os.path.join(folder, *rel.split("/"))
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(text)
        return folder

    def granted(self, *sources, words=None):
        root, repo = self.make_root(FILES, config={"privacy_words": words or []})
        if sources:
            code, out, err = run(root, "grant", "knowledge_sources", "yes", "--reopen", "--words", "yes please",
                                 "--bound", "sources=" + ",".join(sources))
            self.assertEqual(code, 0, err)
        return root

    def written(self, root, name):
        base = Root(root).p("knowledge", name)
        found = {}
        for folder, _, names in os.walk(base):
            for n in names:
                full = os.path.join(folder, n)
                with open(full, encoding="utf-8") as fh:
                    found[os.path.relpath(full, base).replace(os.sep, "/")] = fh.read()
        return found

    def all_text(self, root):
        out = []
        for folder, _, names in os.walk(root):
            for n in names:
                with open(os.path.join(folder, n), encoding="utf-8", errors="replace") as fh:
                    out.append(fh.read())
        return "\n".join(out)

    def action_rows(self, root):
        with open(Root(root).p("actions.log"), encoding="utf-8") as fh:
            return [json.loads(line) for line in fh]


class FetchTests(KnowledgeCase):
    def test_knowledge_source_needs_grant(self):
        folder = self.export({"a.md": "# runbook\nrestart it\n"})
        root = self.granted()
        code, out, err = run(root, "knowledge", "fetch", f"folder:{folder}")
        self.assertEqual(code, 1)
        self.assertIn("refused: knowledge_sources", err)
        self.assertFalse(os.path.exists(Root(root).p("knowledge")))
        self.assertEqual(self.action_rows(root)[-1]["status"], "refused")
        root = self.granted("other")
        code, out, err = run(root, "knowledge", "fetch", f"folder:{folder}")
        self.assertEqual(code, 1)
        self.assertIn("not granted", err)
        self.assertFalse(os.path.exists(Root(root).p("knowledge")))

    def test_folder_export_is_copied_as_markdown_and_logged(self):
        folder = self.export({"chat/general.txt": "hello team\n", "wiki/page.md": "# page\n",
                              "wiki/image.png": "not text", ".env": "A=1\n"})
        spec = f"folder:{folder}"
        root = self.granted(spec)
        code, out, err = run(root, "knowledge", "fetch", spec)
        self.assertEqual(code, 0, err)
        docs = self.written(root, knowledge.source_name(spec))
        self.assertEqual(sorted(docs), ["chat/general.txt.md", "wiki/page.md"])
        entry = Root(root).state()["knowledge"][knowledge.source_name(spec)]
        self.assertEqual((entry["status"], entry["count"]), ("absorbed", 2))
        self.assertIn("grimoira index-docs --from", out)
        last = self.action_rows(root)[-1]
        self.assertEqual((last["group"], last["status"]), ("knowledge_sources", "ok"))

    def test_named_source_from_config_resolves(self):
        folder = self.export({"a.md": "text\n"})
        root, repo = self.make_root(FILES, config={"knowledge_sources": [
            {"name": "wiki", "kind": "folder", "target": folder}]})
        self.assertEqual(run(root, "grant", "knowledge_sources", "yes", "--reopen", "--words", "yes",
                             "--bound", "sources=wiki")[0], 0)
        code, out, err = run(root, "knowledge", "fetch", "wiki")
        self.assertEqual(code, 0, err)
        self.assertEqual(sorted(self.written(root, "wiki")), ["a.md"])

    def test_github_source_reads_issues_prs_and_discussions(self):
        calls = []

        def fake_gh(args, stdin=None):
            calls.append(args)
            if args[0] == "issue":
                return json.dumps([{"number": 1, "title": "Slow start", "body": "it hangs", "state": "OPEN",
                                    "comments": [{"body": "same here"}]}])
            if args[0] == "pr":
                return json.dumps([{"number": 2, "title": "Fix hang", "body": "patch", "state": "MERGED",
                                    "comments": []}])
            return json.dumps({"data": {"repository": {"discussions": {"nodes": [
                {"number": 3, "title": "How to deploy", "body": "use compose", "comments": {"nodes": []}}]}}}})

        self.addCleanup(setattr, knowledge, "run_gh", knowledge.run_gh)
        knowledge.run_gh = fake_gh
        spec = "github:acme/tool"
        root = self.granted(spec)
        code, out, err = run(root, "knowledge", "fetch", spec)
        self.assertEqual(code, 0, err)
        docs = self.written(root, knowledge.source_name(spec))
        self.assertEqual(sorted(docs), ["discussions.md", "issues.md", "pulls.md"])
        self.assertIn("Slow start", docs["issues.md"])
        self.assertIn("same here", docs["issues.md"])
        self.assertIn("How to deploy", docs["discussions.md"])
        self.assertTrue(all(c[0] in ("issue", "pr", "api") for c in calls))
        self.assertTrue(all("create" not in c and "POST" not in c for c in calls))


class MaskingTests(KnowledgeCase):
    def test_fetched_knowledge_masks_secrets(self):
        folder = self.export({"notes/ops.md": f"deploy with key {FAKE_KEY} today\n",
                              "notes/log.txt": f"token={FAKE_KEY}\n"})
        spec = f"folder:{folder}"
        root = self.granted(spec)
        code, out, err = run(root, "knowledge", "fetch", spec)
        self.assertEqual(code, 0, err)
        docs = self.written(root, knowledge.source_name(spec))
        self.assertEqual(len(docs), 2)
        self.assertIn("<masked>", docs["notes/ops.md"])
        self.assertNotIn(FAKE_KEY, self.all_text(Root(root).path))

    def test_privacy_word_refuses_the_whole_source(self):
        folder = self.export({"a.md": "fine\n", "b.md": "the Secretproject launch\n"})
        spec = f"folder:{folder}"
        root = self.granted(spec, words=["secretproject"])
        code, out, err = run(root, "knowledge", "fetch", spec)
        self.assertEqual(code, 1)
        self.assertIn("privacy word", err)
        self.assertIn("b.md", err)
        self.assertEqual(self.written(root, knowledge.source_name(spec)), {})
        entry = Root(root).state()["knowledge"][knowledge.source_name(spec)]
        self.assertEqual(entry["status"], "refused")


class UnreachableTests(KnowledgeCase):
    def test_unreachable_source_reported(self):
        def broken_gh(args, stdin=None):
            raise CrucibleError("gh issue list failed: HTTP 404")

        self.addCleanup(setattr, knowledge, "run_gh", knowledge.run_gh)
        knowledge.run_gh = broken_gh
        spec = "github:acme/gone"
        root = self.granted(spec)
        code, out, err = run(root, "knowledge", "fetch", spec)
        self.assertEqual(code, 1)
        self.assertIn("unreachable", err)
        self.assertIn("export", err)
        name = knowledge.source_name(spec)
        entry = Root(root).state()["knowledge"][name]
        self.assertEqual(entry["status"], "unreachable")
        self.assertIn("HTTP 404", entry["reason"])
        self.assertEqual(self.action_rows(root)[-1]["status"], "failed")
        code, out, err = run(root, "report")
        self.assertEqual(code, 0, err)
        self.assertIn("knowledge sources not absorbed: 1", out)
        self.assertIn(name, out)
        self.assertIn("HTTP 404", out)

    def test_unreachable_kinds_never_touch_the_network(self):
        for spec in ("url:http://plain.invalid/page",
                     "folder:" + os.path.join(self.tmp(), "missing")):
            root = self.granted(spec)
            code, out, err = run(root, "knowledge", "fetch", spec)
            self.assertEqual(code, 1, spec)
            self.assertEqual(Root(root).state()["knowledge"][knowledge.source_name(spec)]["status"],
                             "unreachable", spec)

    def fake_clone(self, calls):
        def run_git(argv, **kwargs):
            calls.append(argv)
            dest = argv[-1]
            os.makedirs(os.path.join(dest, ".git"))
            with open(os.path.join(dest, ".git", "notes.txt"), "w", encoding="utf-8") as fh:
                fh.write("internal\n")
            with open(os.path.join(dest, "guide.md"), "w", encoding="utf-8") as fh:
                fh.write("# guide\nrun it\n")
            return mock.Mock(returncode=0, stdout="", stderr="")
        return run_git

    def test_knowledge_git_source_needs_grant(self):
        spec = "git:https://host.invalid/a/b.git"
        root = self.granted(spec)
        calls = []
        with mock.patch.object(clones.subprocess, "run", side_effect=self.fake_clone(calls)):
            code, out, err = run(root, "knowledge", "fetch", spec)
        self.assertEqual(code, 1)
        self.assertIn("refused: knowledge_clone", err)
        self.assertEqual(calls, [])
        self.assertEqual(self.written(root, knowledge.source_name(spec)), {})
        self.assertEqual(self.action_rows(root)[-1]["status"], "refused")

    def test_knowledge_git_source_is_cloned_under_its_grant(self):
        spec = "git:https://host.invalid/a/b.git"
        root = self.granted(spec)
        self.assertEqual(run(root, "grant", "knowledge_clone", "yes", "--reopen", "--words", "yes",
                             "--bound", "sources=" + spec)[0], 0)
        calls = []
        with mock.patch.object(clones.subprocess, "run", side_effect=self.fake_clone(calls)):
            code, out, err = run(root, "knowledge", "fetch", spec)
        self.assertEqual(code, 0, err)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][:2], ["git", "clone"])
        self.assertEqual(self.written(root, knowledge.source_name(spec)), {"guide.md": "# guide\nrun it\n"})
        self.assertEqual(self.action_rows(root)[-1]["group"], "knowledge_sources")
        self.assertIn("knowledge_clone", [r["group"] for r in self.action_rows(root)])

    def test_unknown_source_is_refused(self):
        root = self.granted()
        code, out, err = run(root, "knowledge", "fetch", "nothing")
        self.assertEqual(code, 1)
        self.assertIn("not a known source", err)


class ListTests(KnowledgeCase):
    def test_list_shows_configured_and_fetched_sources(self):
        folder = self.export({"a.md": "x\n"})
        root, repo = self.make_root(FILES, config={"knowledge_sources": [
            {"name": "wiki", "kind": "folder", "target": folder}, {"name": "site", "kind": "url", "target": "x"}]})
        self.assertEqual(run(root, "grant", "knowledge_sources", "yes", "--reopen", "--words", "yes",
                             "--bound", "sources=wiki")[0], 0)
        self.assertEqual(run(root, "knowledge", "fetch", "wiki")[0], 0)
        code, out, err = run(root, "knowledge", "list")
        self.assertEqual(code, 0, err)
        self.assertIn("wiki: absorbed, 1 documents", out)
        self.assertIn("site: not fetched", out)
