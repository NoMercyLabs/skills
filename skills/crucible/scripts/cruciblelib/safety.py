import os

from .common import Root, is_secret_file
from .config import git


def tracked_secret_files(path):
    """(paths, is_git_repo): the secret files `git ls-files` lists, by path only; no file is opened."""
    if not os.path.exists(os.path.join(path, ".git")):
        return [], False
    listed = git(path, "ls-files", "-z")
    return sorted(p for p in listed.split("\0") if p and is_secret_file(p)), True


def cmd_safety(args):
    cfg = Root(args.root).config()
    total = 0
    for repo in cfg["repos"]:
        found, is_repo = tracked_secret_files(repo["path"])
        if not is_repo:
            print(f"{repo['name']}: not a git repo, tracked files unknown")
            continue
        total += len(found)
        print(f"{repo['name']}: {len(found)} tracked secret files")
        for rel in found:
            print(f"  {rel}")
    print(f"tracked secret files: {total}")
    if total:
        print("Remove them from git and rotate what they held; the audit never reads them.")
    return 1 if total else 0


def register(sub):
    p = sub.add_parser("safety", help="list secret files tracked by git (path only, never the content)")
    p.set_defaults(func=cmd_safety)
