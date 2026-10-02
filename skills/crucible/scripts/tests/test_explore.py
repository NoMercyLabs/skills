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
