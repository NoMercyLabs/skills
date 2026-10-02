"""Self-improving (design 4f): patterns in crucible's own records become lessons the user decides on.

A lesson that only tunes the audit lives in `<root>/lessons/`, one file per lesson; it is never written into the
skill's own files. A lesson that would help the user's normal workflow is a change to the user's own file and goes
through the same dry run, backup, diff and yes as every other change to it.
"""
import contextlib
import difflib
import hashlib
import io
import os
import re
import shutil
import tempfile

from . import selftest
from .backup import backup
from .common import CrucibleError, Root, has_key_like, read_json, write_json
from .models import TIERS
from .permissions import dryrun_hashes, log_action, now, read_log, record_dryrun, refuse
from .repeats import MIN_RUNS, find_repeats, shape_of
from .transcripts import inside

MIN_OCCURRENCES = 3
MEASURED_STATUSES = ("failed", "refused")
STATES = ("proposed", "active", "applied", "reverted")
TARGETS = ("audit", "workflow")
RECOVERIES = ("report", "rerun_once", "split_unit", "resend_prompt", "resume_after_wait")
# The only keys a lesson may hold. Everything else is refused, so a lesson cannot reach a safety, permission,
# privacy, visibility, root-cause or gate rule.
AUDIT_KEYS = ("unit_size_factor", "model_tier", "reader_addendum", "failure_signature", "recovery", "forecast_factor")
WORKFLOW_KEYS = ("shape", "instruction_line")
SAFETY_WORDS = re.compile(r"safe|permission|privacy|private|visib|root.?cause|gate|grant|secret", re.IGNORECASE)


def lessons_dir(root):
    return root.p("lessons")


def lesson_path(root, lesson_id):
    if not re.match(r"^L-[A-Za-z0-9]+$", str(lesson_id)):
        raise CrucibleError(f"{lesson_id!r} is not a lesson id (L- and letters or digits)")
    return os.path.join(lessons_dir(root), lesson_id + ".json")


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def check_change(change, target):
    """Refuse every key outside the allow-list and every value that loosens: a lesson only tunes or tightens."""
    if not isinstance(change, dict) or not change:
        raise CrucibleError("a lesson holds a change: a non-empty object")
    allowed = AUDIT_KEYS if target == "audit" else WORKFLOW_KEYS
    for key, value in change.items():
        if key not in allowed:
            why = "it would reach a safety rule" if SAFETY_WORDS.search(key) else "it is not on the allow-list"
            raise CrucibleError(f"lesson refused: key {key!r} is not allowed ({why}); allowed: {', '.join(allowed)}")
        if key == "unit_size_factor" and not (number(value) and 0 < value <= 1):
            raise CrucibleError("lesson refused: unit_size_factor must be above 0 and at most 1 (smaller units only)")
        if key == "forecast_factor" and not (number(value) and value > 0):
            raise CrucibleError("lesson refused: forecast_factor must be a number above 0")
        if key == "model_tier":
            tiers = [t for t in TIERS if t != "top"]
            if not isinstance(value, dict) or any(not isinstance(k, str) or v not in tiers for k, v in value.items()):
                raise CrucibleError(f"lesson refused: model_tier maps a risk class to one of {', '.join(tiers)}; "
                                    "the top tier is never set by a lesson")
        if key in ("reader_addendum", "instruction_line", "shape", "failure_signature"):
            if not isinstance(value, str) or not value.strip() or len(value) > 500 or "\n" in value.strip():
                raise CrucibleError(f"lesson refused: {key} must be one short line of text")
            if has_key_like(value):
                raise CrucibleError(f"lesson refused: {key} holds a key-like string")
        if key == "recovery" and value not in RECOVERIES:
            raise CrucibleError(f"lesson refused: recovery must be one of {', '.join(RECOVERIES)}")
    if ("recovery" in change) != ("failure_signature" in change):
        raise CrucibleError("lesson refused: failure_signature and recovery go together")


def load_lesson(root, lesson_id):
    path = lesson_path(root, lesson_id)
    data = read_json(path, None)
    if data is None:
        raise CrucibleError(f"unknown lesson {lesson_id}: run `crucible learn list`")
    if not isinstance(data, dict) or data.get("id") != lesson_id:
        raise CrucibleError(f"{path} is not the lesson {lesson_id}")
    if data.get("target") not in TARGETS or data.get("state") not in STATES:
        raise CrucibleError(f"{path} has no valid target and state")
    check_change(data.get("change"), data["target"])
    return data


def all_lessons(root):
    folder = lessons_dir(root)
    names = sorted(n[:-5] for n in os.listdir(folder) if n.endswith(".json")) if os.path.isdir(folder) else []
    return [load_lesson(root, name) for name in names]


def active(root):
    return [x for x in all_lessons(root) if x["state"] == "active"]


def reader_addenda(root):
    """The one-line addenda of the active audit lessons, in lesson id order; they go into each unit file."""
    return [x["change"]["reader_addendum"] for x in active(root)
            if x["target"] == "audit" and "reader_addendum" in x["change"]]


def occurrences(root):
    """One row per failure in crucible's own records: the action log and, when present, failures.json."""
    rows = []
    for index, row in enumerate(read_log(root)):
        if row.get("status") in MEASURED_STATUSES and row.get("group") != "lessons":
            signature = f"{row.get('group')}:{row['status']}:{shape_of(row.get('result', ''))}"
            rows.append({"signature": signature, "kind": "failure_signature", "id": f"actions.log#{index}",
                         "at": row.get("at", "")})
    for index, row in enumerate(read_json(root.p("failures.json"), []) or []):
        if not isinstance(row, dict):
            continue
        name = str(row.get("class", "unknown"))
        if name == "context_exhausted":
            kind = "unit_size"
        elif name == "unknown":
            kind = "failure_signature"
        else:
            continue
        rows.append({"signature": str(row.get("signature") or name), "kind": kind,
                     "id": str(row.get("id") or f"failures.json#{index}"), "at": str(row.get("at", ""))})
    return rows


def find_patterns(root, minimum=MIN_OCCURRENCES):
    """Signatures seen at least `minimum` times in this audit folder's records (earlier runs share its log)."""
    groups = {}
    for row in occurrences(root):
        entry = groups.setdefault(row["signature"], {"signature": row["signature"], "kind": row["kind"],
                                                     "count": 0, "records": []})
        entry["count"] += 1
        entry["records"].append(row["id"])
    return sorted((e for e in groups.values() if e["count"] >= minimum), key=lambda e: (-e["count"], e["signature"]))


def lesson_id(kind, signature):
    return "L-" + hashlib.sha1(f"{kind}|{signature}".encode("utf-8")).hexdigest()[:8]


def audit_lesson(pattern):
    if pattern["kind"] == "unit_size":
        change = {"unit_size_factor": 0.75}
        metric = "context-exhausted failures per run"
    else:
        change = {"failure_signature": pattern["signature"], "recovery": "report"}
        metric = "failures of this signature per run"
    return {"id": lesson_id(pattern["kind"], pattern["signature"]), "target": "audit", "kind": pattern["kind"],
            "signature": pattern["signature"], "state": "proposed",
            "evidence": {"count": pattern["count"], "records": pattern["records"]}, "change": change,
            "expected": {"metric": metric, "before": pattern["count"], "after": 0},
            "check": "run `crucible learn review` after the next runs: it counts this signature again"}


def workflow_lesson(row):
    shape = row["shape"]
    line = f"The command shape `{shape}` repeats: put it in one script and run that script, never build it by hand."
    return {"id": lesson_id("script_for_repeat", shape), "target": "workflow", "kind": "script_for_repeat",
            "signature": shape, "state": "proposed",
            "evidence": {"count": row["runs"], "records": [f"repeats:{row['runs']} runs"], "failed": row["failed"],
                         "retried": row["retried"], "tokens": row["tokens"]},
            "change": {"shape": shape, "instruction_line": line},
            "expected": {"metric": "hand-built runs of this command shape", "before": row["runs"], "after": 0},
            "check": "run `crucible repeats --scripts INDEX` later: it shows the script's use against hand commands"}


def propose(root, repeats=None):
    """Write one proposed lesson per pattern; returns those written. A lesson already decided is left alone."""
    wanted = [audit_lesson(p) for p in find_patterns(root)]
    wanted += [workflow_lesson(r) for r in (repeats or {}).get("repeats", []) if r["runs"] >= MIN_OCCURRENCES]
    written = []
    for lesson in wanted:
        check_change(lesson["change"], lesson["target"])
        path = lesson_path(root, lesson["id"])
        old = read_json(path, None)
        if old and old.get("state") != "proposed":
            continue
        write_json(path, lesson)
        written.append(lesson)
    log_action(root, "lessons", "learn propose", f"{len(written)} lessons proposed", "ok")
    return written


def scores(text):
    """(found, invented, coverage percent) from the score output."""
    found, invented, coverage = (re.search(pattern, text) for pattern in
                                 (r"found (\d+) of", r"invented (\d+)", r"coverage (\d+)%"))
    return tuple(int(m.group(1)) if m else -1 for m in (found, invented, coverage))


def seeded_run(work, lesson=None):
    """The scripted replay in a fresh folder, then its score; -> (replay exit code, score output)."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = selftest.cmd_replay(work)
    if code:
        return code, out.getvalue()
    if lesson:
        write_json(os.path.join(work, "lessons", lesson["id"] + ".json"), dict(lesson, state="active"))
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        selftest.cmd_score(Root(work))
    return 0, out.getvalue()


def run_selftest(root, lesson):
    """The seeded pipeline with the lesson in place: the replay must pass and the score must not be lower than
    the run without it. The replay is scripted, so its score stays below the real pass mark; it is compared, not
    held to that mark."""
    base = tempfile.mkdtemp(prefix="crucible-lesson-")
    try:
        try:
            _code, without = seeded_run(os.path.join(base, "without"))
            code, text = seeded_run(os.path.join(base, "with"), lesson)
        except CrucibleError as exc:
            return False, f"SELFTEST FAIL: {exc}"
        if code:
            return False, "SELFTEST FAIL: the replay failed with the lesson\n" + text.rstrip()
        (found, invented, coverage), (b_found, b_invented, b_coverage) = scores(text), scores(without)
        if found < b_found or invented > b_invented or coverage < b_coverage:
            return False, (f"SELFTEST FAIL: found {found}, invented {invented}, coverage {coverage}% with the lesson; "
                           f"{b_found}, {b_invented}, {b_coverage}% without it")
        return True, f"SELFTEST PASS: replay ok, found {found}, invented {invented}, coverage {coverage}% (without the lesson {b_found}, {b_invented}, {b_coverage}%)"
    finally:
        shutil.rmtree(base, ignore_errors=True)


def read_file(path):
    with open(path, encoding="utf-8", newline="") as fh:
        return fh.read()


def workflow_plan(lesson, repo, rel):
    path = os.path.join(repo, rel) if repo and rel else None
    if not path or not inside(repo, path) or not os.path.isfile(path):
        raise CrucibleError("a workflow lesson needs --repo and --file naming an instruction file inside that repo")
    text = read_file(path)
    newline = "\r\n" if "\r\n" in text else "\n"
    line = lesson["change"]["instruction_line"]
    new = text + ("" if text.endswith("\n") or not text else newline) + line + newline
    diff = "".join(difflib.unified_diff(text.splitlines(True), new.splitlines(True), rel, rel))
    digest = hashlib.sha256(f"{lesson['id']}|{rel}|{text}|{line}".encode("utf-8")).hexdigest()[:16]
    return {"path": path, "new": new, "diff": diff, "hash": digest, "file": rel}


def save(root, lesson):
    write_json(lesson_path(root, lesson["id"]), lesson)


def apply(root, lesson_id, yes=False, repo=None, rel=None, dry_run=False):
    lesson = load_lesson(root, lesson_id)
    action = f"learn apply {lesson_id}"
    if lesson["state"] != "proposed":
        refuse(root, "lessons", action, f"the lesson is {lesson['state']}, not proposed")
    if lesson["target"] == "workflow":
        return apply_workflow(root, lesson, yes, repo, rel, dry_run)
    if dry_run:
        return {"diff": f"{lesson_id}: {lesson['change']}", "hash": None}
    if not yes:
        refuse(root, "lessons", action, "nothing is applied without the user's yes: show the evidence and the "
                                        "change, then run again with --yes")
    ok, output = run_selftest(root, lesson)
    if not ok:
        refuse(root, "lessons", action, f"the lesson failed the selftest and is not used:\n{output}")
    lesson.update(state="active", applied_at=now(), selftest=output.splitlines()[-1] if output else "", measures=[])
    save(root, lesson)
    log_action(root, "lessons", action, "active", "ok")
    return lesson


def apply_workflow(root, lesson, yes, repo, rel, dry_run):
    action = f"learn apply {lesson['id']}"
    plan = workflow_plan(lesson, repo, rel)
    if dry_run:
        record_dryrun(root, plan["hash"], {"lesson": lesson["id"], "file": rel})
        log_action(root, "lessons", action, f"dry run {plan['hash']}", "ok")
        return plan
    if plan["hash"] not in dryrun_hashes(root):
        refuse(root, "lessons", action, "no dry run of this exact change: run with --dry-run, show the user the diff")
    if not yes:
        refuse(root, "lessons", action, "nothing is applied without the user's yes: run again with --yes")
    backup(root, f"instructions-{rel}", plan["path"])
    with open(plan["path"], "w", encoding="utf-8", newline="") as fh:
        fh.write(plan["new"])
    lesson.update(state="applied", applied_at=now(), applied_to={"path": plan["path"], "file": rel})
    save(root, lesson)
    log_action(root, "lessons", action, f"line added to {rel}", "ok")
    return lesson


def revert(root, lesson_id):
    lesson = load_lesson(root, lesson_id)
    action = f"learn revert {lesson_id}"
    if lesson["state"] not in ("active", "applied"):
        refuse(root, "lessons", action, f"the lesson is {lesson['state']}, nothing to revert")
    backup(root, f"lesson-{lesson_id}", lesson_path(root, lesson_id))
    result = "reverted"
    target = lesson.get("applied_to")
    if target:
        path = target["path"]
        text = read_file(path) if os.path.isfile(path) else ""
        line = lesson["change"]["instruction_line"]
        found = re.search(re.escape(line) + r"\r?\n", text)
        if found:
            backup(root, f"instructions-{target['file']}", path)
            with open(path, "w", encoding="utf-8", newline="") as fh:
                fh.write(text[:found.start()] + text[found.end():])
        else:
            result = f"reverted; the line is no longer in {target['file']}, remove nothing by hand"
    lesson.update(state="reverted", reverted_at=now())
    save(root, lesson)
    log_action(root, "lessons", action, result, "ok")
    return lesson


def review(root, at=None):
    """Count each active audit lesson's signature again since its last measurement. A lesson whose last two
    windows both ran above the count that proved it is proposed for revert; nothing is reverted here."""
    at = at or now()
    rows = occurrences(root)
    measured, worse = [], []
    for lesson in active(root):
        if lesson["target"] != "audit":
            continue
        windows = lesson.setdefault("measures", [])
        since = windows[-1]["at"] if windows else lesson.get("applied_at", "")
        count = sum(1 for r in rows if r["signature"] == lesson["signature"] and since < r["at"] <= at)
        windows.append({"at": at, "count": count})
        before = lesson["evidence"]["count"]
        if len(windows) >= 2 and all(w["count"] > before for w in windows[-2:]):
            worse.append(lesson["id"])
        measured.append({"id": lesson["id"], "before": before, "now": count, "windows": len(windows)})
        save(root, lesson)
    log_action(root, "lessons", "learn review", f"{len(measured)} lessons measured, {len(worse)} worse", "ok")
    return {"measured": measured, "revert": worse}


def show(lesson):
    ev = lesson["evidence"]
    print(f"{lesson['id']} ({lesson['target']}, {lesson['kind']}): seen {ev['count']} times")
    print(f"  evidence: {', '.join(ev['records'][:5])}{' ...' if len(ev['records']) > 5 else ''}")
    print(f"  change: {lesson['change']}")
    expected = lesson["expected"]
    print(f"  expected: {expected['metric']} from {expected['before']} to {expected['after']}")
    print(f"  check: {lesson['check']}")


def cmd_learn(args):
    root = Root(args.root)
    root.require_confirmed()
    command = args.learn_command
    if command == "propose":
        found = None
        if args.transcripts:
            names = args.repo or [r["name"] for r in root.config()["repos"]]
            found = find_repeats(root, args.transcripts, names, minimum=MIN_RUNS)
        made = propose(root, repeats=found)
        for lesson in made:
            show(lesson)
        print(f"{len(made)} lessons proposed; nothing is applied without a yes")
    elif command == "apply":
        repo = None
        if args.repo:
            paths = {r["name"]: r["path"] for r in root.config()["repos"]}
            if args.repo not in paths:
                raise CrucibleError(f"{args.repo} is not a repo in the config")
            repo = paths[args.repo]
        result = apply(root, args.id, yes=args.yes, repo=repo, rel=args.file, dry_run=args.dry_run)
        if args.dry_run:
            print(result["diff"])
            if result["hash"]:
                print(f"dry run {result['hash']}: show the user the diff, then run again with --yes")
        else:
            print(f"{args.id} {result['state']}")
    elif command == "list":
        for lesson in all_lessons(root):
            print(f"{lesson['id']} {lesson['state']} {lesson['target']} {lesson['kind']}: seen {lesson['evidence']['count']} times")
    elif command == "revert":
        print(f"{args.id} {revert(root, args.id)['state']}")
    else:
        result = review(root)
        for row in result["measured"]:
            print(f"{row['id']}: {row['before']} before, {row['now']} in the last window ({row['windows']} windows)")
        for lesson_id_ in result["revert"]:
            print(f"worse over 2 windows, propose revert: crucible learn revert {lesson_id_}")


def register(sub):
    p = sub.add_parser("learn", help="turn patterns in crucible's own records into lessons the user decides on")
    parts = p.add_subparsers(dest="learn_command", required=True)
    pro = parts.add_parser("propose", help="list lessons for signatures seen 3 or more times; writes proposals only")
    pro.add_argument("--transcripts", metavar="DIR", help="also propose scripts for repeated commands; needs the transcripts grant")
    pro.add_argument("--repo", action="append", help="a repo name in scope for --transcripts")
    app = parts.add_parser("apply", help="use a lesson; needs --yes")
    app.add_argument("id")
    app.add_argument("--yes", action="store_true", help="the user said yes")
    app.add_argument("--dry-run", action="store_true", help="show the change and write nothing")
    app.add_argument("--repo", help="a workflow lesson: the repo name of the instruction file")
    app.add_argument("--file", help="a workflow lesson: the instruction file, relative to the repo")
    parts.add_parser("list", help="every lesson and its state")
    rev = parts.add_parser("revert", help="undo a lesson by id")
    rev.add_argument("id")
    parts.add_parser("review", help="measure active lessons against their evidence; proposes a revert for a worse one")
    p.set_defaults(func=cmd_learn)
