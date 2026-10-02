import copy
import os

from cruciblelib import blockers, board
from cruciblelib.common import Root

from .helpers import CrucibleCase, good_finding

FILES = {"app.py": "import os\nTOKEN_PATH = os.environ['X']\nrun(query)\n" + "pass\n" * 60}


def finding(fid, cause_line, goal=3, severity="medium"):
    f = copy.deepcopy(good_finding(id=fid, goal=goal, severity=severity))
    f["chain"]["root_cause"]["ref"] = f"app.py:{cause_line}"
    f["chain"]["symptom"]["ref"] = f"app.py:{cause_line + 1}"
    return f


class BoardCase(CrucibleCase):
    def make_board(self, findings, config=None, blocker=False):
        root = self.make_inventoried(FILES, config=config)
        for f in findings:
            self.write(root, f"findings/{f['id']}.json", f)
        self.write(root, "graph.json", {"repos": ["svc"], "edges": []})
        if blocker:
            blockers.add(Root(root), "the build does not start", "")
        return Root(root)

    def test_area_values_cite_the_system_map(self):
        root = self.make_board([finding("F-001", 2)])
        areas = board.build_board(root)["areas"]
        self.assertTrue(areas)
        units = {u: root.unit(u) for u in root.units()}
        repo_paths = {r["path"] for r in root.config()["repos"]}
        for area in areas:
            self.assertTrue(area["source"], area)
            if area["kind"] == "repo":
                self.assertIn(area["source"], repo_paths)
            else:
                repo, _, rel = area["source"].partition("/")
                self.assertIn(rel, units[area["name"]]["files"])
                self.assertEqual(repo, units[area["name"]]["repo"])
        self.assertIn("svc", {a["name"] for a in areas})
        self.assertIn("svc-u01", {a["name"] for a in areas})

    def test_stage_has_reason_per_finding(self):
        findings = [finding("F-001", 2), finding("F-002", 2), finding("F-003", 40, goal=1)]
        result = board.build_board(self.make_board(findings))
        self.assertEqual(sorted(result["items"]), ["F-001", "F-002", "F-003"])
        names = [s["name"] for s in result["stages"]]
        for item in result["items"].values():
            self.assertTrue(item["reason"].strip())
            self.assertIn(item["stage"], names)
        self.assertEqual(result["items"]["F-003"]["reason"], "goal 1: users can use the product without help")
        self.assertEqual(result["items"]["F-001"]["reason"], "blocks 2 findings in svc")

    def test_blockers_and_unblocking_causes_staged_first(self):
        findings = [finding("F-001", 40, goal=1), finding("F-002", 2), finding("F-003", 2)]
        result = board.build_board(self.make_board(findings, blocker=True))
        names = [s["name"] for s in result["stages"]]
        self.assertEqual(result["stages"][0]["blockers"], ["B-001"])
        shared = names.index(result["items"]["F-002"]["stage"])
        single = names.index(result["items"]["F-001"]["stage"])
        self.assertGreater(shared, 0)
        self.assertLess(shared, single)
        self.assertEqual(result["items"]["F-002"]["stage"], result["items"]["F-003"]["stage"])

    def test_priority_and_severity_follow_goal_order_and_finding(self):
        findings = [finding("F-001", 2, goal=2, severity="high")]
        item = board.build_board(self.make_board(findings))["items"]["F-001"]
        self.assertEqual((item["severity"], item["priority"]), ("high", 2))

    def test_roadmap_stages_mapped_when_given(self):
        findings = [finding("F-001", 2), finding("F-002", 2), finding("F-003", 40, goal=1)]
        result = board.build_board(self.make_board(findings, config={"stages": ["Alpha", "Beta"]}))
        self.assertEqual([s["name"] for s in result["stages"]], ["Alpha", "Beta"])
        self.assertEqual(result["items"]["F-001"]["stage"], "Alpha")
        self.assertEqual(result["items"]["F-003"]["stage"], "Beta")
        self.assertTrue(result["mapping"])
        for row in result["mapping"]:
            self.assertIn(row["roadmap"], ("Alpha", "Beta"))
            self.assertTrue(row["generated"])
