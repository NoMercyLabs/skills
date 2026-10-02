---
name: crucible
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
  homepage: https://github.com/NoMercyLabs/skills/tree/main/skills/crucible
---

# Crucible

A crucible tests a material for what it really contains. This skill tests a system the same way: every file is read, every claim is checked by a second reader, and a script, not an agent's report, accepts each step.

Check the engine first. One command proves it works on a sample system with known defects:

```sh
python scripts/crucible.py selftest --replay
```

It must end with a pass line. If it does not, stop and report the output. Do not audit with a broken engine.

## Say what an audit is, first

Before the first question, tell the user in plain words:

- An audit reads every file in the chosen repos, in order, with agents that read and agents that check them.
- It writes only into its own folder (`ROOT`) until the user grants more. It files issues only where the user says.
- The code the agents read is sent to the model provider that runs them. That is every file in scope.
- It costs tokens, and the user sets a cap. It takes a while and can be resumed.

Then start the interview. Every question and every permission comes first: the interview, then `crucible plan` and the grants, then `confirm`. The principle: every choice about the user's own system, risk or workflow is a question with the safest default. Product findings are filed, never fixed. Backups of anything that can be lost are on by default. The run never stops later to ask what it could have asked here.

Paths below are relative to this skill's folder. `ROOT` is the audit folder (default `./crucible-audit`), given to every command as `--root ROOT`.

## The interview is mandatory, and the engine enforces it

Nothing is read, inventoried or filed until the user has answered. `crucible init` detects facts by script and writes `ROOT/config.json` with `confirmed: false`. Every other command refuses to run while it is false, with the message `config not confirmed: ask the user the interview questions (references/interview.md), then run crucible confirm`. `confirm` also refuses while the memory, filing or blocker-fix choice or any permission group is unanswered, and lists what is missing.

Procedure:

1. Run `python scripts/crucible.py --root ROOT init --repo PATH [--repo PATH ...]`. It prints what it detected: remotes, languages and lines per repo, CI files, suggested skips.
2. Open `references/interview.md`. Run `crucible next`: it prints the next unanswered key. Ask that question. Ask **one at a time**, show the default with each, never answer for the user, never batch two questions, never skip one because the answer looks obvious.
3. Record each answer with `python scripts/crucible.py --root ROOT answer KEY VALUE --words "the user's words"`. Never edit `ROOT/config.json` by hand. Repeat from step 2 until `next` has no interview key left. The tracker question is followed at once by "May I file the findings there automatically?" (`auto_file`).
4. Run `python scripts/crucible.py --root ROOT summary`. Show the whole output to the user.
5. Run `python scripts/crucible.py --root ROOT plan`. It lists every permission group with bounds, cost and where the data goes. Show it. Ask for one yes or no per group and record each with `crucible grant GROUP yes|no --words "..." [--bound key=value]`. A no is final. `references/permissions.md` has the groups, the flags, the data-flow statement and the rules.
6. When the user says yes to the summary and every group has an answer, run `python scripts/crucible.py --root ROOT confirm`. A change after that goes back through `summary`, `plan` and a new yes.
7. If the user chose Grimoira, run its full onboarding and ask where more knowledge lives outside this machine (`references/interview.md`, question 11; `references/memory.md`).

## The pipeline

Run in this order. Each command ends in a file on disk. Commands marked "refuses" exit non-zero and print why.

| Step | Command | Refuses when |
| --- | --- | --- |
| 1 | `crucible inventory` (add `--delta OLD_COVERAGE` on a re-audit) | config not confirmed |
| 2 | `crucible estimate`: units, lines, tokens per tier. Show it; the user's cap from question 8 applies | config not confirmed |
| 3 | Reader agent per unit (`agents/reader.md`). Reads through `show`, writes `ledger/UNIT.json` and `candidates/UNIT.json` | |
| 4 | `crucible proof UNIT TRANSCRIPT` | a file of the unit was not shown whole in the reader's transcript, a stamp does not match, a skip has no reason, there is no leads list |
| 5 | Verifier agent per unit (`agents/verifier.md`), a different agent. Writes `review/verdicts-UNIT.json` | |
| 6 | `crucible verdict-check UNIT` | a candidate or a dropped lead has no verdict, or a verdict quotes a line that does not exist |
| 7 | `crucible accept UNIT` | the finding gate fails, or proof or verdicts are missing |
| 8 | `crucible split UNIT` when a unit is too big for one reader | |
| 9 | `crucible gate` | a field is empty, evidence does not match the real line, a privacy word or a key-like string is present |
| 10 | `crucible status` | never refuses; it prints coverage N of M, findings by goal, tokens spent against the cap |
| 11 | `crucible file --dry-run`, then (when `auto_file` is false) `crucible approve PLAN_HASH`, then `crucible file --apply`, then `crucible file --verify` | `--apply` without a dry run of the same plan, without approval when it is required, outside the granted bounds, or config not confirmed |
| 12 | `crucible report` | |

Two more command groups run beside the pipeline:/n/n- **Blockers.** When a stage cannot go on: `crucible blocker add DESCRIPTION [--stage S]`, `crucible blocker list`, `crucible fix plan BLOCKER_ID`, `crucible fix run BLOCKER_ID [--yes-words ".."]`. A fix needs the `blocker_fixes` grant, makes a backup first, and re-runs the blocked stage, which must pass. See `references/blockers.md`.
- **Knowledge.** `crucible knowledge fetch SOURCE_NAME` pulls a granted outside source into `ROOT/knowledge/SOURCE_NAME/` as Markdown, to be absorbed by Grimoira's `index-docs --from`. See `references/memory.md`.

For a system of several repos: `crucible layout` says single repo, monorepo or a folder of repos; `crucible related` lists the repos the code points to with file:line; `crucible workspace plan|choose|clone` reads them from your own checkouts or a fresh read-only base folder (`workspace_clones` grant, `references/interview.md` 10e); `crucible graph` writes the edges between repos with file:line evidence and hands each reader the leads of its unit.

`crucible safety` lists the secret files git tracks, by path only; run it at the start and tell the user. `SECURITY.md` lists every file read or written, every network call and every subprocess.

`crucible X` in this file means `python scripts/crucible.py --root ROOT X`. Run `python scripts/crucible.py --help` for the commands the installed engine has. Never replace a missing command with a hand step: report it.

The engine splits a repo into units of at most 90 KB of whole files, so one reader can hold a unit. The reader shows each file with `python scripts/crucible.py --root ROOT show UNIT FILE [--page N]`, never piped or filtered. The stamp on each block is a keyed hash. The key lives in `ROOT/private/key` and no command prints it. A reader cannot fake a read.

Rules for the main session while the pipeline runs:

- Dispatch readers in small batches. Check the pace and the user's token cap from `crucible status` before each batch.
- Accept a unit only after `proof`, `verdict-check` and `accept` all pass. A reader's report, a verifier's report and your own opinion are not acceptance.
- The reader and the verifier of a unit are different agents. The verifier never sees the reader's report.
- A unit with any file unread is `partial`, never `done`. Resume it; do not round it up.
- Report coverage only as "N of M" from `crucible status`. "Found nothing" without the ledger is not a result.

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

`references/finding-schema.md` has the finding fields and the verdict shape. `references/memory.md` says what goes into permanent memory, the Grimoira onboarding and the knowledge flow. `references/permissions.md` has the permission plan, the grant commands, the action log and backups. `references/blockers.md` has the blocker flow.

Every outward action is written to `ROOT/actions.log` by the engine, and an action that cannot be logged is not taken. Before any change that can lose data, the engine makes a backup first. Before each phase, say what happens next and what it should cost.

The final report is the output of `crucible report`, pasted. It lists every action taken, every action refused or skipped with its reason, coverage N of M, and tokens spent against the cap. It also says what was not read, what could not be checked, and that findings were verified by a second agent, not by a human.

A phase that did not run has not passed. Never say a unit, a repo or the audit is done without the command output that shows it.

## Portability rule

This skill is generic. Every example in it comes from constructs that exist in every codebase: a request handler, a config file, a deploy script, a worker. No file here may name the project, product or company the skill was developed in, beyond the publisher lines and the install commands for the memory plugin. `scripts/test_portability.py` checks this and must pass before any change to the skill is committed. A product-specific rule (a list of keys that are public on purpose, a house style) belongs in the user's own `scope` and `goals` config, never in this skill.
