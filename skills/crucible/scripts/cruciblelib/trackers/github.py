"""GitHub adapter: the only module that calls `gh`. Argument lists only; no token is read or passed."""
import json
import re
import subprocess

from ..common import CrucibleError
from .base import Tracker

NEEDED_SCOPES = {"issue": ("repo",), "advisory": ("repo", "security_events"), "board": ("project",)}


VIEW_FIELDS = "id name layout filter"
VIEWS_QUERY = ("query($id:ID!){node(id:$id){... on ProjectV2{views(first:50){nodes{" + VIEW_FIELDS + "}}}}}")
CREATE_VIEW = ("mutation($input:CreateProjectV2ViewInput!){createProjectV2View(input:$input){projectV2View{"
               + VIEW_FIELDS + "}}}")
UPDATE_VIEW = ("mutation($input:UpdateProjectV2ViewInput!){updateProjectV2View(input:$input){projectV2View{"
               + VIEW_FIELDS + "}}}")


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

    def labels(self, slug):
        out = run_gh(["label", "list", "--repo", slug, "--limit", "1000", "--json", "name", "--jq", ".[].name"])
        return {line.strip() for line in out.splitlines() if line.strip()}

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

    def open_pull_request(self, slug, branch, title, body):
        return run_gh(["pr", "create", "--repo", slug, "--head", branch, "--title", title, "--body", body]
                      ).strip().splitlines()[-1]

    def add_to_board(self, action, ref):
        owner, _, number = action["board"][len("board:"):].partition("/")
        run_gh(["project", "item-add", number, "--owner", owner, "--url", ref])

    def project_id(self, owner, number):
        return json.loads(run_gh(["project", "view", str(number), "--owner", owner, "--format", "json"]))["id"]

    def list_fields(self, owner, number):
        out = run_gh(["project", "field-list", str(number), "--owner", owner, "--format", "json", "-L", "100"])
        return json.loads(out)["fields"]

    def create_field(self, owner, number, name, options):
        args = ["project", "field-create", str(number), "--owner", owner, "--name", name, "--format", "json"]
        if options is None:
            return json.loads(run_gh(args + ["--data-type", "DATE"]))
        # the flag is a comma-split list that reads CSV quoting, so a value with a comma is quoted
        quoted = ['"' + o.replace('"', '""') + '"' if "," in o or '"' in o else o for o in options]
        return json.loads(run_gh(args + ["--data-type", "SINGLE_SELECT", "--single-select-options", ",".join(quoted)]))

    def list_items(self, owner, number):
        out = run_gh(["project", "item-list", str(number), "--owner", owner, "--format", "json", "-L", "1000"])
        return json.loads(out)["items"]

    def set_item_field(self, project_id, item_id, field, value):
        args = ["project", "item-edit", "--id", item_id, "--project-id", project_id, "--field-id", field["id"]]
        if "options" not in field:
            run_gh(args + ["--text", value])
            return
        option = next((o for o in field["options"] if o["name"] == value), None)
        if option is None:
            raise CrucibleError(f"the board field {field['name']} has no option {value!r}")
        run_gh(args + ["--single-select-option-id", option["id"]])

    def graphql(self, query, variables):
        """One GraphQL call; the body goes on stdin so nested input objects need no flag quoting."""
        out = json.loads(run_gh(["api", "graphql", "--input", "-"], stdin=json.dumps({"query": query, "variables": variables})))
        if out.get("errors"):
            raise CrucibleError("gh api graphql failed: " + "; ".join(str(e.get("message", e)) for e in out["errors"]))
        return out["data"]

    def list_views(self, project_id):
        data = self.graphql(VIEWS_QUERY, {"id": project_id})
        return data["node"]["views"]["nodes"]

    def create_view(self, project_id, name, layout, field_ids):
        data = self.graphql(CREATE_VIEW, {"input": {"projectId": project_id, "name": name, "layout": layout,
                                                    "configuration": {"visibleFieldIds": field_ids}}})
        return data["createProjectV2View"]["projectV2View"]

    def set_view_filter(self, view_id, filter_text):
        self.graphql(UPDATE_VIEW, {"input": {"viewId": view_id, "filter": filter_text}})

    def read(self, kind, target, ref):
        if kind == "advisory":
            data = json.loads(run_gh(["api", f"repos/{target}/security-advisories/{ref}"]))
            return {"title": data.get("summary", ""), "body": data.get("description", "")}
        data = json.loads(run_gh(["issue", "view", ref, "--json", "title,body"]))
        return {"title": data.get("title", ""), "body": data.get("body", "")}


def owner_repos(owner):
    """Read-only listing of an owner's repositories: name, visibility, default branch, size in KB."""
    data = json.loads(run_gh(["repo", "list", owner, "--limit", "200", "--json", "name,visibility,defaultBranchRef,diskUsage"]))
    return [{"name": r["name"], "visibility": str(r.get("visibility", "")).lower(),
             "branch": (r.get("defaultBranchRef") or {}).get("name"), "size_kb": r.get("diskUsage")} for r in data]
