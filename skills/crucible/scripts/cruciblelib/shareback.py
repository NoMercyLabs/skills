"""Share back (design 4f): a general lesson may be offered to the crucible repo as a public issue.

This module only drafts the text for the user to send; it sends nothing. The text is built from a short list of
general fields, never from free text, and a draft that still looks like a path, a link, an address or a key is refused.
"""
import re

from .common import CrucibleError, has_key_like
from .gate import has_privacy_word
from .permissions import log_action, now

SAFE_KEYS = ("unit_size_factor", "model_tier", "forecast_factor", "recovery", "failure_signature")
WORD = re.compile(r"^[a-z][a-z0-9_.-]{0,31}$")
DETAIL = re.compile(r"[\/@]|://|\.[a-z]{2,4}\b|\b\d{1,3}(?:\.\d{1,3}){3}\b", re.IGNORECASE)
QUESTION = "This lesson could help other crucible users. May I open a public issue on the crucible repo?"


def settings(root):
    return root.config().get("share_back") or {}


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def word(value, what):
    if not isinstance(value, str) or not WORD.match(value):
        raise CrucibleError(f"refused: share back: the {what} is not a plain word, so the draft is not built")
    return value


def privacy_words(root):
    return [w.lower() for w in root.config().get("privacy_words", []) if str(w).strip()]


def draft(lesson, words=()):
    """The issue text from the general fields of one lesson, checked before it is shown."""
    evidence, expected = lesson.get("evidence") or {}, lesson.get("expected") or {}
    lines = [f"Lesson kind: {word(lesson.get('kind'), 'kind')}",
             f"Seen in the audit's own records: {int(evidence.get('count', 0))} times"]
    for key in SAFE_KEYS:
        value = (lesson.get("change") or {}).get(key)
        if value is None:
            continue
        lines.append(f"Change: {key} = {value if number(value) else word(value, key)}")
    if number(expected.get("before")) and number(expected.get("after")):
        lines.append(f"Expected effect: from {expected['before']} to {expected['after']} per run")
    text = "\n".join(lines)
    if has_key_like(text) or DETAIL.search(text):
        raise CrucibleError("refused: share back: the draft holds a path, link, address or key; it is not offered")
    hit = next((w for w in words if has_privacy_word(text, [w])), None)
    if hit:
        raise CrucibleError(f"refused: share back: the draft holds the privacy word {hit}; it is not offered")
    return text


def eligible(lesson):
    return lesson.get("general") is True and lesson.get("target") == "audit"


def enable(root, words):
    if not (words or "").strip():
        raise CrucibleError("refused: share back is turned on with the user's own words (--words)")
    cfg = root.config()
    row = cfg.setdefault("share_back", {})
    row.update({"enabled": True, "words": words, "at": now()})
    row.setdefault("answers", {})
    root.save_config(cfg)


def answered(root, lesson):
    return (settings(root).get("answers") or {}).get(lesson["id"])


def offer(root, lesson):
    """The question and the exact text, or None: off, not general, or already answered (a no is never asked again)."""
    if not settings(root).get("enabled") or not eligible(lesson) or answered(root, lesson):
        return None
    return {"id": lesson["id"], "question": QUESTION, "text": draft(lesson, privacy_words(root))}


def answer(root, lesson, value, words):
    if not settings(root).get("enabled"):
        raise CrucibleError("refused: share back is off; the user turns it on first")
    if not eligible(lesson):
        raise CrucibleError("refused: share back: only a general audit lesson can be shared")
    if value not in ("yes", "no"):
        raise CrucibleError("the answer is yes or no")
    if not (words or "").strip():
        raise CrucibleError("refused: an answer records the user's own words (--words)")
    if answered(root, lesson):
        raise CrucibleError(f"refused: {lesson['id']} is already answered; this is final and is not asked again")
    text = draft(lesson, privacy_words(root)) if value == "yes" else None
    cfg = root.config()
    cfg["share_back"].setdefault("answers", {})[lesson["id"]] = {"answer": value, "words": words, "at": now()}
    root.save_config(cfg)
    if value == "no":
        log_action(root, "tracker_issues", f"share back {lesson['id']}", "the user said no", "skipped")
        return None
    log_action(root, "tracker_issues", f"share back {lesson['id']}",
               "the draft was shown for the user to send; nothing was sent", "ok")
    return text


def final_text(root, lesson):
    row = answered(root, lesson)
    if not row or row["answer"] != "yes":
        raise CrucibleError("refused: share back: no yes from the user for this lesson")
    return draft(lesson, privacy_words(root))


def report_lines(root):
    """The end-of-run offer: only when share back is on and an active lesson is general."""
    if not settings(root).get("enabled"):
        return []
    from .lessons import active
    ready = [x["id"] for x in active(root) if eligible(x)]
    return [f"share back: {len(ready)} general lesson(s) could help other crucible users; "
            f"to see the exact text run `crucible shareback offer {ready[0]}`; nothing is sent without your yes"] if ready else []


def cmd_shareback(args):
    from .common import Root
    from .lessons import load_lesson
    root = Root(args.root)
    root.require_confirmed()
    if args.action == "enable":
        enable(root, args.words or "")
        print("share back: on; it only drafts text, it sends nothing")
        return
    lesson = load_lesson(root, args.id)
    if args.action == "offer":
        made = offer(root, lesson)
        print(f"{made['question']}\n{made['text']}" if made else "nothing to offer")
    else:
        text = answer(root, lesson, args.action, args.words or "")
        print(text + "\nsend this yourself; crucible sent nothing" if text else f"{args.id}: no, not asked again")


def register(sub):
    p = sub.add_parser("shareback", help="draft a general lesson as a public issue text for the user to send; off by default")
    p.add_argument("action", choices=["enable", "offer", "yes", "no"])
    p.add_argument("id", nargs="?", help="the lesson id; not needed for enable")
    p.add_argument("--words", help="the user's own words")
    p.set_defaults(func=cmd_shareback)
