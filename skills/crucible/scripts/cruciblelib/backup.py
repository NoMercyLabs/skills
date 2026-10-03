import os
import re
import shutil
import time

from .common import CrucibleError
from .permissions import log_action


def backup(root, label, source):
    """Copy a file, a folder or a piece of text before a change that can lose data; returns the copy's path.

    Returns None when the user turned backups off. A failed copy raises: the caller stops.
    """
    settings = root.config().get("backups") or {"enabled": True, "path": None}
    if not settings.get("enabled", True):
        log_action(root, "backups", f"backup {label}", "backups are off", "skipped")
        return None
    base = settings.get("path") or root.p("backups")
    safe = re.sub(r"[^A-Za-z0-9._-]", "-", label) or "backup"
    stem = os.path.join(base, f"{time.strftime('%Y%m%dT%H%M%S')}-{safe}")
    target, n = stem, 1
    while os.path.exists(target):
        n += 1
        target = f"{stem}-{n}"
    try:
        os.makedirs(base, exist_ok=True)
        if os.path.isdir(source):
            shutil.copytree(source, target)
        elif os.path.isfile(source):
            shutil.copy2(source, target)
        else:
            with open(target, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(str(source))
    except OSError as exc:
        log_action(root, "backups", f"backup {label}", f"failed: {exc}", "failed")
        raise CrucibleError(f"backup of {label} failed ({exc}); the change is not made")
    log_action(root, "backups", f"backup {label}", target, "ok")
    return target
