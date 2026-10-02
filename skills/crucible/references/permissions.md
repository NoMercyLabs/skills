# Permissions

Nothing outward happens without a yes. The interview (`interview.md`) and the permission plan below are both finished before the first reader runs. The user can then walk away: the run never stops to ask something it could have asked at the start.

## Say this first

Before the first interview question, and again at the top of the plan, say in plain words where data goes:

- The code the readers and verifiers read is sent to the **model provider** that runs the agents. Name the provider. This applies to every file in scope.
- Issue and advisory text goes to the tracker. Issues on a public repo are public. Security advisories stay private drafts.
- Memory writes to Grimoira stay on this machine.
- Knowledge sources are read only, and what is fetched lands in the audit folder first.
- Live checks contact the named targets and nothing else.

If the user does not accept the first point, stop. Do not read a file.

## The plan

`crucible plan` lists every group with its bounds, its cost and where its data goes. Show the whole plan. Then ask for one explicit yes or no per group. A group is never granted by silence, by a yes to a different group, or by the interview answers.

| Group | Bounds the plan states |
| --- | --- |
| `local_reads` | the repos and folders in scope; always needed |
| `agent_runs` | number of readers and verifiers, model tier per role, estimated tokens, the hard cap |
| `installs` | the memory plugin (the user runs its commands); anything else the setup needs, named |
| `memory_writes` | which Grimoira instance, which kinds of record |
| `tracker_board` | create or map the board and its fields |
| `tracker_labels` | create labels (named) |
| `tracker_issues` | create issues (maximum count, which repos) |
| `tracker_advisories` | draft advisories (which repos) |
| `tracker_assignees` | assignees (named) |
| `tracker_comments` | comments on existing issues |
| `live_checks` | each target and each command, read-only |
| `publish_report` | the final report anywhere outside the audit folder |
| `blocker_fixes` | which blockers, how a fix lands, which systems may change live (see `blockers.md`) |
| `knowledge_sources` | each named source, read-only, and where its text is written |

Filing never puts a private finding in a public place: `crucible visibility list` shows what the user confirmed, and `file --apply` reads each repo's visibility again before every write.

## Commands

```sh
python scripts/crucible.py --root ROOT plan
python scripts/crucible.py --root ROOT grant GROUP yes|no [--words "the user's words"] [--bound key=value ...]
python scripts/crucible.py --root ROOT grant GROUP yes --reopen --words "the user's words"
python scripts/crucible.py --root ROOT approve PLAN_HASH
python scripts/crucible.py --root ROOT report
python scripts/crucible.py --root ROOT answer KEY VALUE [--words "the user's words"]
python scripts/crucible.py --root ROOT next
```

- `grant GROUP yes|no` records `{answer, words, bounds, at}` in `config.permissions[GROUP]`. `--words` is the user's own text; never write it for them. `--bound key=value` is repeatable. Bound keys: `repos`, `max_count`, `labels`, `assignees`, `instance`, `kinds`, `sources`, `targets`, `commands`, `mode`.
- A `no` is final. A later `grant GROUP yes` is refused unless `--reopen` is given together with the user's own `--words`. Do not ask again in another form, and do not look for another action that reaches the same result.
- `approve PLAN_HASH` records the user's go for exactly that plan. A changed plan has a new hash and needs a new approval.
- `answer` and `next` are the interview commands (see `interview.md`).
- `confirm` refuses until every group has an answer, and also until the memory, filing and blocker-fix choices are answered. Its message lists what is missing.

## Bounds

The engine enforces the bounds. Every outward action (tracker, memory, install, live check, publish, knowledge fetch, blocker fix) goes through one gate that checks its grant first. It refuses when the group is unanswered or `no`, when a requested list is not a subset of the granted list (a repo not listed, a label not named, a new assignee), and when the requested count is above `max_count`. A refusal is logged with status `refused`. The run stops and reports it. It never extends a grant by itself. A wider grant is a new question to the user.

## Filing: one more question, asked at the start

This is the `auto_file` answer (interview, question 10b).

- **No (the default).** The dry-run list is shown. `file --apply` is refused until the user has seen it and the agent runs `crucible approve PLAN_HASH` for that exact plan.
- **Yes.** `file --apply` runs within the granted bounds without asking again.

In both cases `file --apply` needs a prior `file --dry-run` of the same plan hash, and filing stops at the bounds.

## The action log

Every outward action is written to `ROOT/actions.log`, one JSON line each: `at`, `group`, `command`, `result`, `status`. Status is `ok`, `refused`, `skipped` or `failed`. Secrets are masked. The engine writes the log itself, and checks it is writable before it acts. An action that cannot be logged is not taken. Do not write an entry by hand and do not edit the log.

## Backups

Backups are on by default (`config.backups`, interview question 10d). Before any change that can lose data (a file, a tracker board or field, a config, a memory store, a running system's setting) the engine copies the old state to `config.backups.path`, or to `ROOT/backups/<timestamp>-<label>`, and logs where. If a backup is enabled and the copy fails, the change is not made. The user can choose the place, and turning backups off is their choice, recorded in the config.

## Before each phase

Say what happens next, how long it should take, and how many tokens it should cost. Then do it. The phases: inventory, reading, verification, acceptance, filing.

## The final report

`crucible report` prints:

- every action taken, from the log;
- every action refused or skipped, each with its reason;
- coverage as N of M;
- tokens spent against the cap;
- knowledge sources absorbed, and sources named but not absorbed.

Nothing happened that the report does not show. Run `crucible report` and paste its output; do not write the report from memory.

## Limits, said plainly

State these in the report, in these terms:

- What the audit did not read: every file outside scope, every file skipped with its reason, every unit not done.
- What it could not check: behaviour of running systems when live checks were off, and anything a finding lists under `not_checked`.
- Findings are verified by a second agent, not by a human. A reader and a verifier can both be wrong. The user decides what to fix.
