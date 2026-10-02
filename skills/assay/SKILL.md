---
name: assay
description: >-
  A script-accepted audit of a whole software system: read every file of every repo, find real defects, verify each one with a second agent, and file the survivors in an issue tracker. Use this skill whenever the user asks to audit, review, sweep or "find every problem in" a codebase, a full-stack system or a set of repos, wants a bug backlog or a security review with coverage proof, or says "audit this", "find all the defects", "100% audit", "what is wrong with this system", "build me an issue board from the code". It asks the user everything before acting and refuses to run until the user confirms. Do not use it for a review of one diff or one pull request, or for fixing code.
license: MIT
compatibility: >-
  Needs Python 3.10 or newer (standard library only) and a harness that can dispatch
  subagents with a model per role. The GitHub tracker adapter needs the gh CLI.
  Tested in Claude Code.
metadata:
  author: NoMercy Labs
  version: "0.1.0"
  homepage: https://github.com/NoMercyLabs/skills/tree/main/skills/assay
---

# Assay

An assay tests a material for what it really contains. This skill tests a system the same way: every file is read, every claim is checked by a second reader, and a script, not an agent's report, accepts each step.

Check the engine first. One command proves it works on a sample system with known defects:

```sh
python scripts/assay.py selftest --replay
```

It must end with a pass line. If it does not, stop and report the output. Do not audit with a broken engine.

## Say what an audit is, first

Before the first question, tell the user in plain words:

- An audit reads every file in the chosen repos, in order, with agents that read and agents that check them.
- It writes only into its own folder (`ROOT`) until the user grants more. It files issues only where the user says.
- The code the agents read is sent to the model provider that runs them. That is every file in scope.
- It costs tokens, and the user sets a cap. It takes a while and can be resumed.

Then start the interview. Every question and every permission comes first: the interview, then `assay plan` and the grants, then `confirm`. The run never stops later to ask what it could have asked here.

Paths below are relative to this skill's folder. `ROOT` is the audit folder (default `./assay-audit`), given to every command as `--root ROOT`.

## The interview is mandatory, and the engine enforces it

Nothing is read, inventoried or filed until the user has answered. `assay init` detects facts by script and writes `ROOT/config.json` with `confirmed: false`. Every other command refuses to run while it is false, with the message `config not confirmed: ask the user the interview questions (references/interview.md), then run assay confirm`. `confirm` also refuses while the memory choice (question 11) is unset.

Procedure:

1. Run `python scripts/assay.py --root ROOT init --repo PATH [--repo PATH ...]`. It prints what it detected: remotes, languages and lines per repo, CI files, suggested skips.
2. Open `references/interview.md`. Ask its 11 questions **one at a time**. Show the default with each. Never answer for the user, never batch two questions, never skip one because the answer looks obvious.
3. Write each answer into `ROOT/config.json` at the key named in that file.
4. Run `python scripts/assay.py --root ROOT summary`. Show the whole output to the user.
5. Run `python scripts/assay.py --root ROOT plan`. It lists every action the run can take, in seven groups, with bounds and cost. Show it. Ask for one yes or no per group and record each with `assay grant GROUP yes|no`. A no is final. Ask the filing question too: show the dry run and wait for a go (default), or file within the granted bounds. `references/permissions.md` has the groups, the data-flow statement and the rules.
6. When the user says yes to the summary and every group has an answer, run `python scripts/assay.py --root ROOT confirm`. It refuses while any group or the memory choice is unanswered. A change after that goes back through `summary`, `plan` and a new yes.

## The pipeline

Run in this order. Each command ends in a file on disk. Commands marked "refuses" exit non-zero and print why.

| Step | Command | Refuses when |
| --- | --- | --- |
| 1 | `assay inventory` (add `--delta OLD_COVERAGE` on a re-audit) | config not confirmed |
| 2 | `assay estimate`: units, lines, tokens per tier. Show it; the user's cap from question 8 applies | config not confirmed |
| 3 | Reader agent per unit (`agents/reader.md`). Reads through `show`, writes `ledger/UNIT.json` and `candidates/UNIT.json` | |
| 4 | `assay proof UNIT TRANSCRIPT` | a file of the unit was not shown whole in the reader's transcript, a stamp does not match, a skip has no reason, there is no leads list |
| 5 | Verifier agent per unit (`agents/verifier.md`), a different agent. Writes `review/verdicts-UNIT.json` | |
| 6 | `assay verdict-check UNIT` | a candidate or a dropped lead has no verdict, or a verdict quotes a line that does not exist |
| 7 | `assay accept UNIT` | the finding gate fails, or proof or verdicts are missing |
| 8 | `assay split UNIT` when a unit is too big for one reader | |
| 9 | `assay gate` | a field is empty, evidence does not match the real line, a privacy word or a key-like string is present |
| 10 | `assay status` | never refuses; it prints coverage N of M, findings by goal, tokens spent against the cap |
| 11 | `assay file --dry-run`, then (if the user chose to wait for a go) `assay approve PLAN_HASH`, then `assay file --apply`, then `assay file --verify` | `--apply` without a dry run of the same plan, without approval when it is required, outside the granted bounds, or config not confirmed |
| 12 | `assay report` | |

`assay X` in this file means `python scripts/assay.py --root ROOT X`. Run `python scripts/assay.py --help` for the commands the installed engine has. Never replace a missing command with a hand step: report it.

The engine splits a repo into units of at most 90 KB of whole files, so one reader can hold a unit. The reader shows each file with `python scripts/assay.py --root ROOT show UNIT FILE [--page N]`, never piped or filtered. The stamp on each block is a keyed hash. The key lives in `ROOT/private/key` and no command prints it. A reader cannot fake a read.

Rules for the main session while the pipeline runs:

- Dispatch readers in small batches. Check the pace and the user's token cap from `assay status` before each batch.
- Accept a unit only after `proof`, `verdict-check` and `accept` all pass. A reader's report, a verifier's report and your own opinion are not acceptance.
- The reader and the verifier of a unit are different agents. The verifier never sees the reader's report.
- A unit with any file unread is `partial`, never `done`. Resume it; do not round it up.
- Report coverage only as "N of M" from `assay status`. "Found nothing" without the ledger is not a result.

## Method rules

`references/method.md` holds the nine rules for how to treat an issue: no guesses, cause before symptom, siblings, research before the fix, a failing test first, done means proven on every instance, facts from scripts, coverage as N of M, and a correction is a process defect. Each rule names its script check, or says "prose only". Every reader, verifier and filed issue carries them. Read the file before the first reader is dispatched.

## Model roles

Name roles, not products. The config key `models` maps each role to a tier; question 9 of the interview sets it.

| Role | Tier | Default job | Claude mapping |
| --- | --- | --- | --- |
| strong | highest reasoning | cross-unit judgment, splitting disputes, final review of contested findings | Opus |
| balanced | mid | readers and verifiers | Sonnet |
| fast | cheapest | checks, counting, scouting, formatting | Haiku |

In another harness, map the three tiers to its nearest models. Never put the verifier on a cheaper tier than the reader.

## Guarantees, not promises

A rule in a prompt is a promise, and a broken promise costs nothing. Each phase ends in a file on disk and in a command that can reject the work.

| Phase | File on disk | Command that can reject it |
| --- | --- | --- |
| Interview | `config.json` | every command, until `confirm` |
| Read | `ledger/UNIT.json`, `candidates/UNIT.json` | `proof` |
| Verify | `review/verdicts-UNIT.json` | `verdict-check` |
| Accept | `findings/F-NNNN.json` | `gate`, `accept` |
| Coverage | `coverage.json`, `state.json` | `status` |
| File | the tracker, read back | `file --verify` |

`references/finding-schema.md` has the finding fields and the verdict shape. `references/memory.md` says what goes into permanent memory and when. `references/permissions.md` has the permission plan.

Every outward action is written to `ROOT/actions.log` by the engine, and an action that cannot be logged is not taken. Before each phase, say what happens next and what it should cost.

The final report is the output of `assay report`, pasted. It lists every action taken, every action refused or skipped with its reason, coverage N of M, and tokens spent against the cap. It also says what was not read, what could not be checked, and that findings were verified by a second agent, not by a human.

A phase that did not run has not passed. Never say a unit, a repo or the audit is done without the command output that shows it.

## Portability rule

This skill is generic. Every example in it comes from constructs that exist in every codebase: a request handler, a config file, a deploy script, a worker. No file here may name the project, product or company the skill was developed in, beyond the publisher lines and the install commands for the memory plugin. `scripts/test_portability.py` checks this and must pass before any change to the skill is committed. A product-specific rule (a list of keys that are public on purpose, a house style) belongs in the user's own `scope` and `goals` config, never in this skill.
