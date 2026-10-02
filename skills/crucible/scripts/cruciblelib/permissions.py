import datetime
import hashlib
import json
import os
import re

from .common import CrucibleError, Root, mask_secrets, read_json, write_json
from .status import coverage_counts, coverage_line, repo_coverage_lines, tokens_line

GROUPS = ("local_reads", "agent_runs", "installs", "memory_writes", "tracker_board", "tracker_labels",
          "tracker_issues", "tracker_advisories", "tracker_assignees", "tracker_comments", "live_checks",
          "publish_report", "blocker_fixes", "blocker_pushes", "transcripts", "workspace_clones", "history", "knowledge_sources",
          "knowledge_clone", "user_instructions")

# What each group lets the run do, what it costs and where the data goes: the plan prints these verbatim.
GROUP_INFO = {
    "local_reads": ("read every file of the chosen repos", "no cost beyond the reads",
                    "the code is sent to the model provider that runs the agents"),
    "agent_runs": ("run readers and verifiers", "tokens up to the cap in config.budget",
                   "the code is sent to the model provider that runs the agents"),
    "installs": ("install what the setup needs (the user runs plugin commands)", "none beyond the install",
                 "downloads to this machine"),
    "memory_writes": ("write facts, rules and findings to permanent memory", "none",
                      "stays on this machine"),
    "tracker_board": ("create or map the board, its fields and its views", "none", "the tracker"),
    "tracker_labels": ("create the named labels", "none", "the tracker"),
    "tracker_issues": ("create issues, up to max_count, in the listed repos", "none",
                       "the tracker; issues on a public repo are public"),
    "tracker_advisories": ("draft security advisories in the listed repos", "none",
                           "the tracker, as private drafts"),
    "tracker_assignees": ("assign the named people", "none", "the tracker"),
    "tracker_comments": ("comment on existing issues", "none", "the tracker"),
    "live_checks": ("run the named read-only commands against the named targets", "none",
                    "the named targets only"),
    "publish_report": ("publish the final report outside the audit folder", "none",
                       "the places named in the bounds"),
    "blocker_fixes": ("fix what blocks the audit or filing", "tokens for the fix and its proof",
                      "the landing chosen in config.blocker_fixes"),
    "blocker_pushes": ("push the fix branch of a fixed blocker to its remote, so a pull request can be opened",
                       "none", "the remote of the repo; a push to a public repo is public"),
    "transcripts": ("read only the shell commands and exit codes of agent transcripts for the listed repos",
                    "none", "stays on this machine; the conversation and the tool output are never read out"),
    "workspace_clones": ("clone the named repos read-only into the chosen fresh base folder", "disk for the clones",
                         "the clones stay on this machine; the user's own checkouts are never touched"),
    "history": ("read only the user's own past messages in the agent history of the listed repos, to find answers "
                "already given", "none", "stays on this machine; only the matched quote, its source and its date "
                "are kept, never the assistant's text or tool output"),
    "knowledge_sources": ("pull the named outside sources into the audit folder", "none",
                          "read-only requests to the named sources"),
    "knowledge_clone": ("clone the named git knowledge sources into a scratch folder and read their text", "disk "
                        "for the clone until it is read", "the clone stays on this machine and is removed after the read"),
    "user_instructions": ("read the size and the headings of the user-wide agent instruction file named in the bounds",
                          "none", "stays on this machine; the text is never printed or sent anywhere"),
}

LIST_BOUNDS = ("repos", "labels", "assignees", "kinds", "sources", "targets", "commands")
BOUND_KEYS = LIST_BOUNDS + ("max_count", "instance", "mode")
ACTION_STATUSES = ("ok", "refused", "skipped", "failed")
PLAN_HASH = re.compile(r"^[0-9a-f]{8,64}$")


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def parse_bounds(items):
    """['repos=a,b', 'max_count=3'] -> {'repos': ['a', 'b'], 'max_count': 3}; a repeated list key adds to it."""
    bounds = {}
    for item in items or []:
        key, sep, value = item.partition("=")
        key = key.strip()
        if not sep or key not in BOUND_KEYS:
            raise CrucibleError(f"bad bound {item!r}: use key=value with key one of {', '.join(BOUND_KEYS)}")
        if key in LIST_BOUNDS:
            bounds.setdefault(key, []).extend(v.strip() for v in value.split(",") if v.strip())
        elif key == "max_count":
            if not value.strip().isdigit():
                raise CrucibleError(f"bad bound {item!r}: max_count is a whole number")
            bounds[key] = int(value)
        else:
            bounds[key] = value.strip()
    return bounds


def log_path(root):
    return root.p("actions.log")


def log_action(root, group, command, result, status):
    if status not in ACTION_STATUSES:
        raise CrucibleError(f"bad action status {status!r}: use one of {', '.join(ACTION_STATUSES)}")
    line = {"at": now(), "group": group, "command": mask_secrets(command), "result": mask_secrets(result),
            "status": status}
    try:
        os.makedirs(root.path, exist_ok=True)
        with open(log_path(root), "a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")
    except OSError as exc:
        raise CrucibleError(f"refused: cannot write {log_path(root)} ({exc}); an action that cannot be logged is not taken")


def read_log(root):
    path = log_path(root)
    if not os.path.isfile(path):
        return []
    rows = []
    with open(path, encoding="utf-8") as fh:
        for text in fh:
            try:
                rows.append(json.loads(text))
            except ValueError:
                continue
    return rows


def refuse(root, group, action, reason):
    message = f"refused: {group}: {reason}"
    log_action(root, group, action, message, "refused")
    raise CrucibleError(message)


def wanted(want):
    """Normalise the want of an action: list keys become lists, `count` becomes `max_count`."""
    out = {}
    for key, value in want.items():
        if value is None:
            continue
        key = "max_count" if key == "count" else key
        if key in LIST_BOUNDS:
            out[key] = [value] if isinstance(value, str) else list(value)
        else:
            out[key] = value
    return out


def authorize(root, group, action, **want):
    if group not in GROUPS:
        raise CrucibleError(f"unknown permission group {group!r}")
    grant_row = root.config().get("permissions", {}).get(group)
    if not grant_row:
        refuse(root, group, action, "no answer yet: ask the user, then run `crucible grant "
                                    f"{group} yes|no`")
    if grant_row["answer"] != "yes":
        refuse(root, group, action, "the user answered no; this is final and is not asked again")
    bounds = grant_row.get("bounds", {})
    for key, value in wanted(want).items():
        if key not in bounds:
            refuse(root, group, action, f"{key} is not in the granted bounds")
        if key in LIST_BOUNDS:
            outside = [v for v in value if v not in bounds[key]]
            if outside:
                refuse(root, group, action, f"{key} {', '.join(map(str, outside))} not granted "
                                            f"(granted: {', '.join(bounds[key]) or 'none'})")
        elif key == "max_count":
            if value > bounds[key]:
                refuse(root, group, action, f"count {value} is over the granted max_count {bounds[key]}")
        elif value != bounds[key]:
            refuse(root, group, action, f"{key} {value} is not the granted {bounds[key]}")


def run_action(root, group, command, fn, **want):
    authorize(root, group, command, **want)
    try:
        os.makedirs(root.path, exist_ok=True)
        with open(log_path(root), "a", encoding="utf-8"):
            pass
    except OSError as exc:
        raise CrucibleError(f"refused: cannot write {log_path(root)} ({exc}); an action that cannot be logged is not taken")
    try:
        result = fn()
    except Exception as exc:
        log_action(root, group, command, f"{type(exc).__name__}: {exc}", "failed")
        raise
    log_action(root, group, command, "" if result is None else str(result), "ok")
    return result


def grant(root, group, answer, words="", bounds=None, reopen=False):
    if group not in GROUPS:
        raise CrucibleError(f"unknown permission group {group!r}: use one of {', '.join(GROUPS)}")
    if answer not in ("yes", "no"):
        raise CrucibleError("the answer is yes or no")
    if not (words or "").strip():
        raise CrucibleError(f"refused: a grant records the user's own words: ask the user, then pass them with "
                            f"--words (for example `crucible grant {group} {answer} --words \"<their words>\"`)")
    cfg = root.config()
    permissions = cfg.setdefault("permissions", {})
    before = permissions.get(group)
    if before and before["answer"] == "no" and answer == "yes":
        if not (reopen and words):
            raise CrucibleError(f"refused: the user answered no to {group}; a no is final. "
                                "Only the user can reopen it: run `grant GROUP yes --reopen --words \"<their words>\"`")
    permissions[group] = {"answer": answer, "words": words, "bounds": bounds or {}, "at": now()}
    root.save_config(cfg)


def require_approved(root, plan_hash):
    """The gate `file --apply` calls: auto_file true passes; otherwise the user must have approved this exact plan."""
    if root.config().get("auto_file") is True:
        return
    approved = read_json(root.p("approvals.json"), [])
    if plan_hash not in [row["hash"] for row in approved]:
        refuse(root, "tracker_issues", f"apply plan {plan_hash}",
               "the plan is not approved: show the dry run to the user, then run `crucible approve "
               f"{plan_hash}`")


def record_dryrun(root, plan_hash, plan=None):
    """Remember a plan hash that `file --dry-run` produced; only such a hash can be approved or applied."""
    rows = read_json(root.p("dryruns.json"), [])
    if plan_hash not in [row["hash"] for row in rows]:
        rows.append({"hash": plan_hash, "at": now(), "plan": plan})
        write_json(root.p("dryruns.json"), rows)


def dryrun_hashes(root):
    return [row["hash"] for row in read_json(root.p("dryruns.json"), [])]


def approve(root, plan_hash):
    if not PLAN_HASH.match(plan_hash or ""):
        raise CrucibleError(f"{plan_hash!r} is not a plan hash (8 to 64 lowercase hex characters)")
    if plan_hash not in dryrun_hashes(root):
        raise CrucibleError(f"refused: no `file --dry-run` produced plan {plan_hash}; run the dry run, show the "
                            "user its list, then approve the hash it printed")
    approved = read_json(root.p("approvals.json"), [])
    if plan_hash not in [row["hash"] for row in approved]:
        approved.append({"hash": plan_hash, "at": now()})
        write_json(root.p("approvals.json"), approved)


def describe_bounds(bounds):
    return "; ".join(f"{k}={','.join(map(str, v)) if isinstance(v, list) else v}" for k, v in bounds.items())


def plan_text(cfg):
    permissions = cfg.get("permissions", {})
    lines = ["Where data goes: the code the agents read is sent to the model provider that runs them."]
    for group in GROUPS:
        what, cost, where = GROUP_INFO[group]
        row = permissions.get(group)
        state = "not answered" if not row else row["answer"]
        lines.append(f"{group}: {state}")
        lines.append(f"  does: {what}")
        lines.append(f"  cost: {cost}")
        lines.append(f"  data goes to: {where}")
        if row and row["bounds"]:
            lines.append(f"  bounds: {describe_bounds(row['bounds'])}")
    auto = cfg.get("auto_file")
    lines.append("filing: " + ("not answered" if auto is None else
                               "within the granted bounds without asking again" if auto else
                               "dry run first, then wait for `crucible approve PLAN_HASH`"))
    return "\n".join(lines)


def cmd_plan(args):
    text = plan_text(Root(args.root).config())
    print(text)
    print("plan hash: " + hashlib.sha256(text.encode("utf-8")).hexdigest()[:12])


def cmd_grant(args):
    root = Root(args.root)
    grant(root, args.group, args.answer, args.words or "", parse_bounds(args.bound), args.reopen)
    print(f"{args.group}: {args.answer}")


def cmd_approve(args):
    approve(Root(args.root), args.plan_hash)
    print(f"approved plan {args.plan_hash}")


def knowledge_lines(state):
    entries = state.get("knowledge") or {}
    absorbed, missed = [], []
    for name, entry in sorted(entries.items()):
        entry = entry if isinstance(entry, dict) else {"status": str(entry)}
        if entry.get("status") in ("absorbed", "ok"):
            count = entry.get("count")
            absorbed.append(f"  {name}" + (f": {count} documents" if count is not None else ""))
        else:
            missed.append(f"  {name}: {entry.get('reason') or entry.get('status') or 'not absorbed'}")
    return absorbed, missed


def cmd_report(args):
    root = Root(args.root)
    root.require_confirmed()
    cfg, state = root.config(), root.state()
    rows = read_log(root)
    taken = [r for r in rows if r["status"] in ("ok", "failed")]
    stopped = [r for r in rows if r["status"] in ("refused", "skipped")]
    print(f"actions taken: {len(taken)}")
    for r in taken:
        print(f"  {r['at']} {r['group']} {r['status']}: {r['command']}")
    print(f"actions refused or skipped: {len(stopped)}")
    for r in stopped:
        print(f"  {r['at']} {r['group']} {r['status']}: {r['command']} ({r['result']})")
    counts, _ = coverage_counts(root)
    print(coverage_line(counts))
    for line in repo_coverage_lines(root):
        print(line)
    print(tokens_line(cfg, state))
    from .filing import counts
    by_visibility, by_destination = counts(root)
    if by_visibility:
        print("filed by visibility: " + ", ".join(f"{k} {v}" for k, v in sorted(by_visibility.items())))
        print("filed by destination: " + ", ".join(f"{k} {v}" for k, v in sorted(by_destination.items())))
    from .blockers import report_lines
    print("\n".join(report_lines(root)))
    from .brief import routing_lines
    print("\n".join(routing_lines(root)))
    from .heal import report_lines as healed_lines
    if healed_lines(root):
        print("\n".join(healed_lines(root)))
    from .shareback import report_lines as shareback_lines
    if shareback_lines(root):
        print("\n".join(shareback_lines(root)))
    absorbed, missed = knowledge_lines(state)
    if absorbed or missed:
        print("knowledge sources absorbed: " + str(len(absorbed)))
        print("\n".join(absorbed))
        print("knowledge sources not absorbed: " + str(len(missed)))
        print("\n".join(missed))


def register(sub):
    p = sub.add_parser("plan", help="list every action the run can take, with bounds, cost and where data goes")
    p.set_defaults(func=cmd_plan)
    p = sub.add_parser("grant", help="record the user's yes or no for one permission group")
    p.add_argument("group", choices=GROUPS)
    p.add_argument("answer", choices=["yes", "no"])
    p.add_argument("--words", help="the user's own words")
    p.add_argument("--bound", action="append", metavar="KEY=VALUE",
                   help=f"a bound ({', '.join(BOUND_KEYS)}); lists are comma separated; repeatable")
    p.add_argument("--reopen", action="store_true", help="reopen a no; needs the user's words in --words")
    p.set_defaults(func=cmd_grant)
    p = sub.add_parser("approve", help="record the user's go for one plan hash")
    p.add_argument("plan_hash")
    p.set_defaults(func=cmd_approve)
    p = sub.add_parser("report", help="actions taken, refused or skipped, coverage, tokens, sources")
    p.set_defaults(func=cmd_report)
