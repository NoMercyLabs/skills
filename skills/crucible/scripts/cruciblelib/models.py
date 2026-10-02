import math
import re

from .common import Root, split_lines, write_json
from .inventory import READER_TOKENS_PER_LINE, VERIFIER_SHARE, DEFAULT_UNIT_BYTES, pack, walk_text_files

TIERS = ("fast", "balanced", "strong", "top")
LOW_TIER = "fast"
# A planning default for one judgment call over finding summaries; calibration replaces it with a measured number.
JUDGE_CALL_TOKENS = 4000

# Low is checked first: a test inside an auth folder is still a test.
LOW_PATH = re.compile(r"(^|/)(docs?|tests?|__tests__|fixtures?|generated|gen|dist|build|vendor|third_party)(/|$)"
                      r"|\.(md|rst|txt|lock|snap)$|\.min\.|_pb2\.|\.generated\.", re.IGNORECASE)
HIGH_PATH = re.compile(r"auth|login|session|crypt|payment|billing|secret|token|passw|migrat|deploy|dockerfile"
                       r"|(^|/)\.github/workflows/|\.tf$|route|endpoint|controller|handler|webhook|parser", re.IGNORECASE)
HIGH_CONTENT = re.compile(r"password|passwd|secret|api[_-]?key|crypto|\beval\(|\bexec\(|subprocess|"
                          r"create table|alter table|drop table", re.IGNORECASE)

# The jobs that may use the top tier, each with how many calls the plan can count before findings exist.
COMPLEX_JOBS = {
    "group_by_cause": ("group findings by shared cause across units and repos", 1),
    "verify_critical": ("verify each critical finding: a wrong critical costs the user the most", 0),
    "blocker_root_cause": ("find the root cause of a blocker after one failed fix", 0),
    "priority_order": ("set the final priority order from the finding summaries", 1),
}


def unit_risk(items):
    """items: [(relative path, text)]. High if any file is risky, low only if every file is low."""
    kinds = []
    for rel, text in items:
        if LOW_PATH.search(rel):
            kinds.append("low")
        elif HIGH_PATH.search(rel) or HIGH_CONTENT.search(text):
            kinds.append("high")
        else:
            kinds.append("normal")
    if "high" in kinds:
        return "high"
    return "low" if kinds and all(k == "low" for k in kinds) else "normal"


def read_text(path):
    with open(path, "rb") as fh:
        return fh.read().decode("utf-8", errors="replace")


def scan_units(cfg):
    """The units an inventory would make, without writing a snapshot: the model plan is asked before confirm."""
    units, scope = [], cfg.get("scope", {})
    for repo in cfg["repos"]:
        files = walk_text_files(repo["path"], scope.get("skip", []), scope.get("include", []))
        for index, group in enumerate(pack(files, cfg.get("unit_bytes", DEFAULT_UNIT_BYTES)), 1):
            items = [(rel, read_text(full)) for rel, full, size in group]
            units.append({"unit": f"{repo['name']}-u{index:02d}", "files": [rel for rel, text in items],
                          "lines": sum(len(split_lines(text.encode("utf-8"))) for rel, text in items),
                          "risk": unit_risk(items)})
    return units


def inventory_units(root):
    state = root.state()["units"]
    units = []
    for name in root.units():
        if state.get(name, {}).get("status") in ("split", "carried"):
            continue
        unit = root.unit(name)
        items = [(rel, "\n".join(root.snapshot_lines(unit["repo"], rel))) for rel in unit["files"]]
        units.append({"unit": name, "files": unit["files"], "lines": unit["lines"], "risk": unit_risk(items)})
    return units


def load_units(root):
    return inventory_units(root) if root.units() else scan_units(root.config())


def fable_allowed(cfg):
    return cfg.get("models", {}).get("fable") is True


def fable_answer(cfg):
    value = cfg.get("models", {}).get("fable")
    return "not answered" if value is None and "models.fable" not in cfg.get("answers", {}) else "yes" if value else "no"


def bulk_tier(tier):
    """Readers and ordinary verifiers never use the top tier."""
    return "strong" if tier == "top" else tier


def build_plan(cfg, units, fable):
    chosen = cfg["models"]
    reader_tier = bulk_tier(chosen["reader"])
    for unit in units:
        unit["reader_tier"] = LOW_TIER if unit["risk"] == "low" else reader_tier
    per_tier, tokens = {}, {}
    for unit in units:
        per_tier[unit["reader_tier"]] = per_tier.get(unit["reader_tier"], 0) + 1
        tokens[unit["reader_tier"]] = tokens.get(unit["reader_tier"], 0) + unit["lines"] * READER_TOKENS_PER_LINE
    reader_tokens = sum(tokens.values())
    verifier_tokens = math.ceil(reader_tokens * VERIFIER_SHARE)
    verifier_tier = bulk_tier(chosen["verifier"])
    top_or_strong = "top" if fable else "strong"
    judge_tier = top_or_strong if chosen.get("judge", "strong") in ("strong", "top") else chosen["judge"]
    jobs = {name: {"tier": judge_tier, "reason": reason, "calls": calls, "tokens": calls * JUDGE_CALL_TOKENS}
            for name, (reason, calls) in COMPLEX_JOBS.items()}
    roles = {
        "reader": {"tier": reader_tier, "units_per_tier": per_tier, "tokens": reader_tokens,
                   "reason": "reading whole files and naming a real cause with exact line evidence is judgment; "
                             "docs, tests and generated code are low risk and go to the fast tier"},
        "verifier": {"tier": verifier_tier, "critical_tier": judge_tier, "input": "cited_lines_only",
                     "tokens": verifier_tokens,
                     "reason": "a different agent that gets only the candidates and their cited lines, not the "
                               "whole unit, so it costs a fraction of reading; a critical finding gets a stronger "
                               "verifier"},
        "blocker_fix": {"tier": "balanced", "tokens": 0,
                        "reason": "a first fix attempt is ordinary work; the strong tier only after one failed "
                                  "attempt, with the failure as input (counted when a blocker happens)"},
    }
    amounts = dict(tokens)
    amounts[verifier_tier] = amounts.get(verifier_tier, 0) + verifier_tokens
    for job in jobs.values():
        amounts[job["tier"]] = amounts.get(job["tier"], 0) + job["tokens"]
    return {"fable": fable, "fable_answer": "yes" if fable else "no", "availability": "not checked",
            "units": units, "roles": roles, "complex_jobs": jobs, "estimate": amounts,
            "judgment_tokens": sum(job["tokens"] for job in jobs.values())}


def plan_for(root, fable=None):
    cfg = root.config()
    plan = build_plan(cfg, load_units(root), fable_allowed(cfg) if fable is None else fable)
    plan["fable_answer"] = fable_answer(cfg)
    return plan


def tier_lines(amounts):
    return [f"tier {tier}: {amounts[tier]}" for tier in TIERS if amounts.get(tier)]


def cmd_models(args):
    root = Root(args.root)
    plan = plan_for(root)
    with_fable = plan if plan["fable"] else plan_for(root, True)
    without = plan if not plan["fable"] else plan_for(root, False)
    write_json(root.p("model-plan.json"), plan)
    print("model plan; model availability was not checked (the user's plan may not include every model)")
    print(f"units: {len(plan['units'])}")
    for role, entry in plan["roles"].items():
        print(f"{role}: {entry['tier']}, about {entry['tokens']} tokens")
        print(f"  why: {entry['reason']}")
    reader = plan["roles"]["reader"]["units_per_tier"]
    print("reader units per tier: " + (", ".join(f"{t}: {n} units" for t, n in sorted(reader.items())) or "none"))
    verifier = plan["roles"]["verifier"]
    print(f"verifier input: {verifier['input']}; critical findings: {verifier['critical_tier']}")
    print(f"complex jobs ({'top tier' if plan['fable'] else 'strong tier'}):")
    for name, job in plan["complex_jobs"].items():
        print(f"  {name}: {job['tier']}, {job['calls']} calls counted up front; {job['reason']}")
    print(f"Claude Fable for the complex jobs: {plan['fable_answer']}"
          + (" (counts as no)" if plan["fable_answer"] == "not answered" else ""))
    print("estimate without Fable: " + ", ".join(tier_lines(without["estimate"])))
    print("estimate with Fable: " + ", ".join(tier_lines(with_fable["estimate"])))


def register(sub):
    p = sub.add_parser("models", help="write the model plan: tier, reason and tokens per role")
    p.set_defaults(func=cmd_models)
