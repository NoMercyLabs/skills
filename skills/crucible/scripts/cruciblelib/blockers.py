"""Blockers and their fixes: a blocker is recorded, a fix is planned against the root cause, and the fix runs only
with the user's grant, a backup first, and a proof that the blocked stage now runs."""
import os
import shlex
import subprocess

from . import brief, rootcause
from .backup import backup
from .common import CrucibleError, Root, read_json, write_json
from .permissions import authorize, log_action, now, refuse

GROUP = "blocker_fixes"
STATUSES = ("open", "fixed", "failed")
COMMAND_TIMEOUT = 600


def load(root):
    return read_json(root.p("blockers.json"), [])


def find(root, blocker_id):
    for row in load(root):
        if row["id"] == blocker_id:
            return row
    raise CrucibleError(f"unknown blocker {blocker_id}: run `crucible blocker list`")


def set_status(root, blocker_id, status):
    rows = load(root)
    for row in rows:
        if row["id"] == blocker_id:
            row["status"] = status
    write_json(root.p("blockers.json"), rows)


def add(root, description, stage):
    if not (description or "").strip():
        raise CrucibleError("a blocker needs a description")
    rows = load(root)
    row = {"id": f"B-{len(rows) + 1:03d}", "description": description.strip(), "stage": stage or "", "status": "open",
           "at": now()}
    write_json(root.p("blockers.json"), rows + [row])
    return row


def plan_path(root, blocker_id):
    return root.p("fixes", blocker_id + ".json")


def touch_path(touch):
    path, _, tail = str(touch).strip().replace("\\", "/").rpartition(":")
    path = path if path and tail.replace("-", "").isdigit() else str(touch).strip().replace("\\", "/")
    return path[2:] if path.startswith("./") else path


def plan_problems(root, plan):
    """Problems that stop a fix plan; an empty list means the plan may go on."""
    problems = []
    if not plan.get("cause", "").strip() or not plan.get("evidence"):
        problems.append("the fix plan needs the cause and the evidence for it (file:line or command output)")
    if not plan.get("why_symptom_patch_not_enough", "").strip():
        problems.append("the fix plan must say why a symptom patch would not be enough (why_symptom_patch_not_enough)")
    if not plan.get("change") or not plan.get("proof"):
        problems.append("the fix plan needs the change command and the proof command that re-runs the blocked stage")
    key = rootcause.ref_key(plan.get("root_cause", ""))
    if key is None:
        problems.append("root_cause must be a file:line link to the cause of the blocker")
    problems += brief.fix_plan_problems(root, plan)
    if key is None:
        return problems
    cause_path = key[0]
    if cause_path not in [touch_path(t) for t in plan.get("touches") or []]:
        problems.append(f"refused: the fix does not touch the root cause ({cause_path}): a change only at the "
                        "symptom hides the problem; change the cause, or say why the cause is somewhere else")
    if cause_path not in [touch_path(t["target"]) for t in plan.get("tests") or []]:
        problems.append(f"the fix plan names no test whose target is the root cause file ({cause_path}): the test "
                        "must reproduce the cause, not only the symptom")
    return problems


def split_tests(items):
    tests = []
    for item in items or []:
        name, sep, target = item.partition("=")
        if not sep or not name.strip() or not target.strip():
            raise CrucibleError(f"bad --test {item!r}: use NAME=file:line, the test and the file it checks")
        tests.append({"name": name.strip(), "target": target.strip()})
    return tests


def split_command(text, label):
    try:
        argv = shlex.split(text or "")
    except ValueError as exc:
        raise CrucibleError(f"bad {label} command ({exc})")
    if not argv:
        raise CrucibleError(f"the {label} command is empty")
    return argv


def repo_dir(root):
    repos = root.config().get("repos") or []
    if not repos:
        raise CrucibleError("no repo in the config: run `crucible init --repo PATH`")
    return repos[0]["path"]


def cmd_blocker_add(args):
    row = add(Root(args.root), args.description, args.stage)
    print(f"{row['id']} {row['status']} {row['stage'] or '-'}: {row['description']}")


def cmd_blocker_list(args):
    rows = load(Root(args.root))
    for row in rows:
        print(f"{row['id']} {row['status']} {row['stage'] or '-'}: {row['description']}")
    print(f"blockers: {len(rows)}, open {sum(1 for r in rows if r['status'] == 'open')}")


def cmd_fix_plan(args):
    root = Root(args.root)
    find(root, args.blocker_id)
    blockers_cfg = root.config().get("blocker_fixes") or {}
    touches = [t.strip() for t in args.touch or [] if t.strip()]
    repo = repo_dir(root)
    plan = {
        "blocker": args.blocker_id, "cause": args.cause or "", "evidence": list(args.evidence or []),
        "root_cause": args.root_cause or "", "touches": touches, "tests": split_tests(args.test),
        "backup": [t for t in touches if os.path.isfile(os.path.join(repo, *touch_path(t).split("/")))],
        "landing": blockers_cfg.get("landing") or "pr", "branch": blockers_cfg.get("branch"),
        "change": split_command(args.change, "change"), "proof": split_command(args.proof, "proof"),
        "why_symptom_patch_not_enough": args.why or "", "at": now(),
    }
    problems = plan_problems(root, plan)
    if problems:
        raise CrucibleError("\n".join(f"refused: {p}" if not p.startswith("refused") else p for p in problems))
    write_json(plan_path(root, args.blocker_id), plan)
    print(f"fix plan written: {plan_path(root, args.blocker_id)}")
    print(f"touches: {', '.join(touches)}")
    print(f"root cause: {plan['root_cause']}")
    print(f"landing: {plan['landing']}")
    print("proof: " + " ".join(plan["proof"]))


def run_command(argv, repo):
    try:
        done = subprocess.run(argv, cwd=repo, capture_output=True, text=True, timeout=COMMAND_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, f"{type(exc).__name__}: {exc}"
    return done.returncode, (done.stdout + done.stderr).strip()[-500:]


def check_may_run(root, command, yes_words):
    authorize(root, GROUP, command)
    mode = (root.config().get(GROUP) or {}).get("mode")
    if mode not in ("each", "within_limits"):
        refuse(root, GROUP, command, f"the blocker fix mode is {mode or 'not answered'}: no fix runs")
    if mode == "each" and not (yes_words or "").strip():
        refuse(root, GROUP, command, "the user chose to approve each fix: ask them about this plan, then pass "
                                     "their own words with --yes-words")


def cmd_fix_run(args):
    root = Root(args.root)
    root.require_confirmed()
    row = find(root, args.blocker_id)
    command = f"fix run {args.blocker_id}"
    check_may_run(root, command, args.yes_words)
    plan = read_json(plan_path(root, args.blocker_id))
    if plan is None:
        raise CrucibleError(f"no fix plan for {args.blocker_id}: run `crucible fix plan {args.blocker_id}` first")
    problems = plan_problems(root, plan)
    if problems:
        refuse(root, GROUP, command, "; ".join(problems))
    repo = repo_dir(root)
    for source in plan["backup"]:
        backup(root, f"{args.blocker_id}-{touch_path(source).replace('/', '-')}",
               os.path.join(repo, *touch_path(source).split("/")))
    code, text = run_command(plan["change"], repo)
    if code == 0:
        code, text = run_command(plan["proof"], repo)
    status = "fixed" if code == 0 else "failed"
    set_status(root, args.blocker_id, status)
    log_action(root, GROUP, command, f"{status}: stage {row['stage'] or '-'} re-run: {text}",
               "ok" if code == 0 else "failed")
    print(f"{args.blocker_id} {status}")
    return 0 if code == 0 else 1


def register(sub):
    p = sub.add_parser("blocker", help="record or list what stops a stage")
    actions = p.add_subparsers(dest="action", metavar="action", required=True)
    q = actions.add_parser("add", help="record a blocker")
    q.add_argument("description")
    q.add_argument("--stage", help="the stage that cannot go on")
    q.set_defaults(func=cmd_blocker_add)
    q = actions.add_parser("list", help="list the blockers and their status")
    q.set_defaults(func=cmd_blocker_list)
    p = sub.add_parser("fix", help="plan or run the fix of a blocker")
    actions = p.add_subparsers(dest="action", metavar="action", required=True)
    q = actions.add_parser("plan", help="write the fix plan against the root cause")
    q.add_argument("blocker_id")
    q.add_argument("--cause", help="the cause of the blocker")
    q.add_argument("--evidence", action="append", metavar="TEXT", help="evidence for the cause; repeatable")
    q.add_argument("--root-cause", metavar="FILE:LINE", help="the link where the cause starts")
    q.add_argument("--touch", action="append", metavar="ITEM", help="a file, setting or behaviour the fix changes")
    q.add_argument("--test", action="append", metavar="NAME=FILE:LINE", help="a test and the root cause file it checks")
    q.add_argument("--change", help="the command that makes the change")
    q.add_argument("--proof", help="the command that re-runs the blocked stage; exit 0 means it runs")
    q.add_argument("--why", help="why a symptom patch would not be enough")
    q.set_defaults(func=cmd_fix_plan)
    q = actions.add_parser("run", help="back up, change, re-run the blocked stage")
    q.add_argument("blocker_id")
    q.add_argument("--yes-words", help="the user's own yes for this plan (needed when the mode is each)")
    q.set_defaults(func=cmd_fix_run)
