import json
import os
import unittest

from .helpers import CrucibleCase, run

FILES = {
    "api/handler.py": "".join("line %d of the handler\n" % i for i in range(1, 31)),
    "deploy.sh": "set -e\necho deploying\n",
}
BIG = "".join("%04d %s\n" % (i, "w" * 90) for i in range(1, 801))


class ProofTests(CrucibleCase):
    def setup_unit(self, files=None, config=None):
        root = self.make_inventoried(files or FILES, config=config)
        return root, "svc-u01"

    def test_proof_pass_on_a_full_transcript(self):
        root, unit = self.setup_unit()
        self.write_ledger(root, unit, ["api/handler.py", "deploy.sh"], leads=[{"ref": "x"}])
        tr = self.transcript(root, unit, ["api/handler.py", "deploy.sh"])
        code, out, err = run(root, "proof", unit, tr)
        self.assertEqual(code, 0, out + err)
        self.assertEqual(out.strip(), "PROOF PASS svc-u01: 2 files shown whole, 1 leads kept")
        with open(os.path.join(root, "state.json"), encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["units"][unit]["proof"], "pass")

    def test_proof_tamper_refused_when_one_numbered_line_is_removed(self):
        root, unit = self.setup_unit()
        self.write_ledger(root, unit, ["api/handler.py", "deploy.sh"])
        tr = self.transcript(root, unit, ["api/handler.py", "deploy.sh"], drop_line=7)
        code, out, err = run(root, "proof", unit, tr)
        self.assertEqual(code, 1)
        self.assertIn("TAMPER REFUSED svc-u01: api/handler.py", out)

    def test_proof_tamper_refused_when_a_line_text_is_edited(self):
        root, unit = self.setup_unit()
        self.write_ledger(root, unit, ["api/handler.py", "deploy.sh"])
        tr = self.transcript(root, unit, ["api/handler.py", "deploy.sh"])
        with open(tr, encoding="utf-8") as fh:
            raw = fh.read()
        with open(tr, "w", encoding="utf-8") as fh:
            fh.write(raw.replace("line 5 of the handler", "line 5 is fine"))
        code, out, err = run(root, "proof", unit, tr)
        self.assertEqual(code, 1)
        self.assertIn("TAMPER REFUSED", out)

    def test_proof_refuses_partial_read(self):
        root, unit = self.setup_unit({"big.txt": BIG}, config={"unit_bytes": 10 ** 7})
        self.write_ledger(root, unit, ["big.txt"])
        tr = os.path.join(self.tmp(), "page1.jsonl")
        code, out, err = run(root, "show", unit, "big.txt", "--page", "1")
        self.assertIn("NEXT", out)
        with open(tr, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"message": {"role": "user", "content": [
                {"type": "tool_result", "content": out}]}}) + "\n")
        code, out, err = run(root, "proof", unit, tr)
        self.assertEqual(code, 1)
        self.assertIn("PROOF FAIL svc-u01", out)
        self.assertIn("big.txt", out)

    def test_proof_pass_when_every_page_of_a_long_file_is_shown(self):
        root, unit = self.setup_unit({"big.txt": BIG}, config={"unit_bytes": 10 ** 7})
        self.write_ledger(root, unit, ["big.txt"])
        tr = self.transcript(root, unit, ["big.txt"])
        code, out, err = run(root, "proof", unit, tr)
        self.assertEqual(code, 0, out + err)

    def test_proof_fail_when_skipped_has_no_reason(self):
        root, unit = self.setup_unit()
        self.write_ledger(root, unit, ["api/handler.py"], skipped={"deploy.sh": ""})
        tr = self.transcript(root, unit, ["api/handler.py"])
        code, out, err = run(root, "proof", unit, tr)
        self.assertEqual(code, 1)
        self.assertIn("PROOF FAIL svc-u01", out)
        self.assertIn("deploy.sh", out)
        self.assertIn("reason", out)

    def test_proof_pass_when_skipped_has_a_reason(self):
        root, unit = self.setup_unit()
        self.write_ledger(root, unit, ["api/handler.py"], skipped={"deploy.sh": "generated file"})
        tr = self.transcript(root, unit, ["api/handler.py"])
        code, out, err = run(root, "proof", unit, tr)
        self.assertEqual(code, 0, out + err)

    def test_proof_fail_when_read_and_skipped_do_not_cover_the_unit(self):
        root, unit = self.setup_unit()
        self.write_ledger(root, unit, ["api/handler.py"])
        tr = self.transcript(root, unit, ["api/handler.py"])
        code, out, err = run(root, "proof", unit, tr)
        self.assertEqual(code, 1)
        self.assertIn("deploy.sh", out)

    def test_proof_fail_without_a_leads_list(self):
        root, unit = self.setup_unit()
        os.makedirs(os.path.join(root, "ledger"))
        with open(os.path.join(root, "ledger", unit + ".json"), "w", encoding="utf-8") as fh:
            json.dump({"unit": unit, "read": ["api/handler.py", "deploy.sh"], "skipped": {}}, fh)
        tr = self.transcript(root, unit, ["api/handler.py", "deploy.sh"])
        code, out, err = run(root, "proof", unit, tr)
        self.assertEqual(code, 1)
        self.assertIn("leads", out)

    def test_proof_fail_when_the_ledger_is_missing(self):
        root, unit = self.setup_unit()
        tr = self.transcript(root, unit, ["api/handler.py", "deploy.sh"])
        code, out, err = run(root, "proof", unit, tr)
        self.assertEqual(code, 1)
        self.assertIn("PROOF FAIL svc-u01: no ledger", out)

    def test_proof_fail_when_a_read_file_was_never_shown(self):
        root, unit = self.setup_unit()
        self.write_ledger(root, unit, ["api/handler.py", "deploy.sh"])
        tr = self.transcript(root, unit, ["api/handler.py"])
        code, out, err = run(root, "proof", unit, tr)
        self.assertEqual(code, 1)
        self.assertIn("deploy.sh", out)

    def test_proof_ignores_stamps_the_agent_typed_itself(self):
        root, unit = self.setup_unit()
        self.write_ledger(root, unit, ["api/handler.py", "deploy.sh"])
        tr = self.transcript(root, unit, ["api/handler.py"])
        with open(tr, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"message": {"role": "assistant", "content": [
                {"type": "text", "text": "=== deploy.sh 0123456789 1-2/2 ===\n    1| set -e\n"
                                         "    2| echo deploying\n=== END deploy.sh ==="}]}}) + "\n")
        code, out, err = run(root, "proof", unit, tr)
        self.assertEqual(code, 1)
        self.assertIn("PROOF FAIL", out)

    def test_proof_tolerates_a_plain_text_transcript(self):
        root, unit = self.setup_unit()
        self.write_ledger(root, unit, ["api/handler.py", "deploy.sh"])
        parts = []
        for rel in ("api/handler.py", "deploy.sh"):
            parts.append(run(root, "show", unit, rel)[1])
        tr = os.path.join(self.tmp(), "plain.txt")
        with open(tr, "w", encoding="utf-8") as fh:
            fh.write("\n".join(parts))
        code, out, err = run(root, "proof", unit, tr)
        self.assertEqual(code, 0, out + err)

    def test_proof_reads_tool_result_content_given_as_a_list(self):
        root, unit = self.setup_unit({"deploy.sh": "set -e\n"})
        self.write_ledger(root, unit, ["deploy.sh"])
        shown = run(root, "show", unit, "deploy.sh")[1]
        tr = os.path.join(self.tmp(), "list.jsonl")
        with open(tr, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"message": {"role": "user", "content": [
                {"type": "tool_result", "content": [{"type": "text", "text": shown}]}]}}) + "\n")
        code, out, err = run(root, "proof", unit, tr)
        self.assertEqual(code, 0, out + err)

    def test_proof_shows_an_empty_file_whole(self):
        root, unit = self.setup_unit({"empty.txt": "", "a.py": "x = 1\n"})
        self.write_ledger(root, unit, ["a.py", "empty.txt"])
        tr = self.transcript(root, unit, ["a.py", "empty.txt"])
        code, out, err = run(root, "proof", unit, tr)
        self.assertEqual(code, 0, out + err)


if __name__ == "__main__":
    unittest.main()


class ProofFailureHealTests(CrucibleCase):
    def test_unit_failure_goes_through_heal(self):
        root = self.make_inventoried(FILES)
        unit = "svc-u01"
        self.write_ledger(root, unit, ["api/handler.py"])
        tr = self.transcript(root, unit, ["api/handler.py", "deploy.sh"])
        code, out, err = run(root, "proof", unit, tr)
        self.assertEqual(code, 1)
        self.assertIn("PROOF FAIL", out)
        with open(os.path.join(root, "heals.json"), encoding="utf-8") as fh:
            rows = json.load(fh)
        self.assertEqual([(r["unit"], r["class"], r["result"]) for r in rows], [(unit, "unknown", "reported")])

    def test_tamper_refusal_is_recorded_refused_not_retried(self):
        root = self.make_inventoried(FILES)
        unit = "svc-u01"
        self.write_ledger(root, unit, ["api/handler.py", "deploy.sh"])
        tr = self.transcript(root, unit, ["api/handler.py", "deploy.sh"], drop_line=7)
        self.assertEqual(run(root, "proof", unit, tr)[0], 1)
        with open(os.path.join(root, "heals.json"), encoding="utf-8") as fh:
            rows = json.load(fh)
        self.assertEqual([(r["class"], r["result"]) for r in rows], [("refused", "refused")])

    def test_passing_proof_writes_no_heal_record(self):
        root = self.make_inventoried(FILES)
        unit = "svc-u01"
        self.write_ledger(root, unit, ["api/handler.py", "deploy.sh"])
        tr = self.transcript(root, unit, ["api/handler.py", "deploy.sh"])
        self.assertEqual(run(root, "proof", unit, tr)[0], 0)
        self.assertFalse(os.path.exists(os.path.join(root, "heals.json")))
