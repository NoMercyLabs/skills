"""Reliability proof: the whole pipeline on the seeded fixture, scored against its known defects.

Three modes:
  --prepare --work DIR   a run folder with the fixture (without EXPECTED.json), the interview answered with
                         plain defaults, and the inventory done; prints the commands a reader and a verifier use.
  --replay --work DIR    the full pipeline with SCRIPTED agent output from fixtures/replay/. The recordings are
                         written by a script (tests/build_replay.py), not by a model: they prove the engine
                         (stamps, proof, verdict check, accept, gate, status, tamper refusal) and nothing about
                         how well a model reads. The scripted reader's transcript is rebuilt from the engine's
                         own `show` output on every run, because stamps are keyed per audit folder.
  --root DIR --score     matches the accepted findings of a run folder against fixtures/seeded/EXPECTED.json
                         by file and line range, and checks coverage and proof per unit.
"""
import contextlib
import io
import json
import os
import shutil

from . import proof
from .common import CrucibleError, Root, read_json
from .gate import parse_ref
from .permissions import GROUPS
from .status import coverage_counts, unit_status
from .visibility import required_slugs

SKILL = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIXTURE = os.path.join(SKILL, "fixtures", "seeded")
EXPECTED = os.path.join(FIXTURE, "EXPECTED.json")
REPLAY = os.path.join(SKILL, "fixtures", "replay")
WORDS = "selftest default"
MIN_FOUND = 10
REPLAY_NOTE = ("replay: the agent output is scripted (fixtures/replay), not model output; "
               "it proves the engine only, not what a model finds")


def engine(root, *args):
    """Run one crucible command in-process; -> (exit code, its output)."""
    from . import cli
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = cli.main(["--root", root.path, *args])
        except SystemExit as exc:
            code = exc.code or 0
    return code, out.getvalue() + err.getvalue()


def must(root, *args):
    code, text = engine(root, *args)
    if code:
        raise CrucibleError(f"selftest setup step failed: crucible {' '.join(args)}\n{text.strip()}")
    return text


def interview_defaults(root):
    """The interview answered the plain way: nothing filed, no blocker fixes, no grants, everything private."""
    must(root, "memory", "none", "--words", WORDS)
    for field in ("purpose", "good", "intentional", "must_never_change", "accepted_risks", "out_of_scope",
                  "known_issues"):
        must(root, "brief", "answer", field, "--words", WORDS)
    must(root, "brief", "confirm")
    must(root, "answer", "auto_file", "false", "--words", WORDS)
    must(root, "answer", "blocker_fixes", '{"mode": "never"}', "--words", WORDS)
    for group in GROUPS:
        must(root, "grant", group, "no", "--words", WORDS)
    for flag in ("public_board_items", "collaborators_see_security", "pointers"):
        must(root, "answer", f"visibility.{flag}", "false", "--words", WORDS)
    must(root, "answer", "private_destination", '{"kind": "local_report"}', "--words", WORDS)
    for slug in required_slugs(root.config()):
        must(root, "visibility", "confirm", slug, "private", "--words", WORDS)
    must(root, "workspace", "choose", "this_repo", "--words", WORDS)
    must(root, "answer", "models.fable", "false", "--words", WORDS)
    must(root, "confirm")


def prepare(work):
    root = Root(work)
    if os.path.exists(root.p("config.json")):
        raise CrucibleError(f"selftest refused: {root.path} already holds an audit; use a new folder")
    # EXPECTED.json stays out of the folder, so no reader can see the answers
    shutil.copytree(FIXTURE, root.p("repo"), ignore=shutil.ignore_patterns("EXPECTED*"))
    must(root, "init", "--repo", root.p("repo"))
    interview_defaults(root)
    must(root, "inventory")
    return root


def cmd_prepare(root):
    for unit in root.units():
        data = root.unit(unit)
        print(f"unit {unit}: {len(data['files'])} files, {data['lines']} lines")
        for path in data["files"]:
            print(f"  crucible --root {root.path} show {unit} {path} [--page N]")
        print(f"  crucible --root {root.path} proof {unit} TRANSCRIPT")
        print(f"  crucible --root {root.path} verdict-check {unit}")
        print(f"  crucible --root {root.path} accept {unit}")


def shown_rows(root, unit, files):
    """The transcript rows of a scripted reader that ran `show` on every page of each file."""
    rows = []
    for path in files:
        page = 1
        while True:
            text = must(root, "show", unit, path, "--page", str(page))
            rows.append({"message": {"role": "user", "content": [{"type": "tool_result", "content": text}]}})
            if "=== NEXT:" not in text:
                break
            page += 1
    return rows


def write_rows(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


def tampered(rows):
    """A copy of the rows with one numbered source line changed under its stamp."""
    out = json.loads(json.dumps(rows))
    for row in out:
        part = row["message"]["content"][0]
        lines = part["content"].split("\n")
        if len(lines) > 2 and not lines[1].startswith("=== END"):
            lines[1] += " tampered"
            part["content"] = "\n".join(lines)
            return out
    raise CrucibleError("selftest: no shown page to tamper with")


def replay_step(root, *args):
    print(f"$ crucible {' '.join(args)}")
    code, text = engine(root, *args)
    print(text.rstrip())
    if code:
        raise CrucibleError(f"replay failed at: crucible {' '.join(args)}")


def cmd_replay(work):
    print(REPLAY_NOTE)
    root = prepare(work)
    first = None
    for unit in root.units():
        recorded = os.path.join(REPLAY, unit)
        if not os.path.isdir(recorded):
            raise CrucibleError(f"no replay recording for unit {unit}: run tests/build_replay.py")
        rows = shown_rows(root, unit, root.unit(unit)["files"])
        transcript = root.p("replay", unit + ".jsonl")
        write_rows(transcript, rows)
        first = first or (unit, rows)
        for name, target in (("ledger.json", ("ledger", unit + ".json")),
                             ("candidates.json", ("candidates", unit + ".json")),
                             ("verdicts.json", ("review", f"verdicts-{unit}.json"))):
            os.makedirs(os.path.dirname(root.p(*target)), exist_ok=True)
            shutil.copyfile(os.path.join(recorded, name), root.p(*target))
        for args in (("proof", unit, transcript), ("verdict-check", unit), ("accept", unit)):
            replay_step(root, *args)
    replay_step(root, "gate")
    replay_step(root, "status")
    unit, rows = first
    path = root.p("replay", "tampered.jsonl")
    write_rows(path, tampered(rows))
    ok, message = proof.check_proof(root, unit, path)
    if ok or not message.startswith("TAMPER REFUSED"):
        print(f"TAMPER NOT REFUSED: {message}")
        return 1
    print("TAMPER REFUSED: " + message.split(": ", 1)[1])
    return 0


def finding_spans(finding):
    """(path, first line, last line) of every file position a finding cites in where and evidence."""
    refs = [w.get("ref") for w in finding.get("where", []) if isinstance(w, dict) and w.get("kind") == "file"]
    refs += [e.get("ref") for e in finding.get("evidence", []) if isinstance(e, dict) and e.get("kind") == "file_line"]
    prefix = str(finding.get("repo", "")) + "/"
    spans = []
    for ref in refs:
        parsed = parse_ref(str(ref)) if ref else None
        if parsed:
            path, a, b = parsed
            spans.append((path[len(prefix):] if path.startswith(prefix) else path, a, b))
    return spans


def cmd_score(root):
    root.require_confirmed()
    expected = read_json(EXPECTED)
    findings = root.findings()
    found, invented = {}, []
    for fid, finding in findings.items():
        hits = [d["id"] for d in expected for path, a, b in finding_spans(finding)
                if path == d["file"] and a <= d["line_end"] and d["line_start"] <= b]
        if not hits:
            invented.append(fid)
        for hit in hits:
            found.setdefault(hit, fid)
    missed = [d["id"] for d in expected if d["id"] not in found]
    print(f"found {len(found)} of {len(expected)}" + (f" ({', '.join(sorted(found))})" if found else ""))
    print(f"missed {len(missed)}" + (f": {', '.join(missed)}" if missed else ""))
    print(f"invented {len(invented)}" + (f" ({', '.join(invented)})" if invented else ""))
    counts, _ = coverage_counts(root)
    total = sum(counts.values())
    covered = counts.get("done", 0) + counts.get("carried", 0)
    print(f"units read {covered} of {total}")
    recorded = root.state()["units"]
    failed_proof = []
    for unit in root.units():
        if unit_status(root, unit) == "split":
            continue
        passed = recorded.get(unit, {}).get("proof") == "pass"
        print(f"proof {'PASS' if passed else 'FAIL'} {unit}")
        if not passed:
            failed_proof.append(unit)
    percent = 100 * covered // total if total else 0
    print(f"coverage {percent}%")
    reasons = []
    if len(found) < MIN_FOUND:
        reasons.append(f"found {len(found)} of {len(expected)}, at least {MIN_FOUND} needed")
    if invented:
        reasons.append(f"{len(invented)} invented findings accepted")
    if percent < 100:
        reasons.append(f"coverage {percent}%")
    if failed_proof:
        reasons.append(f"{len(failed_proof)} units without a passing proof")
    print("SELFTEST " + ("FAIL: " + "; ".join(reasons) if reasons else "PASS"))
    return 1 if reasons else 0


def cmd_selftest(args):
    if args.score:
        return cmd_score(Root(args.root))
    if not args.work:
        raise CrucibleError("selftest --prepare and --replay need --work DIR")
    if args.replay:
        return cmd_replay(args.work)
    cmd_prepare(prepare(args.work))
    return 0


def register(sub):
    p = sub.add_parser("selftest", help="run the pipeline on the seeded fixture and score it")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true", help="make a run folder for a reader and a verifier")
    mode.add_argument("--replay", action="store_true", help="run the pipeline on scripted agent output")
    mode.add_argument("--score", action="store_true", help="score the accepted findings of --root against the fixture")
    p.add_argument("--work", help="run folder for --prepare and --replay")
    p.set_defaults(func=cmd_selftest)
