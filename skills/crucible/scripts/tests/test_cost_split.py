import json
import os

from cruciblelib import tokens
from cruciblelib.transcripts import read_usage

from .helpers import CrucibleCase, run
from . import test_tokens

FIELDS = ("input", "cache_write", "cache_read", "output")


def usage_row(path, message_id, usage):
    with open(path, "a", encoding="utf-8") as fh:
        for block in ({"type": "text", "text": "x"}, {"type": "tool_use", "id": message_id, "name": "Read", "input": {}}):
            fh.write(json.dumps({"type": "assistant", "message": {"id": message_id, "content": [block], "usage": usage}}) + "\n")


class CostSplitTests(CrucibleCase):
    setup_audit = test_tokens.TokenTests.setup_audit

    def transcript(self, name):
        path = os.path.join(self.tmp(), name)
        usage_row(path, "m1", {"input_tokens": 3, "cache_creation_input_tokens": 100, "cache_read_input_tokens": 1000,
                               "output_tokens": 10})
        usage_row(path, "m2", {"input_tokens": 4, "cache_creation_input_tokens": 200, "cache_read_input_tokens": 3000,
                               "output_tokens": 20})
        return path

    def test_cost_split_by_usage_field(self):
        usage = read_usage(self.transcript("a.jsonl"))
        self.assertEqual(usage["split"], {"input": 7, "cache_write": 300, "cache_read": 4000, "output": 30})
        self.assertEqual((usage["tokens"], usage["output"], usage["turns"]), (4337, 30, 2))
        root, units = self.setup_audit()
        code, out, err = run(root, "calibrate", "--unit", units[0]["unit"], "--transcript", self.transcript("b.jsonl"))
        self.assertEqual(code, 0, err)
        with open(os.path.join(root, "tokens.json"), encoding="utf-8") as fh:
            record = json.load(fh)["records"][0]
        self.assertEqual(record["split"], usage["split"])
        self.assertEqual(record["tokens"], 4337)
        self.assertIn("cost split: input 7, cache write 300, cache read 4000, output 30, total 4337", out)
        old = {k: v for k, v in record.items() if k != "split"}
        self.assertIsNone(tokens.cost_split([old]))
        found = tokens.cost_split([record, record])
        self.assertEqual({k: found[k] for k in FIELDS}, {k: 2 * v for k, v in usage["split"].items()})
        self.assertEqual(found["total"], sum(found[k] for k in FIELDS))
