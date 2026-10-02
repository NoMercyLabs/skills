"""The only module that runs `git clone` and `git ls-remote` (an adapter, listed in SECURITY.md).

A clone starts only inside `permissions.run_action` with the `workspace_clones` grant, so no grant
means no folder and no process. `ls_remote_branch` is a read-only query of a remote's default branch; it contacts the remote only with the same grant,
and answers "unknown" without it.
"""
import os
import re
import subprocess

from .common import CrucibleError
from .permissions import authorize, run_action


def ls_remote_branch(root, source):
    """Default branch of a remote source, or "unknown" (also when the workspace_clones grant is missing: no grant, no network)."""
    try:
        authorize(root, "workspace_clones", f"ls-remote {source}")
    except CrucibleError:
        return "unknown"
    try:
        done = subprocess.run(["git", "ls-remote", "--symref", source, "HEAD"], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    match = re.search(r"ref: refs/heads/(\S+)\s+HEAD", done.stdout)
    return match.group(1) if match else "unknown"


def clone_repos(root, rows, base, finish):
    """Clone every row (name, source, dest) behind the workspace_clones grant; finish(row) runs after each clone."""
    def action():
        done = []
        for row in rows:
            if os.path.exists(row["dest"]):
                raise CrucibleError(f"refused: {row['dest']} exists")
        os.makedirs(os.path.dirname(rows[0]["dest"]), exist_ok=True)
        for row in rows:
            out = subprocess.run(["git", "clone", "--quiet", "--no-hardlinks", "--", row["source"], row["dest"]],
                                 capture_output=True, text=True, timeout=1800)
            if out.returncode != 0:
                raise CrucibleError(f"git clone of {row['source']} failed: {out.stderr.strip()}")
            finish(row)
            done.append(row["name"])
        return ", ".join(done)

    # the grant is checked before any folder exists
    return run_action(root, "workspace_clones", f"clone {len(rows)} repos into {base}", action,
                      repos=[r["name"] for r in rows])
