"""The board plan, built from stored data only: areas from the system map and inventory units, stages from the
user's goals, blockers and root-cause groups, severity and priority per finding. No tracker is called here."""
from . import blockers, rootcause
from .common import read_json

BLOCKERS_STAGE = "Blockers"
CAUSES_STAGE = "Root causes that unblock other findings"


def build_areas(root, cfg):
    """One area per repo of the system map and per inventory unit, each with the folder or file it came from."""
    paths = {r["name"]: r["path"] for r in cfg.get("repos", [])}
    graph = read_json(root.p("graph.json"), {"repos": [], "edges": []})
    areas = [{"name": name, "kind": "repo", "source": paths.get(name) or "graph.json"}
             for name in sorted(set(paths) | set(graph["repos"]))]
    for name in root.units():
        unit = root.unit(name)
        if unit["files"]:
            areas.append({"name": name, "kind": "unit", "source": f"{unit['repo']}/{unit['files'][0]}"})
    return areas


def goal_rank(cfg, goal):
    for rank, g in enumerate(cfg["goals"], 1):
        if g["id"] == goal:
            return rank
    return len(cfg["goals"]) + 1


def generated_stages(root, cfg, findings):
    """The ordered stages: blockers, then causes shared by several findings, then one stage per goal."""
    stages, reasons = [], {}
    open_blockers = [b["id"] for b in blockers.load(root) if b["status"] == "open"]
    if open_blockers:
        stages.append({"name": BLOCKERS_STAGE, "blockers": open_blockers, "findings": []})
    shared = [g for g in rootcause.group_by_root_cause(findings) if len(g["findings"]) > 1]
    shared.sort(key=lambda g: (-len(g["findings"]), g["findings"]))
    if shared:
        stages.append({"name": CAUSES_STAGE, "blockers": [], "findings": []})
    for group in shared:
        for fid in group["findings"]:
            stages[-1]["findings"].append(fid)
            reasons[fid] = (CAUSES_STAGE, f"blocks {len(group['findings'])} findings in {group['repo']}")
    for goal in sorted(cfg["goals"], key=lambda g: goal_rank(cfg, g["id"])):
        ids = [fid for fid, f in sorted(findings.items()) if f["goal"] == goal["id"] and fid not in reasons]
        if ids:
            name = f"Goal {goal_rank(cfg, goal['id'])}: {goal['name']}"
            stages.append({"name": name, "blockers": [], "findings": ids})
            for fid in ids:
                reasons[fid] = (name, f"goal {goal_rank(cfg, goal['id'])}: {goal['name']}")
    return stages, reasons


def map_to_roadmap(stages, reasons, roadmap):
    """Put the generated stages onto the user's stage names by order; every mapping is recorded."""
    last = len(roadmap) - 1
    mapping = [{"generated": s["name"], "roadmap": roadmap[min(i, last)],
                "why": f"generated stage {i + 1} of {len(stages)} onto the roadmap by order"}
               for i, s in enumerate(stages)]
    target = {m["generated"]: m["roadmap"] for m in mapping}
    mapped = [{"name": name, "blockers": [], "findings": []} for name in roadmap]
    for s in stages:
        home = mapped[roadmap.index(target[s["name"]])]
        home["blockers"] += s["blockers"]
        home["findings"] += s["findings"]
    return mapped, {fid: (target[stage], reason) for fid, (stage, reason) in reasons.items()}, mapping


def build_board(root, cfg=None, findings=None):
    """-> {areas, stages, mapping, items}; items is by finding id: stage, reason, severity, priority."""
    cfg = cfg or root.config()
    findings = root.findings() if findings is None else findings
    stages, reasons = generated_stages(root, cfg, findings)
    mapping = []
    if cfg.get("stages"):
        stages, reasons, mapping = map_to_roadmap(stages, reasons, cfg["stages"])
    items = {fid: {"stage": reasons[fid][0], "reason": reasons[fid][1], "severity": f["severity"],
                   "priority": goal_rank(cfg, f["goal"])} for fid, f in sorted(findings.items())}
    return {"areas": build_areas(root, cfg), "stages": stages, "mapping": mapping, "items": items}
