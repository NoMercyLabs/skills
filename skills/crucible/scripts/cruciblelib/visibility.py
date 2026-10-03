"""Public and private: what the user confirmed for each destination, and what a finding may never share.

A repo or board is public or private only as the user confirmed it; a script read of the tracker is shown to
the user and must agree with the answer. A finding that is exploitable, live, infrastructure or personal is private.
"""
import re

from .common import CrucibleError, Root
from .permissions import now

VISIBILITIES = ("public", "private")
PRIVATE_DESTINATIONS = ("advisory", "private_repo", "local_report")
REMOTE = re.compile(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?/?$")

# Each pattern names why a finding is private. When unsure, the verifier sets private.
EXPLOITABLE = re.compile(
    r"\b(secur\w*|authn|authz|authenticat\w*|authoriz\w*|authoris\w*|auth|secrets?|credentials?|passwords?|"
    r"passwd|inject\w*|exploit\w*|vulnerab\w*|xss|csrf|ssrf|rce|access[- ]control|privilege\w*|bypass\w*)\b",
    re.IGNORECASE)
LIVE = re.compile(r"\b(production|prod|live (?:system|server|instance|environment|setting|settings|config\w*))\b",
                  re.IGNORECASE)
IPV4 = re.compile(r"(?<![\d.])(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)(?![\d.])")
INTERNAL_HOST = re.compile(r"\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:internal|local|lan|corp|intranet)\b", re.IGNORECASE)
PERSONAL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+\.[A-Za-z]{2,}|\b(?:personal data|pii|personally identifiable)\b",
                      re.IGNORECASE)
HARMLESS_IPS = ("127.0.0.1", "0.0.0.0")


def finding_texts(f):
    """Every free-text field that can say why a finding is private (not the evidence quotes, which are code)."""
    out = [str(f.get("area", "")), str(f.get("title", ""))] + [str(x) for x in f.get("labels") or []]
    for group in ("who", "what", "when", "why", "how"):
        value = f.get(group)
        if isinstance(value, dict):
            for item in value.values():
                out += [str(x) for x in item] if isinstance(item, list) else [str(item)]
    out += [str(w.get("ref", "")) for w in f.get("where") or [] if isinstance(w, dict)]
    return out


def forced_private_reasons(f):
    texts = finding_texts(f)
    blob = "\n".join(texts)
    quotes = "\n".join(str(e.get("quote", "")) for e in f.get("evidence") or [] if isinstance(e, dict))
    reasons = []
    if EXPLOITABLE.search(blob):
        reasons.append("exploitable (security, auth, secrets, injection or access control)")
    if LIVE.search(blob):
        reasons.append("a live or production setting")
    ips = [ip for ip in IPV4.findall(blob + "\n" + quotes) if ip not in HARMLESS_IPS]
    if ips or INTERNAL_HOST.search(blob):
        reasons.append("infrastructure detail (a host or address)")
    if PERSONAL.search(blob):
        reasons.append("personal data")
    return reasons


def visibility_problems(f):
    value = f.get("visibility")
    if value not in VISIBILITIES:
        return ["visibility must be public or private (the verifier sets it; when unsure, private)"]
    reasons = forced_private_reasons(f)
    if reasons and value != "private":
        return [f"visibility must be private: {reasons[0]}"]
    return []


def repo_slug(entry):
    match = REMOTE.search(entry.get("remote") or "")
    return f"{match.group(1)}/{match.group(2)}" if match else entry["name"]


def is_github_tracker(cfg):
    return (cfg.get("tracker") or {}).get("kind", "markdown") in ("github-issues", "github-project")


def tracker_slug(cfg):
    tracker = cfg.get("tracker") or {}
    if tracker.get("owner") and tracker.get("repo"):
        return f"{tracker['owner']}/{tracker['repo']}"
    return ""


def board_key(cfg):
    tracker = cfg.get("tracker") or {}
    if tracker.get("kind") == "github-project" and tracker.get("owner") and tracker.get("project_number"):
        return f"board:{tracker['owner']}/{tracker['project_number']}"
    return ""


def required_slugs(cfg):
    """Every repo and board whose visibility the user must confirm before `confirm` passes."""
    names = [repo_slug(r) for r in cfg.get("repos", [])]
    if is_github_tracker(cfg) and tracker_slug(cfg):
        names.append(tracker_slug(cfg))
    if board_key(cfg):
        names.append(board_key(cfg))
    return list(dict.fromkeys(names))


def section(cfg):
    return cfg.get("visibility") or {}


def confirmed(cfg, slug):
    """The user's confirmed visibility of a repo or board, or None."""
    row = (section(cfg).get("destinations") or {}).get(slug)
    return row.get("value") if row and row.get("confirmed") else None


def need_confirmed(cfg, slug):
    value = confirmed(cfg, slug)
    if value is None:
        raise CrucibleError(f"refused: the visibility of {slug} is not confirmed by the user: show what the "
                            f"script read, ask the user, then run `crucible visibility confirm {slug} public|private "
                            "--words \"<their words>\"`")
    return value


def is_answered(cfg):
    sec = section(cfg)
    flags = all(sec.get(k) is not None for k in ("pointers", "public_board_items", "collaborators_see_security"))
    return flags and all(confirmed(cfg, slug) for slug in required_slugs(cfg))


def private_destination_answered(cfg):
    row = cfg.get("private_destination")
    return bool(row) and row.get("kind") in PRIVATE_DESTINATIONS


def detect(cfg, adapter):
    """Read each destination's visibility with the tracker adapter; the result is shown to the user, never trusted."""
    found = {}
    for slug in required_slugs(cfg):
        if slug.startswith("board:"):
            owner, _, number = slug[len("board:"):].partition("/")
            found[slug] = adapter.board_visibility(owner, number)
        elif "/" in slug:
            found[slug] = adapter.visibility(slug)
    return found


def confirm_visibility(root, slug, value, words, detected=None):
    if value not in VISIBILITIES:
        raise CrucibleError("visibility is public or private")
    if not (words or "").strip():
        raise CrucibleError("refused: a visibility is the user's confirmation: pass their own words with --words")
    cfg = root.config()
    sec = cfg.setdefault("visibility", {})
    rows = sec.setdefault("destinations", {})
    known = detected or (rows.get(slug) or {}).get("detected")
    if known and known != value:
        raise CrucibleError(f"refused: the tracker reports {slug} as {known}, the answer is {value}: check it "
                            "with the user; a wrong answer would put private text in a public place")
    rows[slug] = {"value": value, "confirmed": True, "detected": known, "words": words, "at": now()}
    for entry in cfg.get("repos", []):
        if repo_slug(entry) == slug:
            entry["public"] = value == "public"
    root.save_config(cfg)


def cmd_visibility(args):
    root = Root(args.root)
    if args.action == "detect":
        from .trackers import get_adapter
        cfg = root.config()
        found = detect(cfg, get_adapter("github", root))
        sec = cfg.setdefault("visibility", {})
        rows = sec.setdefault("destinations", {})
        for slug, value in found.items():
            rows.setdefault(slug, {"confirmed": False})["detected"] = value
            print(f"{slug}: the tracker reports {value}; ask the user to confirm")
        root.save_config(cfg)
        return 0
    if args.action == "confirm":
        if not (args.slug and args.value):
            raise CrucibleError("usage: visibility confirm SLUG public|private --words \"...\"")
        confirm_visibility(root, args.slug, args.value, args.words or "")
        print(f"{args.slug}: {args.value} (confirmed by the user)")
        return 0
    cfg = root.config()
    for slug in required_slugs(cfg):
        print(f"{slug}: {confirmed(cfg, slug) or 'not confirmed'}")
    return 0


def register(sub):
    p = sub.add_parser("visibility", help="read, confirm or list the public or private state of each destination")
    p.add_argument("action", choices=["detect", "confirm", "list"])
    p.add_argument("slug", nargs="?", help="owner/repo, or board:owner/number")
    p.add_argument("value", nargs="?", choices=list(VISIBILITIES))
    p.add_argument("--words", help="the user's own words (required for confirm)")
    p.set_defaults(func=cmd_visibility)
