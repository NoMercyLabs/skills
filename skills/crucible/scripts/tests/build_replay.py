"""Write the scripted agent output that `crucible selftest --replay` plays back.

A scripted reader: reads every file of the unit, keeps no dropped leads.
A scripted verifier: accepts the candidates on seeded defects, rejects one on a line that is fine.
None of it is model output. Run from the scripts folder after the seeded fixture or the finding shape changes:

    python tests/build_replay.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cruciblelib import selftest  # noqa: E402
from cruciblelib.common import read_json, source_id, write_json  # noqa: E402

ACCEPTED = ("D01", "D02", "D05")
REJECTED_FILE, REJECTED_LINE = "app/config.py", 1


def quote(lines, line):
    return lines[line - 1].strip()


def candidate(repo, goal, defect, ref, text, symptom):
    """A finding that cites the real line, in the shape the gate and the root cause check accept."""
    return {
        "id": "CAND", "repo": repo, "title": defect["title"], "area": defect["area"], "goal": goal,
        "severity": "medium", "size": "S", "stage": "none",
        "who": {"affected": "operators", "owner": "platform team"},
        "what": {"summary": defect["summary"], "observed": "the line behaves as the summary describes",
                 "expected": "the line handles the case safely"},
        "where": [{"kind": "file", "ref": ref}],
        "when": {"trigger": "the input or state described in the summary", "frequency": "sometimes"},
        "why": {"cause": "the cited line has no guard for the case", "verified": True},
        "how": {"reproduce": ["call the code path with the input from the summary"],
                "fix": "add the missing check at the cited line", "prove": "a test that fails before the check"},
        "evidence": [{"kind": "file_line", "ref": ref, "quote": text}],
        "siblings": ["searched the same file for the same construct, none other found"], "not_checked": [
            "root_cause: the verifier has not re-opened the chain yet"],
        "labels": [], "visibility": "public", "intent": "no conflict with the brief",
        "chain": {
            "symptom": {"text": "the caller gets a wrong or unsafe result", "ref": symptom},
            "mechanism": [{"ref": ref, "claim": "execution reaches this statement with the unchecked input",
                           "evidence": {"kind": "file_line", "ref": ref, "quote": text}}],
            "root_cause": {"ref": ref, "claim": "nothing at this statement checks the value before it is used",
                           "evidence": {"kind": "file_line", "ref": ref, "quote": text}},
        },
        "exploration": {"runs": [ref], "followed": [f"{ref}: the only statement involved"],
                        "not_followed": [{"item": "callers outside the unit", "reason": "not in the audited files"}]},
        "root_cause_verified": False,
        "do_not_fix_by": ["hiding the failure instead of checking the input"],
    }


def build():
    work = os.path.join(tempfile.mkdtemp(prefix="crucible-replay-"), "run")
    root = selftest.prepare(work)
    expected = {d["id"]: d for d in read_json(selftest.EXPECTED)}
    goals = {g["name"].lower(): g["id"] for g in root.config()["goals"]}
    for unit in root.units():
        data = root.unit(unit)
        repo = data["repo"]
        candidates, verdicts = [], {}
        for number, defect_id in enumerate(ACCEPTED, 1):
            d = expected[defect_id]
            ref = f"{d['file']}:{d['line_start']}"
            lines = root.snapshot_lines(repo, d["file"])
            goal = next((gid for name, gid in goals.items() if d["goal"] in name), root.config()["goals"][0]["id"])
            item = candidate(repo, goal, {"title": f"Scripted reader finding {number} in {d['file']}",
                                          "area": d["file"].split("/")[0], "summary": d["summary"]},
                             ref, quote(lines, d["line_start"]), f"{d['file']}:1")
            candidates.append(item)
            verdicts[source_id(unit, item)] = {"verdict": "accept", "checked": [ref],
                                               "reason": "the cited line does what the finding says"}
        lines = root.snapshot_lines(repo, REJECTED_FILE)
        ref = f"{REJECTED_FILE}:{REJECTED_LINE}"
        fine = candidate(repo, candidates[0]["goal"], {"title": "Scripted reader finding on a line that is fine",
                                                       "area": "config", "summary": "A claim about a harmless line."},
                         ref, quote(lines, REJECTED_LINE), f"{REJECTED_FILE}:2")
        candidates.append(fine)
        verdicts[source_id(unit, fine)] = {"verdict": "reject", "checked": [ref], "other_defect": "none",
                                           "reason": "the line only sets a constant and nothing misuses it"}
        folder = os.path.join(selftest.REPLAY, unit)
        write_json(os.path.join(folder, "ledger.json"),
                   {"unit": unit, "read": list(data["files"]), "skipped": {}, "leads": []})
        write_json(os.path.join(folder, "candidates.json"), candidates)
        write_json(os.path.join(folder, "verdicts.json"), verdicts)
        print(f"wrote {folder}: {len(candidates)} candidates")


if __name__ == "__main__":
    build()
