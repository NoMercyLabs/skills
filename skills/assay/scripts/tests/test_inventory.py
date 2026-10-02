import json
import os
import re
import unittest

from .helpers import AssayCase, run


def load(root, *parts):
    with open(os.path.join(root, *parts), encoding="utf-8") as fh:
        return json.load(fh)


class InventoryTests(AssayCase):
    def test_inventory_excludes_expected_json_and_notes(self):
        root = self.make_inventoried({
            "app.py": "x = 1\n",
            "EXPECTED.json": "[]",
            "EXPECTED-extra.txt": "hidden",
            "NOTES.md": "private notes",
        })
        files = load(root, "units", "svc-u01.json")["files"]
        self.assertEqual(files, ["app.py"])

    def test_inventory_skips_binary_vendored_and_configured_skip(self):
        root = self.make_inventoried({
            "app.py": "x = 1\n",
            "logo.bin": b"\x00\x01\x02binary",
            "node_modules/dep/index.js": "module.exports = 1;\n",
            "vendor/lib.py": "y = 2\n",
            ".git/config": "[core]\n",
            "gen/out.py": "z = 3\n",
            "keep/mod.py": "w = 4\n",
        }, config={"scope": {"include": [], "skip": ["gen"]}})
        files = load(root, "units", "svc-u01.json")["files"]
        self.assertEqual(files, ["app.py", "keep/mod.py"])

    def test_big_file_own_unit(self):
        root = self.make_inventoried({
            "a.py": "a = 1\n",
            "big.txt": "line of text\n" * 40,
            "z.py": "z = 1\n",
        }, config={"unit_bytes": 200})
        units = {}
        for name in sorted(os.listdir(os.path.join(root, "units"))):
            units[name] = load(root, "units", name)["files"]
        self.assertIn(["big.txt"], units.values())
        self.assertEqual(len(units), 3)

    def test_inventory_packs_whole_files_under_the_cap(self):
        body = "x" * 59 + "\n"
        root = self.make_inventoried({"a.txt": body, "b.txt": body, "c.txt": body, "d.txt": body},
                                     config={"unit_bytes": 130})
        sizes = [len(load(root, "units", n)["files"]) for n in sorted(os.listdir(os.path.join(root, "units")))]
        self.assertEqual(sizes, [2, 2])

    def test_inventory_writes_snapshot_units_and_pending_state(self):
        root = self.make_inventoried({"src/app.py": "a = 1\nb = 2\n"})
        unit = load(root, "units", "svc-u01.json")
        self.assertEqual(unit["unit"], "svc-u01")
        self.assertEqual(unit["repo"], "svc")
        self.assertEqual(unit["lines"], 2)
        self.assertIsNone(unit["parent"])
        self.assertTrue(os.path.isfile(os.path.join(root, "snapshot", "svc", "src", "app.py")))
        state = load(root, "state.json")
        self.assertEqual(state["units"]["svc-u01"]["status"], "pending")
        self.assertEqual(state["tokens_spent"], 0)

    def test_reinventory_refused_once_a_unit_has_progress(self):
        root = self.make_inventoried({"app.py": "x = 1\n"})
        state = load(root, "state.json")
        state["units"]["svc-u01"]["status"] = "done"
        with open(os.path.join(root, "state.json"), "w", encoding="utf-8") as fh:
            json.dump(state, fh)
        code, out, err = run(root, "inventory")
        self.assertEqual(code, 1)
        self.assertIn("progress", err)

    def test_estimate_prints_units_lines_and_tokens(self):
        root = self.make_inventoried({"a.py": "1\n2\n3\n4\n5\n6\n7\n8\n9\n10\n"})
        code, out, err = run(root, "estimate")
        self.assertEqual(code, 0, err)
        self.assertIn("units: 1", out)
        self.assertIn("lines: 10", out)
        self.assertIn("reader tokens: 290", out)
        self.assertIn("verifier tokens: 44", out)
        self.assertIn("tokens: 334", out)
        self.assertIn("balanced", out)


class ShowTests(AssayCase):
    def test_show_stamp_format(self):
        root = self.make_inventoried({"app.py": "alpha\nbeta\n"})
        code, out, err = run(root, "show", "svc-u01", "app.py")
        self.assertEqual(code, 0, err)
        lines = out.split("\n")
        self.assertRegex(lines[0], r"^=== app\.py [0-9a-f]{10} 1-2/2 ===$")
        self.assertEqual(lines[1], "    1| alpha")
        self.assertEqual(lines[2], "    2| beta")
        self.assertEqual(lines[3], "=== END app.py ===")
        self.assertNotIn("NEXT", out)

    def test_show_stamp_is_the_keyed_hmac_of_the_body(self):
        from assaylib import common
        root = self.make_inventoried({"app.py": "alpha\nbeta\n"})
        code, out, err = run(root, "show", "svc-u01", "app.py")
        key = common.Root(root).key()
        expected = common.stamp(key, "app.py", 1, 2, 2, "    1| alpha\n    2| beta")
        self.assertIn("=== app.py %s 1-2/2 ===" % expected, out)

    def test_show_refuses_a_file_not_in_the_unit(self):
        root = self.make_inventoried({"app.py": "alpha\n", "EXPECTED.json": "[]"})
        code, out, err = run(root, "show", "svc-u01", "EXPECTED.json")
        self.assertEqual(code, 1)
        self.assertIn("not in unit", err)
        self.assertEqual(out, "")

    def test_show_refuses_an_unknown_unit(self):
        root = self.make_inventoried({"app.py": "alpha\n"})
        code, out, err = run(root, "show", "svc-u09", "app.py")
        self.assertEqual(code, 1)
        self.assertIn("unknown unit", err)

    def test_show_pages_a_long_file_and_points_to_the_next_page(self):
        text = "".join("%04d %s\n" % (i, "w" * 90) for i in range(1, 801))
        root = self.make_inventoried({"long.txt": text}, config={"unit_bytes": 10 ** 7})
        code, out, err = run(root, "show", "svc-u01", "long.txt")
        self.assertEqual(code, 0, err)
        self.assertRegex(out.split("\n")[0], r"^=== long\.txt [0-9a-f]{10} 1-\d+/800 ===$")
        self.assertIn("=== NEXT: show svc-u01 long.txt --page 2 ===", out)
        code, out2, err = run(root, "show", "svc-u01", "long.txt", "--page", "2")
        self.assertEqual(code, 0, err)
        start = int(re.search(r" (\d+)-\d+/800 ===", out2).group(1))
        self.assertGreater(start, 1)

    def test_show_page_out_of_range_refused(self):
        root = self.make_inventoried({"app.py": "alpha\n"})
        code, out, err = run(root, "show", "svc-u01", "app.py", "--page", "3")
        self.assertEqual(code, 1)
        self.assertIn("page 3 of 1", err)


if __name__ == "__main__":
    unittest.main()
