import ast
import os
import unittest

LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cruciblelib")


def git_calls_without_env():
    """Every subprocess call in cruciblelib that runs git without env=repo_env(), as file:line."""
    missing = []
    for folder, _, names in os.walk(LIB):
        for name in names:
            if not name.endswith(".py"):
                continue
            path = os.path.join(folder, name)
            with open(path, encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "run" and node.args and isinstance(node.args[0], ast.List)):
                    continue
                first = node.args[0].elts[:1]
                if not (first and isinstance(first[0], ast.Constant) and first[0].value == "git"):
                    continue
                env = next((k.value for k in node.keywords if k.arg == "env"), None)
                if not (isinstance(env, ast.Call) and getattr(env.func, "id", "") == "repo_env"):
                    missing.append(f"{os.path.relpath(path, LIB)}:{node.lineno}")
    return missing


class GitEnvTests(unittest.TestCase):
    def test_every_git_call_drops_the_callers_repo_location(self):
        self.assertEqual(git_calls_without_env(), [])
