import json
import os

from .common import CrucibleError, mask_secrets
from .permissions import refuse, run_action

SHELL_TOOLS = ("Bash", "PowerShell")


def inside(folder, path):
    folder, path = (os.path.normcase(os.path.normpath(p)) for p in (folder, path))
    return path == folder or path.startswith(folder + os.sep)


def exit_status(part):
    """0 for a result that is not an error; the number after 'Exit code' for one that is, else 1."""
    if not part.get("is_error"):
        return 0
    body = part.get("content")
    if isinstance(body, list):
        body = " ".join(x.get("text", "") for x in body if isinstance(x, dict))
    words = str(body or "").split()
    return int(words[2]) if words[:2] == ["Exit", "code"] and words[2:3] and words[2].isdigit() else 1


def read_commands(path, folders):
    """[{"command", "exit"}] for every shell command run inside one of the folders; nothing else is kept."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            rows = fh.read().split("\n")
    except OSError as exc:
        raise CrucibleError(f"cannot read transcript {path}: {exc}")
    commands, results = [], {}
    for raw in rows:
        try:
            row = json.loads(raw)
        except ValueError:
            continue
        message = row.get("message") if isinstance(row, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "tool_use" and part.get("name") in SHELL_TOOLS:
                command = (part.get("input") or {}).get("command")
                cwd = row.get("cwd")
                if isinstance(command, str) and isinstance(cwd, str) and any(inside(f, cwd) for f in folders):
                    commands.append((part.get("id"), command))
            elif part.get("type") == "tool_result":
                results[part.get("tool_use_id")] = exit_status(part)
    return [{"command": mask_secrets(command), "exit": results.get(tool_id)} for tool_id, command in commands]


def scoped_commands(root, transcript, repo_names):
    """Shell commands and exit codes from an agent transcript, only for repos in scope, only with the
    `transcripts` grant. The conversation and the tool output are never returned."""
    paths = {r["name"]: r["path"] for r in root.config()["repos"]}
    unknown = [n for n in repo_names if n not in paths]
    if unknown:
        refuse(root, "transcripts", f"read {transcript}", f"{', '.join(unknown)} not in scope")
    found = run_action(root, "transcripts", f"read shell commands from {os.path.basename(transcript)}",
                       lambda: read_commands(transcript, [paths[n] for n in repo_names]), repos=list(repo_names))
    return found


USAGE_FIELDS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")
SPLIT_NAMES = {"input_tokens": "input", "cache_creation_input_tokens": "cache_write", "cache_read_input_tokens": "cache_read",
               "output_tokens": "output"}


def read_usage(path):
    """{"tokens", "output", "turns", "split"} (split: the sum of each usage field) from the usage fields the harness writes on each assistant message.
    One message is written once per content block, so the rows are folded by message id. Text is never read."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            rows = fh.read().split("\n")
    except OSError as exc:
        raise CrucibleError(f"cannot read transcript {path}: {exc}")
    messages = {}
    for index, raw in enumerate(rows):
        try:
            row = json.loads(raw)
        except ValueError:
            continue
        message = row.get("message") if isinstance(row, dict) else None
        usage = message.get("usage") if isinstance(message, dict) else None
        if not isinstance(usage, dict):
            continue
        seen = messages.setdefault(message.get("id") or f"row{index}", {})
        for field in USAGE_FIELDS:
            value = usage.get(field)
            if isinstance(value, int) and not isinstance(value, bool):
                seen[field] = max(seen.get(field, 0), value)
    if not messages:
        raise CrucibleError(f"no usage fields in {path}: the harness transcript of the agent is needed")
    return {"tokens": sum(sum(m.values()) for m in messages.values()),
            "output": sum(m.get("output_tokens", 0) for m in messages.values()), "turns": len(messages),
            "split": {name: sum(m.get(field, 0) for m in messages.values()) for field, name in SPLIT_NAMES.items()}}
