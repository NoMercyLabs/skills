"""Static scan of the skill's own code: the risky constructs a reviewer looks for are refused.

Each rule has a test that plants a violation in a temp file and feeds it to the scanner, and one
test that the real tree is clean. The scanner is the function `scan_file`.
"""
import ast
import os
import re
import tempfile
import unittest

SKILL = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS = os.path.join(SKILL, "scripts")

NETWORK_MODULES = {"urllib", "urllib2", "urllib3", "socket", "http", "httpx", "requests", "aiohttp", "ssl",
                   "ftplib", "smtplib", "telnetlib", "xmlrpc", "websocket", "websockets"}
BLOB_MODULES = {"base64", "binascii", "marshal", "pickle", "zlib", "codecs"}
# Only these files may reach the network or start a process; each is a documented adapter (SECURITY.md).
NETWORK_ALLOWED = ("cruciblelib/trackers/", "cruciblelib/knowledge")
SUBPROCESS_ALLOWED = ("cruciblelib/config.py", "cruciblelib/safety.py", "cruciblelib/trackers/github.py",
                      "cruciblelib/knowledge", "cruciblelib/clones.py")
CREDENTIAL_PATHS = re.compile(
    r"\.ssh\b|\.aws\b|\.gnupg|\.azure\b|\.kube\b|\.netrc|\.git-credentials|\.pypirc|\.npmrc"
    r"|\.docker[/\\]config|\.config[/\\]gcloud|keychains?\b|login data|bash_history|zsh_history"
    r"|consolehost_history|\.mozilla|user data[/\\]|appdata[/\\]roaming",
    re.IGNORECASE)
URL = re.compile(r"https?://[^\s\"'<>)\]]+")
ALLOWED_URL_PREFIXES = ("github.com/NoMercyLabs/grimoira", "github.com/NoMercyLabs/skills", "cli.github.com/",
                         "docs.github.com/")
BLOB_STRING = re.compile(r"^[A-Za-z0-9+/=_-]{64,}$")


def allowed(rel, prefixes):
    return any(rel == p or rel.startswith(p) for p in prefixes)


def call_name(node):
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        return f"{func.value.id}.{func.attr}"
    return ""


def imported_roots(node):
    if isinstance(node, ast.Import):
        return [a.name.split(".")[0] for a in node.names]
    if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
        return [node.module.split(".")[0]]
    return []


def scan_urls(text):
    return [(m.group(0), text.count("\n", 0, m.start()) + 1) for m in URL.finditer(text)
            if not m.group(0).split("://", 1)[1].startswith(ALLOWED_URL_PREFIXES)]


def scan_file(path, rel=None):
    """-> [(rule, line, detail)] for one file; rel is its posix path under scripts/ (decides what it may import)."""
    rel = rel or os.path.basename(path)
    with open(path, encoding="utf-8") as fh:
        source = fh.read()
    out = [("url", line, url) for url, line in scan_urls(source)]
    for number, text in enumerate(source.split("\n"), 1):
        hit = CREDENTIAL_PATHS.search(text)
        if hit:
            out.append(("credential-path", number, hit.group(0)))
    tree = ast.parse(source)
    for node in ast.walk(tree):
        for root in imported_roots(node):
            if root in NETWORK_MODULES and not allowed(rel, NETWORK_ALLOWED):
                out.append(("network-module", node.lineno, root))
            if root in BLOB_MODULES:
                out.append(("encoded-blob", node.lineno, root))
            if root == "subprocess" and not allowed(rel, SUBPROCESS_ALLOWED):
                out.append(("subprocess-location", node.lineno, root))
            if root == "importlib":
                out.append(("dynamic-import", node.lineno, root))
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and BLOB_STRING.match(node.value):
            out.append(("encoded-blob", node.lineno, node.value[:20] + "..."))
        if not isinstance(node, ast.Call):
            continue
        name = call_name(node)
        if name in ("eval", "exec"):
            out.append(("eval-exec", node.lineno, name))
        if name in ("os.system", "os.popen") or re.match(r"os\.(spawn|exec)\w*$", name):
            out.append(("os-exec", node.lineno, name))
        if name == "__import__":
            out.append(("dynamic-import", node.lineno, name))
        if any(k.arg == "shell" and not (isinstance(k.value, ast.Constant) and k.value.value is False)
               for k in node.keywords):
            out.append(("shell-true", node.lineno, name))
        if name.startswith("subprocess.") and (not node.args or not isinstance(node.args[0], (ast.List, ast.Tuple))):
            out.append(("subprocess-args", node.lineno, name))
    return sorted(out)


def skill_files(extensions):
    """The code and documents the skill ships and runs; the unit tests and the seeded fixtures are not part of it."""
    for folder, dirs, names in os.walk(SKILL):
        dirs[:] = [d for d in dirs if d not in ("fixtures", "tests", "__pycache__", ".git")]
        for name in names:
            full = os.path.join(folder, name)
            if name.endswith(extensions):
                yield full


class PlantedViolations(unittest.TestCase):
    def scan(self, source, rel="cruciblelib/example.py"):
        with tempfile.TemporaryDirectory(prefix="crucible-safety-") as folder:
            path = os.path.join(folder, "planted.py")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(source)
            return scan_file(path, rel)

    def rules(self, source, rel="cruciblelib/example.py"):
        return {rule for rule, _, _ in self.scan(source, rel)}

    def test_clean_code_has_no_findings(self):
        self.assertEqual(self.scan("import os\nprint(os.getcwd())\n"), [])

    def test_eval_and_exec_are_refused(self):
        self.assertEqual(self.rules("x = eval('1')\n"), {"eval-exec"})
        self.assertEqual(self.rules("exec('x = 1')\n"), {"eval-exec"})

    def test_os_system_popen_and_spawn_are_refused(self):
        for call in ("os.system('ls')", "os.popen('ls')", "os.spawnl(0, 'a')", "os.execv('a', [])"):
            self.assertEqual(self.rules("import os\n" + call + "\n"), {"os-exec"}, call)

    def test_shell_true_is_refused(self):
        found = self.rules("import subprocess\nsubprocess.run(['ls'], shell=True)\n", "cruciblelib/config.py")
        self.assertEqual(found, {"shell-true"})

    def test_shell_false_is_fine(self):
        self.assertEqual(self.scan("import subprocess\nsubprocess.run(['ls'], shell=False)\n",
                                   "cruciblelib/config.py"), [])

    def test_dynamic_imports_are_refused(self):
        self.assertEqual(self.rules("m = __import__('os')\n"), {"dynamic-import"})
        self.assertEqual(self.rules("import importlib\nimportlib.import_module('os')\n"), {"dynamic-import"})
        self.assertEqual(self.rules("from importlib import import_module\n"), {"dynamic-import"})

    def test_encoded_blobs_are_refused(self):
        self.assertEqual(self.rules("import base64\nbase64.b64decode('aGk=')\n"), {"encoded-blob"})
        self.assertEqual(self.rules("DATA = '" + "QUJD" * 20 + "'\n"), {"encoded-blob"})
        self.assertEqual(self.rules("import zlib\n"), {"encoded-blob"})

    def test_network_modules_are_refused_outside_the_adapters(self):
        for module in ("urllib.request", "socket", "http.client", "requests"):
            self.assertEqual(self.rules(f"import {module}\n"), {"network-module"}, module)
        self.assertEqual(self.rules("from urllib import request\n"), {"network-module"})

    def test_network_modules_are_allowed_in_the_adapters(self):
        self.assertEqual(self.scan("import urllib.request\n", "cruciblelib/trackers/github.py"), [])
        self.assertEqual(self.scan("import socket\n", "cruciblelib/knowledge.py"), [])

    def test_a_subprocess_outside_the_adapters_is_refused(self):
        self.assertEqual(self.rules("import subprocess\nsubprocess.run(['ls'])\n", "cruciblelib/inventory.py"),
                         {"subprocess-location"})

    def test_git_clone_is_allowed_only_in_the_clones_adapter(self):
        call = "import subprocess\nsubprocess.run(['git', 'clone', 'a', 'b'])\n"
        self.assertEqual(self.scan(call, "cruciblelib/clones.py"), [])
        self.assertEqual(self.rules(call, "cruciblelib/system.py"), {"subprocess-location"})

    def test_a_subprocess_call_needs_an_argument_list(self):
        self.assertEqual(self.rules("import subprocess\nsubprocess.run('ls -l')\n", "cruciblelib/config.py"),
                         {"subprocess-args"})
        self.assertEqual(self.rules("import subprocess\nsubprocess.run(cmd)\n", "cruciblelib/config.py"),
                         {"subprocess-args"})

    def test_credential_folders_are_refused(self):
        for text in ("~/.ssh/id_rsa", "~/.aws/credentials", "~/.gnupg", "Library/Keychains/login.keychain",
                     "AppData/Local/Google/Chrome/User Data/Default/Login Data", "~/.bash_history",
                     "~/.config/gcloud/creds", "~/.netrc", "~/.mozilla/firefox"):
            self.assertEqual(self.rules(f"path = {text!r}\n"), {"credential-path"}, text)

    def test_urls_outside_the_allowlist_are_refused(self):
        self.assertEqual(self.rules("URL = 'https://evil.example/collect'\n"), {"url"})
        self.assertEqual(self.rules("# see http://github.com/someone/else\n"), {"url"})

    def test_allowlisted_urls_pass(self):
        self.assertEqual(self.scan("URL = 'https://github.com/NoMercyLabs/skills'\n"), [])
        self.assertEqual(self.scan("URL = 'https://cli.github.com/manual'\n"), [])

    def test_a_finding_carries_its_line(self):
        found = self.scan("x = 1\ny = eval('2')\n")
        self.assertEqual(found, [("eval-exec", 2, "eval")])


class RealTree(unittest.TestCase):
    def test_the_python_code_is_clean(self):
        problems = []
        for path in skill_files((".py",)):
            rel = os.path.relpath(path, SCRIPTS).replace(os.sep, "/")
            problems += [f"{rel}:{line} {rule} {detail}" for rule, line, detail in scan_file(path, rel)]
        self.assertEqual(problems, [])

    def test_the_documents_name_only_allowed_urls(self):
        problems = []
        for path in skill_files((".md",)):
            with open(path, encoding="utf-8") as fh:
                problems += [f"{os.path.relpath(path, SKILL)}:{line} {url}" for url, line in scan_urls(fh.read())]
        self.assertEqual(problems, [])

    def test_the_scan_covers_the_engine(self):
        names = {os.path.basename(p) for p in skill_files((".py",))}
        self.assertTrue({"common.py", "github.py", "cli.py", "inventory.py"} <= names)


if __name__ == "__main__":
    unittest.main()
