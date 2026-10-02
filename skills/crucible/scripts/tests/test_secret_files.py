import os
import subprocess

from cruciblelib.common import CrucibleError, Root, is_secret_file

from .helpers import CrucibleCase, run

SECRET_NAMES = (".env", ".env.local", "server.pem", "tls/private.KEY", "id_rsa", "id_ed25519", "home/id_ecdsa",
                "cert.p12", "cert.pfx", "credentials.json", "config/gcp-credentials.json",
                "client_secret_123.json", "service-account.json", "service_account_prod.json")
PLAIN_NAMES = (".env.example", ".env.sample", ".env.template", ".env.dist", "id_generator.py", "id_utils.py",
               "ids.json", "keyboard.py", "monkey.py", "package.json", "tsconfig.json", "pemfile.py",
               "id_rsa.pub", "environment.py", "credentials_form.py")


def git(path, *args):
    subprocess.run(["git", "-C", path, *args], check=True, capture_output=True)


class SecretFileNames(CrucibleCase):
    def test_secret_names_are_recognised(self):
        for name in SECRET_NAMES:
            self.assertTrue(is_secret_file(name), name)

    def test_plain_names_and_env_templates_are_not_secret(self):
        for name in PLAIN_NAMES:
            self.assertFalse(is_secret_file(name), name)


class SecretFilesAreNeverRead(CrucibleCase):
    FILES = {"app.py": "x = 1\n", "server.pem": "PEM-BODY-1\n", "tls/site.key": "KEY-BODY-2\n",
             "id_rsa": "RSA-BODY-3\n", "cert.p12": "P12-BODY-4\n", "cert.pfx": "PFX-BODY-5\n",
             "credentials.json": '{"k": "JSON-BODY-6"}\n', ".env": "A=ENV-BODY-7\n", ".env.example": "A=\n"}

    def test_inventory_snapshots_no_secret_file(self):
        root = self.make_inventoried(self.FILES)
        snap = os.path.join(root, "snapshot", "svc")
        self.assertEqual(sorted(os.listdir(snap)), [".env.example", "app.py"])

    def test_no_unit_lists_a_secret_file(self):
        root = self.make_inventoried(self.FILES)
        listed = [f for name in Root(root).units() for f in Root(root).unit(name)["files"]]
        self.assertEqual(sorted(listed), [".env.example", "app.py"])

    def test_show_refuses_a_secret_file_even_when_a_unit_lists_it(self):
        root = self.make_inventoried({"app.py": "x = 1\n"})
        unit = Root(root).units()[0]
        planted = os.path.join(root, "snapshot", "svc", "server.pem")
        with open(planted, "w", encoding="utf-8") as fh:
            fh.write("PEM-BODY-1\n")
        data = Root(root).unit(unit)
        data["files"].append("server.pem")
        import json
        with open(os.path.join(root, "units", unit + ".json"), "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        code, out, err = run(root, "show", unit, "server.pem")
        self.assertEqual(code, 1)
        self.assertIn("secret file", err)
        self.assertNotIn("PEM-BODY-1", out + err)

    def test_the_snapshot_reader_refuses_a_secret_path(self):
        root = self.make_inventoried({"app.py": "x = 1\n"})
        with self.assertRaises(CrucibleError):
            Root(root).snapshot_lines("svc", "keys/id_rsa")


class SecretFilesNeverReadByAnyCommand(CrucibleCase):
    def test_secret_files_never_read_by_any_command(self):
        files = {"app.py": "x = 1\n", ".env": "A=ENV-BODY-7\n", "keys/id_rsa": "RSA-BODY-3\n",
                 "tls/site.key": "KEY-BODY-2\n"}
        root = self.make_inventoried(files)
        snap = os.path.join(root, "snapshot", "svc")
        on_disk = [os.path.join(folder, n) for folder, _, names in os.walk(snap) for n in names]
        for path in on_disk:
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            for body in ("ENV-BODY-7", "RSA-BODY-3", "KEY-BODY-2"):
                self.assertNotIn(body, text)
        self.assertEqual([os.path.basename(p) for p in on_disk], ["app.py"])
        for secret in (".env", "keys/id_rsa", "tls/site.key"):
            with self.assertRaises(CrucibleError, msg=secret):
                Root(root).snapshot_lines("svc", secret)
        unit = Root(root).units()[0]
        code, out, err = run(root, "show", unit, ".env")
        self.assertEqual(code, 1)
        self.assertNotIn("ENV-BODY-7", out + err)


class TrackedSecretReport(CrucibleCase):
    def tracked_repo(self, files):
        repo = self.make_repo(files)
        git(repo, "init", "-q")
        git(repo, "add", "-f", "--", *files)
        return repo

    def audit(self, repo):
        root = os.path.join(self.tmp(), "audit")
        self.assertEqual(run(root, "init", "--repo", repo)[0], 0)
        return root

    def test_it_lists_tracked_secret_files_by_path_only(self):
        repo = self.tracked_repo({"app.py": "x = 1\n", ".env": "A=ENV-BODY\n", "keys/server.pem": "PEM-BODY\n",
                                  ".env.example": "A=\n", "id_rsa": "RSA-BODY\n"})
        code, out, err = run(self.audit(repo), "safety")
        self.assertEqual(code, 1, err)
        self.assertIn("tracked secret files: 3", out)
        for path in (".env", "keys/server.pem", "id_rsa"):
            self.assertIn(path, out)
        for text in ("ENV-BODY", "PEM-BODY", "RSA-BODY", ".env.example", "app.py"):
            self.assertNotIn(text, out)

    def test_secret_file_tracked_reported_by_path_never_by_content(self):
        repo = self.tracked_repo({"app.py": "x = 1\n", "config/.env.local": "TOKEN=SECRET-VALUE-XYZ\n"})
        code, out, err = run(self.audit(repo), "safety")
        self.assertEqual(code, 1, err)
        self.assertIn("config/.env.local", out)
        self.assertNotIn("SECRET-VALUE-XYZ", out + err)

    def test_it_reports_clean_when_nothing_secret_is_tracked(self):
        repo = self.tracked_repo({"app.py": "x = 1\n", ".env.example": "A=\n"})
        code, out, err = run(self.audit(repo), "safety")
        self.assertEqual(code, 0, err)
        self.assertIn("tracked secret files: 0", out)

    def test_an_untracked_secret_file_is_not_reported(self):
        repo = self.tracked_repo({"app.py": "x = 1\n"})
        with open(os.path.join(repo, ".env"), "w", encoding="utf-8") as fh:
            fh.write("A=1\n")
        code, out, err = run(self.audit(repo), "safety")
        self.assertEqual(code, 0, err)
        self.assertIn("tracked secret files: 0", out)

    def test_a_folder_that_is_not_a_git_repo_says_so(self):
        repo = self.make_repo({"app.py": "x = 1\n", ".env": "A=1\n"})
        code, out, err = run(self.audit(repo), "safety")
        self.assertEqual(code, 0, err)
        self.assertIn("not a git repo", out)
