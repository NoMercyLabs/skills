# Method rules

Nine rules for how an audit treats a problem. Readers and verifiers are briefed on them, and every filed issue carries them. Each rule names its enforcement. "Prose only" means no script can check it, so the main session holds the line.

## 1. No confident guess

A cause, a data shape, a count or a behaviour not opened this session is a hypothesis. Label it `not checked`.

- **Enforcement**: script. The gate refuses `why.verified: true` unless an evidence quote matches the real line in the snapshot. An unverified cause needs a `not_checked` entry starting `cause:`.
- **Example**: a request handler builds a query from `req.params.id`. "The column is an integer" is a guess until the schema file is opened. Write `cause: column type not checked`.

## 2. Cause, not symptom

A finding names the root cause, not only where it shows.

- **Enforcement**: partly script. The schema keeps `why.cause` separate from `what.summary`. The verifier rejects or fixes a `why` that only repeats `what`.
- **Example**: "the worker crashes on a null payload" is the symptom. "The queue accepts messages with no schema check, so every consumer must guard" is the cause.

## 3. Every instance has siblings

The same pattern elsewhere is part of the finding.

- **Enforcement**: script. The gate refuses a finding with an empty `siblings` list. Allowed text: paths, or `searched: <query>, 0 more`.
- **Example**: one deploy script runs `rm -rf $DIR/` with `DIR` unset. Search every shell script for the same unguarded expansion and list the hits.

## 4. Research before the fix

Every filed issue carries a "Before you fix" block: current behaviour, every caller, every consumer or mirror, earlier fixes of the same code from git history, and the live instances the fix must reach.

- **Enforcement**: script. `before_you_fix` is a required finding field, and `file --verify` checks the block exists in the filed issue. "not checked" is allowed text.
- **Example**: before changing a config parser's default, list who reads the key, which environments set it, and the last commit that touched the line.

## 5. A test fails first

The issue's acceptance says: write a test that fails on the unchanged code, then make the edit.

- **Enforcement**: prose only. The issue template carries the sentence. The skill does not fix code.
- **Example**: for the query built from a request parameter, the test sends `1; DROP TABLE x` and fails until the query is parameterized.

## 6. Done means the goal is reached and the blast radius is proven

A fix is done when it works on every running instance (production, staging, development), not when the words of the request are satisfied.

- **Enforcement**: partly script. `repos[].instances` in the config lists the instances, and the filed issue lists them. Whether each was proven is prose only.
- **Example**: a config fix applied to production and not to staging leaves staging open. The issue lists both and asks for the same proof on each.

## 7. Facts come from scripts, and agent output is accepted by a script

An agent's report is never the evidence. A file's existence, a count, a line's text come from a command.

- **Enforcement**: script. The whole pipeline: `proof`, `verdict-check`, `gate`, `file --verify`.
- **Example**: a reader says it read all 40 files. `proof` recomputes the keyed stamp of each block in its transcript and says 38 of 40.

## 8. Coverage is N of M from the ledger

"Found nothing" is a result only with the ledger that shows what was read.

- **Enforcement**: script. `status` prints N of M from `state.json` and `coverage.json`; split parents are not counted.
- **Example**: "no injection found in the API" is reported as "no injection found in 212 of 212 files in scope", or it is not reported.

## 9. A correction is a process defect

When the user corrects the audit, fix the check or rule that let the mistake through, with a test. Fixing only the one finding is the surface fix.

- **Enforcement**: prose, plus a regression test per engine defect in `scripts/tests/`.
- **Example**: the user says a finding about a hard-coded test credential is not real. Fix that finding, then add the rule to scope and goals so no later reader reports the same class, and record the correction as a memory rule.
