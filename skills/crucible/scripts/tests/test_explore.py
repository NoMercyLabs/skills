import os
import subprocess

from tests.helpers import CrucibleCase, run

SERVICE_V1 = (
    "import os\n"
    "\n"
    "def load_limit():\n"
    "    return int(os.environ.get(\"MAX_ITEMS\", \"5\"))\n"
    "\n"
    "def handler(request):\n"
    "    limit = load_limit()\n"
    "    return request.items[:limit]\n"
)
SERVICE_V2 = SERVICE_V1.replace('"5"', '"10"')


def git(path, *args):
    subprocess.run(["git", "-C", path, "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
                   check=True, capture_output=True, text=True)


class ExploreCase(CrucibleCase):
    def explore_root(self):
        repo = self.make_repo({
            "service.py": SERVICE_V1,
            "worker.py": "from service import load_limit\nn = load_limit()\n",
            "other.py": "import os\n\ndef retries():\n    return int(os.environ.get(\"RETRIES\", \"3\"))\n",
            "deploy.sh": "#!/bin/sh\nexport MAX_ITEMS=20\n",
            ".env": "MAX_ITEMS=99\nTOKEN=hunter2hunter2\n",
        })
        git(repo, "init", "-q")
        git(repo, "add", "-f", "--", "service.py", "worker.py", "other.py", "deploy.sh", ".env")
        git(repo, "commit", "-q", "-m", "feat: add limit")
        with open(os.path.join(repo, "service.py"), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(SERVICE_V2)
        git(repo, "commit", "-q", "-am", "fix: raise the default limit")
        root = os.path.join(self.tmp(), "audit")
        self.assertEqual(run(root, "init", "--repo", repo)[0], 0)
        return root

    def test_explore_lists_callers_history_config(self):
        root = self.explore_root()
        code, out, err = run(root, "explore", "service.py:4")
        self.assertEqual(code, 0, err)
        self.assertIn("symbol: load_limit (service.py:3)", out)
        self.assertIn("service.py:7:", out)
        self.assertIn("worker.py:2:", out)
        self.assertIn("callees:", out)
        self.assertIn("env MAX_ITEMS", out)
        self.assertIn("deploy.sh:2:", out)
        self.assertIn("history:", out)
        self.assertIn("feat: add limit", out)
        self.assertIn("earlier fix or revert on these lines:", out)
        fixes = out.split("earlier fix or revert on these lines:")[1].split("siblings:")[0]
        self.assertIn("fix: raise the default limit", fixes)
        self.assertNotIn("feat: add limit", fixes)
        self.assertIn("siblings:", out)
        self.assertIn("other.py:4:", out)

    def test_explore_never_reads_or_shows_secret_files(self):
        root = self.explore_root()
        out = run(root, "explore", "service.py:4")[1]
        self.assertNotIn(".env:", out)
        self.assertNotIn("hunter2", out)
        code, out, err = run(root, "explore", ".env:1")
        self.assertEqual(code, 1)
        self.assertIn("secret file", err)

    def test_explore_names_what_it_cannot_resolve(self):
        root = self.explore_root()
        code, out, err = run(root, "explore", "service.py:99")
        self.assertEqual(code, 1)
        self.assertIn("line 99", err)
        code, out, err = run(root, "explore", "nowhere.py:1")
        self.assertEqual(code, 1)
        self.assertIn("not in", err)


# (extension, definition file text with the body literal on line BODY_LINE, caller file text) per claimed language.
LANGUAGES = {
    "js": ("function pick(items) {\n  const n = 5;\n  return items.slice(0, n);\n}\n", "const out = pick(list);\n"),
    "ts": ("export function pick(items: string[]): string[] {\n  const n = 5;\n  return items.slice(0, n);\n}\n",
           "const out = pick(list);\n"),
    "tsx": ("export const pick = (items: string[]) => {\n  const n = 5;\n  return items.slice(0, n);\n};\n",
            "const out = pick(list);\n"),
    "cs": ("class Svc\n{\n    public int Pick(int[] items)\n    {\n        var n = 5;\n        return n;\n    }\n}\n",
           "var x = svc.Pick(items);\n"),
    "java": ("class Svc {\n    public int pick(int[] items) {\n        int n = 5;\n        return n;\n    }\n}\n",
             "int x = svc.pick(items);\n"),
    "kt": ("class Svc {\n    fun pick(items: List<Int>): Int {\n        val n = 5\n        return n\n    }\n}\n",
           "val x = svc.pick(items)\n"),
    "php": ("<?php\nclass Svc {\n    public function pick($items) {\n        $n = 5;\n        return $n;\n    }\n}\n",
            "<?php\n$x = $svc->pick($items);\n"),
    "go": ("package main\n\nfunc pick(items []int) int {\n\tn := 5\n\treturn n\n}\n", "package main\n\nvar x = pick(items)\n"),
    "go-method": ("package main\n\nfunc (s *Svc) pick(items []int) int {\n\tn := 5\n\treturn n\n}\n",
                  "package main\n\nvar x = svc.pick(items)\n"),
    "rs": ("fn pick(items: &[i32]) -> i32 {\n    let n = 5;\n    n\n}\n", "fn main() {\n    let x = pick(&items);\n}\n"),
    "rb": ("def pick(items)\n  n = 5\n  n\nend\n", "x = pick(items)\n"),
}


class ExploreLanguageCase(CrucibleCase):
    def language_root(self, ext, source, caller):
        ext = ext.split("-")[0]
        repo = self.make_repo({f"svc.{ext}": source, f"use.{ext}": caller})
        git(repo, "init", "-q")
        git(repo, "add", "--", f"svc.{ext}", f"use.{ext}")
        git(repo, "commit", "-q", "-m", "feat: add pick")
        with open(os.path.join(repo, f"svc.{ext}"), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(source.replace("5", "10"))
        git(repo, "commit", "-q", "-am", "fix: raise the pick limit")
        root = os.path.join(self.tmp(), "audit")
        self.assertEqual(run(root, "init", "--repo", repo)[0], 0)
        return root

    def test_explore_finds_callers_and_history_per_language(self):
        for key, (source, caller) in LANGUAGES.items():
            with self.subTest(language=key):
                ext = key.split("-")[0]
                root = self.language_root(key, source, caller)
                body = next(i for i, text in enumerate(source.splitlines(), 1) if "10" in text.replace("5", "10") and "5" in text)
                code, out, err = run(root, "explore", f"svc.{ext}:{body}")
                self.assertEqual(code, 0, err)
                self.assertIn("symbol: " + ("Pick" if ext == "cs" else "pick") + " (", out)
                self.assertIn(f"use.{ext}:", out)
                callers = out.split("callers:")[1].split("callees:")[0]
                self.assertIn(f"use.{ext}:", callers)
                self.assertIn("feat: add pick", out)
                fixes = out.split("earlier fix or revert on these lines:")[1].split("siblings:")[0]
                self.assertIn("fix: raise the pick limit", fixes)

    def test_explore_says_when_the_extension_has_no_symbol_detection(self):
        repo = self.make_repo({"calc.lua": "function pick(items)\n  return 5\nend\n", "use.lua": "local x = pick(items)\n"})
        root = os.path.join(self.tmp(), "audit")
        self.assertEqual(run(root, "init", "--repo", repo)[0], 0)
        code, out, err = run(root, "explore", "calc.lua:2")
        self.assertEqual(code, 0, err)
        self.assertIn("symbol detection not supported for .lua: callers not listed", out)
        self.assertNotIn("callers: none found by search", out)
