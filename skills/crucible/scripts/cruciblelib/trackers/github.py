"""GitHub adapter: the only module that calls `gh`. Argument lists only; no token is read or passed."""
import json
import re
import subprocess

from ..common import CrucibleError
from .base import Tracker

NEEDED_SCOPES = {"issue": ("repo",), "advisory": ("repo", "security_events"), "board": ("project",)}


def run_gh(args, stdin=None):
    """Run `gh` with an argument list and return stdout; a failure raises with gh's own message."""
    try:
        done = subprocess.run(["gh", *args], input=stdin, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        raise CrucibleError(f"gh could not run: {exc}")
    if done.returncode != 0:
        raise CrucibleError(f"gh {' '.join(args[:2])} failed: {done.stderr.strip() or done.stdout.strip()}")
    return done.stdout


def missing_scopes(status_text, needed):
    """Scopes listed in `gh auth status` output that the token lacks; empty when nothing is known to be missing."""
    match = re.search(r"Token scopes:\s*(.+)", status_text)
    if not match:
        return []
    have = {s.strip(" '\"") for s in match.group(1).split(",")}
    return [s for s in needed if s not in have]


def refresh_hint(scopes):
    """The command the user runs; this skill never runs it."""
    return "gh auth refresh -s " + ",".join(scopes)


class GitHub(Tracker):
    name = "github"

    def visibility(self, slug):
        value = run_gh(["repo", "view", slug, "--json", "visibility", "--jq", ".visibility"]).strip().lower()
        return "public" if value == "public" else "private"

    def board_visibility(self, owner, number):
        data = json.loads(run_gh(["project", "view", str(number), "--owner", owner, "--format", "json"]))
        return "public" if data.get("public") else "private"

    def check_scopes(self, kind):
        try:
            text = run_gh(["auth", "status"])
        except CrucibleError as exc:
            text = str(exc)
        lacking = missing_scopes(text, NEEDED_SCOPES[kind])
        if lacking:
            raise CrucibleError(f"the gh token lacks the scope {', '.join(lacking)}: run `{refresh_hint(lacking)}` "
                                "yourself, then try again")

    def create_label(self, slug, label):
        run_gh(["label", "create", label, "--repo", slug])

    def create(self, action):
        target = action["target"]
        if action["kind"] == "advisory":
            payload = {"summary": action["title"], "description": action["body"], "severity": "medium",
                       "vulnerabilities": []}
            out = run_gh(["api", "-X", "POST", f"repos/{target}/security-advisories", "--input", "-"],
                         stdin=json.dumps(payload))
            return json.loads(out)["ghsa_id"]
        args = ["issue", "create", "--repo", target, "--title", action["title"], "--body", action["body"]]
        for label in action.get("labels") or []:
            args += ["--label", label]
        if action.get("assignee"):
            args += ["--assignee", action["assignee"]]
        return run_gh(args).strip().splitlines()[-1]

    def add_to_board(self, action, ref):
        owner, _, number = action["board"][len("board:"):].partition("/")
        run_gh(["project", "item-add", number, "--owner", owner, "--url", ref])

    def read(self, kind, target, ref):
        if kind == "advisory":
            data = json.loads(run_gh(["api", f"repos/{target}/security-advisories/{ref}"]))
            return {"title": data.get("summary", ""), "body": data.get("description", "")}
        data = json.loads(run_gh(["issue", "view", ref, "--json", "title,body"]))
        return {"title": data.get("title", ""), "body": data.get("body", "")}
