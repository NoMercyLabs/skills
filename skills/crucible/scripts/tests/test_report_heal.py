import unittest

from cruciblelib import heal
from cruciblelib.common import Root

from .helpers import CrucibleCase, run

UNIT = "svc-u01"


class ReportHealTests(CrucibleCase):
    def test_heal_record_in_report(self):
        path = self.make_inventoried({"a.py": "x = 1\n" * 40})
        facts = {"exit_code": 0, "output": "done", "schema_ok": False, "truncated": False, "tool_calls": 3}
        heal.recover(Root(path), UNIT, facts, lambda unit, **opts: {"ok": True})
        code, out, err = run(path, "report")
        self.assertEqual(code, 0, out + err)
        section = out[out.index("healed:"):].splitlines()
        self.assertEqual(section[0], "healed: 1")
        self.assertEqual(section[1], f"  schema_missing {UNIT} try 1: healed")


if __name__ == "__main__":
    unittest.main()
