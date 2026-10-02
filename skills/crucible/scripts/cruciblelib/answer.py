import json

from .common import CrucibleError, Root
from .permissions import GROUPS, now

PREFIX = "permissions."
CONFIG_KEYS = ("scope", "goals", "stages", "tracker", "auto_file", "advisories", "owners", "privacy_words",
               "budget", "models", "live_checks", "blocker_fixes", "backups", "memory", "knowledge_sources")
# auto_file comes right after the tracker: the user is asked where filings go, then whether to file there unasked.
# A group shares its name with a config key (live_checks, blocker_fixes, knowledge_sources), so groups carry a prefix.
INTERVIEW_ORDER = CONFIG_KEYS + tuple(PREFIX + group for group in GROUPS)

CHOICES = {
    "blocker_fixes.mode": ("each", "within_limits", "never"),
    "blocker_fixes.landing": ("pr", "local_branch", "push_branch"),
    "memory.kind": ("grimoira", "none"),
}


def is_answered(cfg, key):
    if key.startswith(PREFIX):
        return key[len(PREFIX):] in cfg.get("permissions", {})
    if key == "memory":
        return bool(cfg.get("memory"))
    if key == "auto_file":
        return cfg.get("auto_file") is not None
    if key == "blocker_fixes":
        return bool((cfg.get("blocker_fixes") or {}).get("mode"))
    return key in cfg.get("answers", {})


def unanswered(cfg):
    return [key for key in INTERVIEW_ORDER if not is_answered(cfg, key)]


def missing_for_confirm(cfg):
    required = ("auto_file", "blocker_fixes") + INTERVIEW_ORDER[len(CONFIG_KEYS):]
    return [key for key in required if not is_answered(cfg, key)]


def parse_value(text):
    try:
        return json.loads(text)
    except ValueError:
        return text


def check_value(key, value):
    if key == "auto_file" and not isinstance(value, bool):
        raise CrucibleError("auto_file is true or false")
    if key in CHOICES and value not in CHOICES[key]:
        raise CrucibleError(f"{key} is one of: {', '.join(CHOICES[key])}")
    if key in ("blocker_fixes", "memory") and isinstance(value, dict):
        for name, inner in value.items():
            if f"{key}.{name}" in CHOICES and inner not in CHOICES[f"{key}.{name}"]:
                raise CrucibleError(f"{key}.{name} is one of: {', '.join(CHOICES[f'{key}.{name}'])}")


def set_answer(root, key, value, words=""):
    parts = key.split(".")
    top = parts[0]
    if top == "permissions":
        raise CrucibleError(f"{key}: permission groups are answered with `crucible grant GROUP yes|no`")
    if top not in CONFIG_KEYS:
        raise CrucibleError(f"unknown key {top!r}: use one of {', '.join(CONFIG_KEYS)}")
    check_value(key, value)
    cfg = root.config()
    node = cfg
    for part in parts[:-1]:
        node = node.setdefault(part, {})
        if not isinstance(node, dict):
            raise CrucibleError(f"{key}: {part} is not a section")
    last = parts[-1]
    # A dict answer fills in the keys it names and keeps the defaults of the rest.
    if isinstance(value, dict) and isinstance(node.get(last), dict):
        node[last].update(value)
    else:
        node[last] = value
    cfg.setdefault("answers", {})[key] = {"value": value, "words": words, "at": now()}
    root.save_config(cfg)


def cmd_answer(args):
    root = Root(args.root)
    set_answer(root, args.key, parse_value(args.value), args.words or "")
    print(f"{args.key}: recorded")


def cmd_next(args):
    missing = unanswered(Root(args.root).config())
    print(missing[0] if missing else "all questions answered")


def register(sub):
    p = sub.add_parser("answer", help="record one interview answer in the config")
    p.add_argument("key", help="dotted config key, for example tracker.kind or auto_file")
    p.add_argument("value", help="JSON, or a plain string")
    p.add_argument("--words", help="the user's own words")
    p.set_defaults(func=cmd_answer)
    p = sub.add_parser("next", help="print the next unanswered interview key")
    p.set_defaults(func=cmd_next)
