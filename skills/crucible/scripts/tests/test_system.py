import json
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from unittest import mock

from .helpers import CrucibleCase, good_finding, run


def git(path, *args):
    done = subprocess.run(["git", "-C", path, "-c", "user.name=t", "-c", "user.email=t@t.test",
                           "-c", "commit.gpgsign=false", *args], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


def unlock(func, path, _info):
    os.chmod(path, stat.S_IWRITE)
    func(path)


class SystemCase(CrucibleCase):
    def tmp(self):
        path = tempfile.mkdtemp(prefix="crucible-test-")
        self.addCleanup(shutil.rmtree, path, False, unlock)
        return path

    def git_repo(self, files, name="svc", remote=None, folder=None):
        repo = os.path.join(folder or self.tmp(), name)
        for rel, content in files.items():
            full = os.path.join(repo, *rel.split("/"))
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(content)
        os.makedirs(repo, exist_ok=True)
        git(repo, "init", "-q")
        git(repo, "symbolic-ref", "HEAD", "refs/heads/main")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "first")
        if remote:
            git(repo, "remote", "add", "origin", remote)
        return repo

    def init_root(self, *repos):
        root = os.path.join(self.tmp(), "audit")
        args = []
        for repo in repos:
            args += ["--repo", repo]
        code, out, err = run(root, "init", *args)
        self.assertEqual(code, 0, err)
        return root

    def confirmed_root(self, *repos):
        root = self.init_root(*repos)
        self.assertEqual(run(root, "memory", "none", "--words", "test default")[0], 0)
        self.answer_everything(root)
        code, out, err = run(root, "confirm")
        self.assertEqual(code, 0, err)
        return root

    def config(self, root):
        return json.loads(self.read_text(os.path.join(root, "config.json")))


class LayoutTests(SystemCase):
    def test_layout_detects_single_mono_multi(self):
        single = self.git_repo({"app.py": "x = 1\n"})
        code, out, err = run(self.tmp(), "layout", single)
        self.assertEqual(code, 0, err)
        self.assertIn("layout: single", out)
        self.assertIn("base folder", out)

        mono = self.git_repo({"package.json": '{"name": "m", "workspaces": ["packages/*"]}\n',
                              "packages/a/package.json": '{"name": "a"}\n',
                              "packages/b/package.json": '{"name": "b"}\n'}, name="mono")
        code, out, err = run(self.tmp(), "layout", mono)
        self.assertIn("layout: monorepo", out)
        self.assertIn("packages: packages/a, packages/b", out)

        two_manifests = self.git_repo({"web/package.json": "{}\n", "api/go.mod": "module x\n"}, name="pair")
        self.assertIn("layout: monorepo", run(self.tmp(), "layout", two_manifests)[1])

        org = self.tmp()
        self.git_repo({"a.py": "1\n"}, name="orders", folder=org)
        self.git_repo({"b.py": "2\n"}, name="billing", folder=org)
        os.makedirs(os.path.join(org, "notes"))
        code, out, err = run(self.tmp(), "layout", org)
        self.assertIn("layout: multi-repo", out)
        self.assertIn("repos: billing, orders", out)
        self.assertNotIn("notes", out)

        code, out, err = run(self.tmp(), "layout", os.path.join(org, "notes"))
        self.assertEqual(code, 1)
        self.assertIn("no git repo", err)


RELATED_FILES = {
    ".gitmodules": '[submodule "lib"]\n\tpath = lib\n\turl = https://github.com/acme/shared-lib.git\n',
    "package.json": '{\n "name": "@acme/web",\n "dependencies": {\n  "@acme/ui-kit": "^1.0.0",\n'
                    '  "left-pad": "1.3.0"\n }\n}\n',
    "src/client.js": "// api client\nconst API_BASE_URL = \"https://orders-api.acme.test/v1\";\nconst home = 1;\n",
    "openapi.yaml": "openapi: 3.0.0\nservers:\n  - url: https://billing.acme.test/api\n",
    "proto/orders.proto": "syntax = \"proto3\";\nmessage Order {}\n",
    "docker-compose.yml": "services:\n  web:\n    build: ../billing\n  mail:\n    image: ghcr.io/acme/mailer:1.2\n"
                          "  db:\n    image: postgres:16\n",
    ".github/workflows/deploy.yml": "jobs:\n  d:\n    steps:\n      - uses: actions/checkout@v4\n"
                                    "        with:\n          repository: acme/infra\n",
}


class RelatedTests(SystemCase):
    def related(self, *extra):
        repo = self.git_repo(RELATED_FILES, name="web", remote="https://github.com/acme/web.git")
        root = self.init_root(repo)
        code, out, err = run(root, "related", *extra)
        self.assertEqual(code, 0, err)
        rows = json.loads(self.read_text(os.path.join(root, "related.json")))["candidates"]
        return repo, out, rows

    def test_related_repos_found_with_evidence(self):
        with mock.patch("cruciblelib.trackers.github.owner_repos", side_effect=AssertionError("gh ran unasked")):
            repo, out, rows = self.related()
        found = {(r["kind"], r["target"]) for r in rows}
        for want in (("submodule", "shared-lib"), ("dependency", "@acme/ui-kit"), ("api_url", "orders-api.acme.test"),
                     ("openapi", "billing.acme.test"), ("shared_schema", "orders.proto"), ("compose", "billing"),
                     ("compose", "mailer"), ("ci_deploy", "infra")):
            self.assertIn(want, found)
        self.assertNotIn(("dependency", "left-pad"), found)
        self.assertNotIn("postgres", {r["target"] for r in rows})
        for row in rows:
            path, _, line = row["ref"].rpartition(":")
            self.assertTrue(line.isdigit(), row)
            lines = self.read_text(os.path.join(repo, *path.split("/"))).split("\n")
            self.assertIn(row["quote"], lines[int(line) - 1].strip(), row)
        self.assertIn("src/client.js:2", out)

    def test_related_same_owner_repos_come_from_read_only_gh_when_asked(self):
        listed = [{"name": "web", "visibility": "private", "branch": "main", "size_kb": 10},
                  {"name": "ops-tools", "visibility": "private", "branch": "dev", "size_kb": 2048}]
        with mock.patch("cruciblelib.trackers.github.owner_repos", return_value=listed) as called:
            repo, out, rows = self.related("--same-owner")
        called.assert_called_once_with("acme")
        owners = [r for r in rows if r["kind"] == "same_owner"]
        self.assertEqual([r["target"] for r in owners], ["ops-tools"])
        self.assertEqual(owners[0]["ref"].split(":")[0], ".git/config")
        self.assertIn("acme/web", owners[0]["quote"] + owners[0]["detail"] + out)
        self.assertEqual(owners[0]["info"]["branch"], "dev")

    def test_related_says_when_gh_cannot_list_the_owner(self):
        from cruciblelib.common import CrucibleError
        with mock.patch("cruciblelib.trackers.github.owner_repos", side_effect=CrucibleError("gh offline")):
            repo, out, rows = self.related("--same-owner")
        self.assertIn("same-owner repos: not checked (gh offline)", out)


class WorkspaceTests(SystemCase):
    maxDiff = None
    def user_repo(self):
        repo = self.git_repo({"app.py": "x = 1\n", "lib/util.py": "y = 2\n"})
        with open(os.path.join(repo, "app.py"), "w", encoding="utf-8", newline="\n") as fh:
            fh.write("x = 2  # uncommitted\n")
        with open(os.path.join(repo, "scratch.txt"), "w", encoding="utf-8", newline="\n") as fh:
            fh.write("untracked\n")
        return repo

    def snapshot(self, repo):
        out = {"status": git(repo, "--no-optional-locks", "status", "--porcelain"), "branch": git(repo, "rev-parse", "--abbrev-ref", "HEAD"),
               "files": {}, "links": {}}
        for folder, dirs, names in os.walk(repo):
            for name in names:
                full = os.path.join(folder, name)
                st = os.stat(full)
                out["files"][full] = (st.st_mtime_ns, st.st_size, stat.S_IMODE(st.st_mode))
                out["links"][full] = st.st_nlink
        return out

    def choose_base(self, root, base):
        code, out, err = run(root, "workspace", "choose", "base_folder", "--base", base, "--words", "yes a new folder")
        self.assertEqual(code, 0, err)
        return out

    def test_workspace_clone_needs_grant(self):
        repo = self.user_repo()
        root = self.init_root(repo)
        base = os.path.join(self.tmp(), "base")
        self.choose_base(root, base)
        code, out, err = run(root, "workspace", "clone", "--base", base)
        self.assertEqual(code, 1)
        self.assertIn("refused: workspace_clones", err)
        self.assertFalse(os.path.exists(base))
        self.assertEqual(run(root, "grant", "workspace_clones", "no", "--words", "not now")[0], 0)
        self.assertEqual(run(root, "workspace", "clone", "--base", base)[0], 1)
        self.assertFalse(os.path.exists(base))
        self.assertEqual(run(root, "grant", "workspace_clones", "yes", "--bound", "repos=other",
                             "--words", "only other", "--reopen")[0], 0)
        code, out, err = run(root, "workspace", "clone", "--base", base)
        self.assertEqual(code, 1)
        self.assertIn("not granted", err)
        self.assertFalse(os.path.exists(base))
        self.assertEqual(run(root, "grant", "workspace_clones", "yes", "--bound", "repos=svc",
                             "--words", "clone svc", "--reopen")[0], 0)
        code, out, err = run(root, "workspace", "clone", "--base", base)
        self.assertEqual(code, 0, err)
        clone = os.path.join(base, "svc")
        self.assertTrue(os.path.isfile(os.path.join(clone, "app.py")))
        self.assertIn("branch main", out)
        cfg = self.config(root)
        self.assertEqual(os.path.normpath(cfg["repos"][0]["path"]), os.path.normpath(clone))
        self.assertFalse(cfg["confirmed"])
        log = self.read_text(os.path.join(root, "actions.log"))
        self.assertIn("workspace_clones", log)

    def test_workspace_clone_refuses_a_base_that_is_not_fresh_or_not_outside(self):
        repo = self.user_repo()
        root = self.init_root(repo)
        run(root, "grant", "workspace_clones", "yes", "--bound", "repos=svc", "--words", "ok")
        inside = os.path.join(repo, "audit-base")
        self.assertEqual(run(root, "workspace", "choose", "base_folder", "--base", inside, "--words", "x")[0], 1)
        full = self.tmp()
        with open(os.path.join(full, "keep.txt"), "w", encoding="utf-8", newline="\n") as fh:
            fh.write("mine\n")
        code, out, err = run(root, "workspace", "choose", "base_folder", "--base", full, "--words", "x")
        self.assertEqual(code, 1)
        self.assertIn("not empty", err)
        self.assertEqual(run(root, "workspace", "choose", "base_folder", "--words", "x")[0], 1)

    def test_workspace_never_touches_user_checkouts(self):
        repo = self.user_repo()
        before = self.snapshot(repo)
        root = self.init_root(repo)
        base = os.path.join(self.tmp(), "base")
        self.choose_base(root, base)
        self.assertEqual(run(root, "grant", "workspace_clones", "yes", "--bound", "repos=svc", "--words", "ok")[0], 0)
        code, out, err = run(root, "workspace", "clone", "--base", base)
        self.assertEqual(code, 0, err)
        self.assertEqual(self.snapshot(repo), before)
        self.assertEqual(set(before["links"].values()), {1})
        clone = os.path.join(base, "svc")
        committed = self.read_text(os.path.join(clone, "app.py"))
        self.assertEqual(committed, "x = 1\n")
        self.assertFalse(os.path.exists(os.path.join(clone, "scratch.txt")))
        with self.assertRaises(PermissionError):
            with open(os.path.join(clone, "app.py"), "a", encoding="utf-8") as fh:
                fh.write("changed\n")
        self.assertEqual(self.read_text(os.path.join(repo, "app.py")), "x = 2  # uncommitted\n")
        state = json.loads(self.read_text(os.path.join(root, "workspace.json")))
        self.assertEqual(state["repos"][0]["commit"], git(repo, "rev-parse", "HEAD"))

    def test_workspace_plan_shows_branch_and_size_and_offers_base_for_a_single_repo(self):
        repo = self.user_repo()
        root = self.init_root(repo)
        base = os.path.join(self.tmp(), "base")
        code, out, err = run(root, "workspace", "plan", "--base", base)
        self.assertEqual(code, 0, err)
        self.assertIn("svc: branch main", out)
        self.assertRegex(out, r"disk [0-9.]+ (B|KB|MB)")
        self.assertIn("never touched", out)
        self.assertIn("grant workspace_clones", out)
        self.assertFalse(os.path.exists(base))

    def test_workspace_existing_checkouts_are_added_read_only(self):
        first = self.git_repo({"a.py": "1\n"}, name="orders")
        second = self.user_repo()
        root = self.init_root(first)
        code, out, err = run(root, "workspace", "choose", "existing", "--repo", second, "--words", "use my folders")
        self.assertEqual(code, 0, err)
        self.assertIn("read-only", out)
        self.assertEqual([r["name"] for r in self.config(root)["repos"]], ["orders", "svc"])
        self.assertEqual(self.config(root)["workspace"]["mode"], "existing_checkouts")

    def test_single_repo_mode_states_lost_depth(self):
        repo = self.git_repo({"a.py": "1\n"})
        root = self.init_root(repo)
        code, out, err = run(root, "workspace", "choose", "this_repo")
        self.assertEqual(code, 1)
        self.assertIn("--words", err)
        code, out, err = run(root, "workspace", "choose", "this_repo", "--words", "just this repo")
        self.assertEqual(code, 0, err)
        for lost in ("the other side of each contract", "consumers in other repos", "fixes that need both sides"):
            self.assertIn(lost, out)
        code, out, err = run(root, "summary")
        self.assertIn("workspace: this repo only", out)
        self.assertIn("the other side of each contract", out)

    def test_workspace_is_a_policy_answer_that_confirm_needs(self):
        repo = self.git_repo({"a.py": "1\n"})
        root = self.init_root(repo)
        self.assertEqual(run(root, "answer", "workspace", '{"mode": "this_repo"}')[0], 1)
        self.assertEqual(run(root, "answer", "workspace", '{"mode": "elsewhere"}', "--words", "x")[0], 1)
        self.assertEqual(run(root, "answer", "workspace", '{"mode": "this_repo"}', "--words", "only this")[0], 0)
        self.assertEqual(self.config(root)["answers"]["workspace"]["words"], "only this")


GRAPH_FILES = {
    "web": {"package.json": '{\n "name": "@acme/web",\n "dependencies": {"@acme/api-client": "^2.0.0"}\n}\n',
            "src/main.js": "// talks to billing someday\nconst API_BASE_URL = \"https://orders-api.acme.test/v1\";\n",
            ".github/workflows/deploy.yml": "steps:\n  - with:\n      repository: acme/infra\n"},
    "api-client": {"package.json": '{"name": "@acme/api-client", "version": "2.0.0"}\n', "index.js": "export {}\n"},
    "orders-api": {"server.py": "app = 1\n"},
    "infra": {"deploy.sh": "echo deploy\n"},
    "billing": {"billing.py": "pay = 1\n"},
}


class CloneAdapterTests(SystemCase):
    def test_clone_refuses_without_grant(self):
        from cruciblelib import clones
        from cruciblelib.common import Root, CrucibleError
        source = self.git_repo({"app.py": "x = 1\n"})
        root = self.init_root(source)
        dest = os.path.join(self.tmp(), "base", "svc")
        rows = [{"name": "svc", "source": source, "dest": dest}]
        seen = []
        with mock.patch.object(clones.subprocess, "run", side_effect=AssertionError("git ran")) as spy:
            with self.assertRaises(CrucibleError) as ctx:
                clones.clone_repos(Root(root), rows, os.path.dirname(dest), seen.append)
        self.assertIn("workspace_clones", str(ctx.exception))
        spy.assert_not_called()
        self.assertEqual(seen, [])
        self.assertFalse(os.path.exists(os.path.dirname(dest)))


class GraphTests(SystemCase):
    def system(self):
        org = self.tmp()
        repos = {name: self.git_repo(files, name=name, folder=org) for name, files in GRAPH_FILES.items()}
        root = self.confirmed_root(*repos.values())
        return root, repos

    def test_graph_edges_have_evidence(self):
        root, repos = self.system()
        code, out, err = run(root, "graph")
        self.assertEqual(code, 0, err)
        graph = json.loads(self.read_text(os.path.join(root, "graph.json")))
        edges = {(e["from"], e["to"], e["kind"]) for e in graph["edges"]}
        self.assertEqual(edges, {("web", "api-client", "dependency"), ("web", "orders-api", "api_url"),
                                 ("web", "infra", "ci_deploy")})
        for edge in graph["edges"]:
            self.assertTrue(edge["evidence"], edge)
            for ev in edge["evidence"]:
                path, _, line = ev["ref"].rpartition(":")
                text = self.read_text(os.path.join(repos[ev["repo"]], *path.split("/"))).split("\n")[int(line) - 1]
                self.assertIn(ev["quote"], text.strip())
        self.assertIn("web -> api-client dependency package.json:3", out)
        self.assertNotIn("billing", " ".join(e["to"] for e in graph["edges"]))

    def test_graph_gives_readers_the_cross_repo_leads_of_their_unit(self):
        root, repos = self.system()
        self.assertEqual(run(root, "graph")[0], 0)
        self.assertEqual(run(root, "inventory")[0], 0)
        web = json.loads(self.read_text(os.path.join(root, "units", "web-u01.json")))
        self.assertEqual({lead["other_repo"] for lead in web["cross_repo"]}, {"api-client", "orders-api", "infra"})
        self.assertTrue(all(lead["direction"] == "uses" for lead in web["cross_repo"]))
        client = json.loads(self.read_text(os.path.join(root, "units", "api-client-u01.json")))
        self.assertEqual([(lead["other_repo"], lead["direction"]) for lead in client["cross_repo"]],
                         [("web", "used_by")])
        self.assertNotIn("cross_repo", json.loads(self.read_text(os.path.join(root, "units", "billing-u01.json"))))
        self.assertEqual(run(root, "graph")[0], 0)
        again = json.loads(self.read_text(os.path.join(root, "units", "web-u01.json")))
        self.assertEqual(len(again["cross_repo"]), 3)

    def cross_finding(self, root, evidence):
        finding = good_finding(repo="web", cross_repo=["api-client"], evidence=evidence)
        finding["where"] = [{"kind": "file", "ref": "package.json:3"}]
        path = os.path.join(self.tmp(), "F.json")
        self.write(os.path.dirname(path), "F.json", finding)
        return run(root, "gate", path)

    def test_cross_repo_finding_cites_both_sides(self):
        root, repos = self.system()
        run(root, "inventory")
        this_side = {"kind": "file_line", "ref": "package.json:3",
                     "quote": '"dependencies": {"@acme/api-client": "^2.0.0"}'}
        code, out, err = self.cross_finding(root, [this_side])
        self.assertEqual(code, 1, out)
        self.assertIn("cross_repo: no evidence from api-client", out)
        other_side = {"kind": "file_line", "ref": "package.json:1", "repo": "api-client",
                      "quote": '{"name": "@acme/api-client", "version": "2.0.0"}'}
        code, out, err = self.cross_finding(root, [this_side, other_side])
        self.assertEqual(code, 0, out)
        bad = dict(other_side, quote="this is not in that file")
        code, out, err = self.cross_finding(root, [this_side, bad])
        self.assertEqual(code, 1)
        self.assertIn("the quote is not at package.json:1", out)
        self.assertIn("cross_repo: no evidence from api-client", out)

    def test_cross_repo_finding_names_known_repos_and_declares_every_repo_it_cites(self):
        root, repos = self.system()
        run(root, "inventory")
        this_side = {"kind": "file_line", "ref": "package.json:3",
                     "quote": '"dependencies": {"@acme/api-client": "^2.0.0"}'}
        finding = good_finding(repo="web", cross_repo=["nowhere"], evidence=[this_side])
        path = os.path.join(self.tmp(), "F.json")
        self.write(os.path.dirname(path), "F.json", finding)
        code, out, err = run(root, "gate", path)
        self.assertIn("cross_repo: nowhere is not a repo of this audit", out)
        other_side = {"kind": "file_line", "ref": "package.json:1", "repo": "api-client",
                      "quote": '{"name": "@acme/api-client", "version": "2.0.0"}'}
        finding = good_finding(repo="web", evidence=[this_side, other_side])
        self.write(os.path.dirname(path), "F.json", finding)
        code, out, err = run(root, "gate", path)
        self.assertEqual(code, 1)
        self.assertIn("cross_repo: evidence cites api-client but it is not listed", out)

    def test_ledger_counts_per_repo_and_total(self):
        root, repos = self.system()
        run(root, "inventory")
        code, out, err = run(root, "status")
        self.assertIn("coverage: 0 of 5 units done", out)
        for name in GRAPH_FILES:
            self.assertIn(f"coverage {name}: 0 of 1 units done", out)
        code, out, err = run(root, "report")
        self.assertIn("coverage billing: 0 of 1 units done", out)

    def test_single_repo_status_has_no_per_repo_lines(self):
        root = self.make_inventoried({"app.py": "x = 1\n"})
        self.assertNotIn("coverage svc", run(root, "status")[1])


if __name__ == "__main__":
    unittest.main()
