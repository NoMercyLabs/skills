"""Root causes, never symptoms: the checks on a finding's causal chain, exploration record and history, the
grouping of findings that share a root cause, and the issue text that carries the chain.

Facts come from the snapshot and from git, not from the finding's own words."""
import re

from .common import Root

LINK_FIELDS = ("ref", "claim")
LINK_EVIDENCE_KINDS = ("file_line", "explore")
OVERLAP_LIMIT = 0.6
STOP_WORDS = {
    "the", "and", "that", "this", "with", "from", "when", "which", "into", "than", "then", "there", "their",
    "have", "has", "had", "will", "would", "does", "doing", "done", "not", "are", "was", "were", "for", "but",
    "its", "any", "all", "can", "may", "because", "while", "also", "each", "every", "only", "such",
}


def words(text):
    return {w for w in re.findall(r"[a-z0-9_]+", str(text).lower()) if len(w) >= 4 and w not in STOP_WORDS}


def restates(cause, what):
    """True when most of the cause's own words already stand in the what (summary, observed, expected)."""
    own = words(cause)
    if not own:
        return False
    return len(own & words(" ".join(what))) / len(own) > OVERLAP_LIMIT


def ref_key(ref):
    from .gate import parse_ref
    parsed = parse_ref(str(ref))
    return None if parsed is None else (parsed[0].replace("\\", "/"), parsed[1], parsed[2])


def ref_text(key):
    path, a, b = key
    return f"{path}:{a}" if a == b else f"{path}:{a}-{b}"


def links(chain):
    """[(name, link)] for every mechanism step and the root cause."""
    out = []
    for i, step in enumerate(chain.get("mechanism") or []):
        out.append((f"chain.mechanism[{i}]", step))
    out.append(("chain.root_cause", chain.get("root_cause")))
    return out


def link_refs(f):
    chain = f.get("chain")
    if not isinstance(chain, dict):
        return []
    return [str(l["ref"]).strip() for _, l in links(chain) if isinstance(l, dict) and l.get("ref")]


def link_evidence_problems(root, f, name, link, runs):
    from .gate import need_text, quote_found, snapshot_range
    problems = []
    if not isinstance(link, dict):
        return [f"{name} is missing"]
    ok_ref = need_text(problems, link.get("ref"), f"{name}.ref")
    if ok_ref and ref_key(link["ref"]) is None:
        problems.append(f"{name}.ref {link['ref']!r} is not path:line")
    need_text(problems, link.get("claim"), f"{name}.claim")
    ev = link.get("evidence")
    if not isinstance(ev, dict):
        problems.append(f"{name}.evidence is missing: every link cites a quote at a real line or an explore run")
        return problems
    ev_name = f"{name}.evidence"
    kind = ev.get("kind")
    if kind not in LINK_EVIDENCE_KINDS:
        problems.append(f"{ev_name}.kind must be one of {', '.join(LINK_EVIDENCE_KINDS)}")
        return problems
    ok_eref, ok_quote = need_text(problems, ev.get("ref"), f"{ev_name}.ref"), need_text(problems, ev.get("quote"), f"{ev_name}.quote")
    if not (ok_eref and ok_quote):
        return problems
    if kind == "explore":
        key = ref_key(ev["ref"])
        if key is None or ref_text(key) not in runs:
            problems.append(f"{ev_name} names an explore run that is not in exploration.runs ({ev['ref']})")
        return problems
    from .gate import parse_ref
    parsed = parse_ref(ev["ref"])
    if not parsed:
        problems.append(f"{ev_name}.ref {ev['ref']!r} is not path:line")
        return problems
    text = snapshot_range(root, ev.get("repo") or f.get("repo", ""), *parsed)
    if text is None:
        problems.append(f"{ev_name}: {ev['ref']} is not in the snapshot (file missing or line past the end)")
    elif not quote_found(ev["quote"], text):
        problems.append(f"{ev_name}: the quote is not at {ev['ref']} in the snapshot")
    return problems


def exploration_problems(f):
    from .gate import need_list, need_text
    problems = []
    rec = f.get("exploration")
    if not isinstance(rec, dict):
        return ["exploration is missing: record the explore runs, what was followed and what was not"]
    runs = [r for r in need_list(problems, rec.get("runs"), "exploration.runs")]
    for i, run_ in enumerate(runs):
        need_text(problems, run_, f"exploration.runs[{i}]")
    if not isinstance(rec.get("followed"), list):
        problems.append("exploration.followed must be a list")
    else:
        for i, item in enumerate(rec["followed"]):
            need_text(problems, item, f"exploration.followed[{i}]")
    not_followed = rec.get("not_followed")
    if not isinstance(not_followed, list):
        problems.append("exploration.not_followed must be a list ([] when everything was followed)")
    else:
        for i, item in enumerate(not_followed):
            name = f"exploration.not_followed[{i}]"
            if not isinstance(item, dict):
                problems.append(f"{name} is not an object with item and reason")
                continue
            need_text(problems, item.get("item"), f"{name}.item")
            need_text(problems, item.get("reason"), f"{name}.reason")
    return problems


def earlier_fixes(cfg, f):
    """[(sha, message, ref)] fix or revert commits that touched the chain's cited lines; [] when the repo is
    not a git repo or nothing is found. Read from git, never from the finding."""
    from .explore import FIX_RE, history
    entry = next((r for r in cfg.get("repos", []) if r.get("name") == f.get("repo")), None)
    if not entry:
        return []
    found, seen = [], set()
    for ref in link_refs(f):
        key = ref_key(ref)
        if key is None:
            continue
        try:
            commits = history(entry, key[0], key[1], key[2])
        except Exception:  # an untracked file or a git failure is "not checked", never a crash
            commits = None
        for c in commits or []:
            if FIX_RE.search(c[2]) and c[0] not in seen:
                seen.add(c[0])
                found.append((c[0], c[2], ref_text(key)))
    return found


def prior_fix_problems(cfg, f):
    from .gate import need_text
    problems = []
    fixes = earlier_fixes(cfg, f)
    prior = f.get("prior_fix")
    if not fixes:
        return problems
    listed = prior.get("commits") if isinstance(prior, dict) else None
    for sha, message, ref in fixes:
        covered = isinstance(listed, list) and any(
            isinstance(c, str) and c and (sha.startswith(c) or c.startswith(sha)) for c in listed)
        if not covered:
            problems.append(f"earlier fix {sha} on {ref} ({message}): list it in prior_fix.commits and say whether "
                            f"it treated a symptom (prior_fix.treated_symptom) and why the defect came back (prior_fix.why_back)")
    if isinstance(prior, dict):
        if not isinstance(prior.get("treated_symptom"), bool):
            problems.append("prior_fix.treated_symptom must be true or false")
        need_text(problems, prior.get("why_back"), "prior_fix.why_back")
    return problems


def check_chain(root, f, cfg):
    """All the root-cause problems of one finding; empty means the chain passes."""
    from .gate import need_list, need_text
    problems = []
    chain = f.get("chain")
    if not isinstance(chain, dict):
        problems.append("chain is missing: symptom, mechanism steps with file:line, and the root cause")
        chain = {}
    exploration = f.get("exploration") if isinstance(f.get("exploration"), dict) else {}
    runs = set()
    for r in exploration.get("runs") or []:
        key = ref_key(r) if isinstance(r, str) else None
        if key:
            runs.add(ref_text(key))
    if chain:
        symptom = chain.get("symptom")
        if not isinstance(symptom, dict):
            problems.append("chain.symptom is missing")
            symptom = {}
        else:
            need_text(problems, symptom.get("text"), "chain.symptom.text")
            need_text(problems, symptom.get("ref"), "chain.symptom.ref")
            if symptom.get("ref") and ref_key(symptom["ref"]) is None:
                problems.append(f"chain.symptom.ref {symptom['ref']!r} is not path:line")
        need_list(problems, chain.get("mechanism"), "chain.mechanism")
        for name, link in links({**chain, "mechanism": chain.get("mechanism") if isinstance(chain.get("mechanism"), list) else []}):
            problems += link_evidence_problems(root, f, name, link, runs)
        root_cause = chain.get("root_cause")
        if isinstance(root_cause, dict) and symptom.get("ref") and root_cause.get("ref"):
            a, b = ref_key(symptom["ref"]), ref_key(root_cause["ref"])
            if a and b and a == b:
                problems.append("chain.root_cause is at the symptom's own file:line: the cause is a different place "
                                "(the decision, code, config or missing check that starts the chain)")
    why = f.get("why") if isinstance(f.get("why"), dict) else {}
    what = f.get("what") if isinstance(f.get("what"), dict) else {}
    if why.get("cause") and restates(why["cause"], [what.get(k, "") for k in ("summary", "observed", "expected")]):
        problems.append("why.cause restates what: it repeats the summary or the observed text. Say what starts the "
                        "chain (a decision, a missing check, a config value), not the result")
    problems += exploration_problems(f)
    do_not = f.get("do_not_fix_by")
    entries = need_list(problems, do_not, "do_not_fix_by")
    for i, entry in enumerate(entries):
        need_text(problems, entry, f"do_not_fix_by[{i}]")
    verified = f.get("root_cause_verified")
    not_checked = f.get("not_checked") if isinstance(f.get("not_checked"), list) else []
    if not isinstance(verified, bool):
        problems.append("root_cause_verified must be true or false")
    elif verified:
        from .gate import snapshot_range
        for r in f.get("verified_links") or []:
            key = ref_key(r) if isinstance(r, str) else None
            if key is None:
                problems.append(f"verified_links entry {r!r} is not path:line")
            elif snapshot_range(root, f.get("repo"), *key) is None:
                problems.append(f"verified_links entry {r} is not a real file and line")
        have = {ref_key(r) for r in (f.get("verified_links") or []) if isinstance(r, str)}
        missing = [r for r in link_refs(f) if ref_key(r) not in have]
        if missing:
            problems.append("root_cause_verified is true but verified_links does not list every link the verifier "
                            f"re-opened (missing {', '.join(missing)})")
    elif not any(str(n).startswith("root_cause:") for n in not_checked):
        problems.append("root_cause_verified is false: not_checked needs an entry starting 'root_cause:'")
    problems += prior_fix_problems(cfg, f)
    return problems


def verdict_link_problems(f, verdict):
    """For the accept step: a verified root cause needs every link ref among the verdict's checked lines."""
    if not isinstance(f, dict) or f.get("root_cause_verified") is not True:
        return []
    checked = verdict.get("checked") or []
    checked = checked if isinstance(checked, list) else [checked]
    covered = []
    for c in checked:
        key = ref_key(c) if isinstance(c, str) else None
        if key:
            covered.append(key)
    problems = []
    for ref in link_refs(f):
        key = ref_key(ref)
        if key and not any(key[0] == c[0] and c[1] <= key[1] and key[2] <= c[2] for c in covered):
            problems.append(f"root_cause_verified is true but the verdict did not re-open {ref}")
    return problems


def group_by_root_cause(findings):
    """Group findings whose root causes sit at the same place (same repo, same file, overlapping lines).
    -> [{repo, root_cause, findings: [ids], symptoms: [refs]}]. Whether two different places are one cause is a
    judgment for the cross-unit step; this is only the script's grouping."""
    items = []
    for fid, f in sorted(findings.items()):
        chain = f.get("chain") if isinstance(f.get("chain"), dict) else {}
        cause = chain.get("root_cause") if isinstance(chain.get("root_cause"), dict) else {}
        key = ref_key(cause.get("ref", "")) if cause.get("ref") else None
        symptom = (chain.get("symptom") or {}).get("ref") if isinstance(chain.get("symptom"), dict) else None
        items.append({"id": f.get("id", fid), "repo": f.get("repo", ""), "key": key, "symptom": symptom})
    groups = []
    for item in items:
        home = None
        for g in groups:
            if item["key"] and g["key"] and g["repo"] == item["repo"] and g["key"][0] == item["key"][0] \
                    and g["key"][1] <= item["key"][2] and item["key"][1] <= g["key"][2]:
                home = g
                break
        if home is None:
            home = {"repo": item["repo"], "key": item["key"], "findings": [], "symptoms": []}
            groups.append(home)
        elif item["key"]:
            home["key"] = (home["key"][0], min(home["key"][1], item["key"][1]), max(home["key"][2], item["key"][2]))
        home["findings"].append(item["id"])
        if item["symptom"]:
            home["symptoms"].append(item["symptom"])
    return [{"repo": g["repo"], "root_cause": ref_text(g["key"]) if g["key"] else "no chain recorded",
             "findings": sorted(g["findings"]), "symptoms": sorted(g["symptoms"])} for g in groups]


def render_chain(f):
    chain = f.get("chain")
    if not isinstance(chain, dict):
        return "not recorded"
    symptom = chain.get("symptom") or {}
    rows = [f"Symptom: {symptom.get('text', '')} ({symptom.get('ref', '')})"]
    for i, step in enumerate(chain.get("mechanism") or [], 1):
        rows.append(f"{i}. `{step.get('ref', '')}`: {step.get('claim', '')}")
    cause = chain.get("root_cause") or {}
    rows.append(f"Root cause: `{cause.get('ref', '')}`: {cause.get('claim', '')}")
    verified = "re-opened by the verifier" if f.get("root_cause_verified") else "not verified"
    rows.append(f"({verified})")
    prior = f.get("prior_fix")
    if isinstance(prior, dict):
        treated = "treated a symptom" if prior.get("treated_symptom") else "did not treat a symptom"
        rows.append(f"Earlier fix {', '.join(prior.get('commits') or [])} {treated}: {prior.get('why_back', '')}")
    return "\n".join(rows)


def render_do_not_fix_by(f):
    entries = f.get("do_not_fix_by")
    return "\n".join(f"- {e}" for e in entries) if isinstance(entries, list) and entries else "not recorded"


def cmd_group(args):
    root = Root(args.root)
    groups = group_by_root_cause(root.findings())
    if not groups:
        print("group: no findings")
        return 0
    for g in groups:
        print(f"root cause {g['root_cause']} ({g['repo']}): {', '.join(g['findings'])}")
        for s in g["symptoms"]:
            print(f"  symptom at {s}")
    shared = sum(1 for g in groups if len(g["findings"]) > 1)
    print(f"group: {len(groups)} root causes, {shared} shared by more than one finding")
    return 0


def register(sub):
    p = sub.add_parser("group", help="group the accepted findings by the place of their root cause")
    p.set_defaults(func=cmd_group)
