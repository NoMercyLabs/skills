# Permissions

Nothing outward happens without a yes. The interview (`interview.md`) and the permission plan below are both finished before the first reader runs. The user can then walk away: the run never stops to ask something it could have asked at the start.

## Say this first

Before the first interview question, and again at the top of the plan, say in plain words where data goes:

- The code the readers and verifiers read is sent to the **model provider** that runs the agents. Name the provider. This applies to every file in scope.
- Issue and advisory text goes to the tracker. Issues on a public repo are public. Security advisories stay private drafts.
- Memory writes to Grimoira stay on this machine.
- Live checks contact the named targets and nothing else.

If the user does not accept the first point, stop. Do not read a file.

## The plan

`assay plan` lists every action the run can take, in seven groups, each with its bounds and cost. Show the whole plan. Then ask for one explicit yes or no per group. A group is never granted by silence, by a yes to a different group, or by the interview answers.

| # | Group | Bounds the plan states |
| --- | --- | --- |
| 1 | Local reads | the repos and folders in scope; always needed |
| 2 | Agent runs | number of readers and verifiers, model tier per role, estimated tokens, the hard cap |
| 3 | Installs | the memory plugin (the user runs its commands); anything else the setup needs, named |
| 4 | Memory writes | which Grimoira instance, which kinds of record |
| 5 | Tracker writes | each of these is a separate grant: create or map the board and its fields; create labels (named); create issues (maximum count, which repos); draft advisories (which repos); assignees (named); comments on existing issues |
| 6 | Live checks | each target and each command, read-only |
| 7 | Publishing | the final report anywhere outside the audit folder |

## Grants

```sh
python scripts/assay.py --root ROOT plan
python scripts/assay.py --root ROOT grant GROUP yes
python scripts/assay.py --root ROOT grant GROUP no
python scripts/assay.py --root ROOT approve PLAN_HASH
```

- `grant GROUP yes|no` records the answer in `config.permissions` together with the user's own words. Record the user's own words (run `assay grant --help` for how); never write them yourself.
- `confirm` refuses until every group has an answer.
- A `no` is final. The engine skips that action. Do not ask again in another form, and do not look for a way to reach the same result by another action.
- Bounds are enforced by the engine. Every outward action (tracker, memory, install, live check, publish) checks its grant first and refuses without one. An action outside the bounds (a repo not listed, more issues than granted, a label not named, a new assignee) is refused. The run stops and reports it. It never extends a grant by itself. A wider grant is a new question to the user.

## Filing: one more question, asked at the start

- **Show the full dry run and wait for my go** (the default). `file --apply` is refused until the user has seen the dry run and the agent runs `assay approve PLAN_HASH` for that exact plan. A changed plan has a new hash and needs a new approval.
- **File within the granted bounds without asking again.** The dry run is still written to disk and logged. Filing still stops at the bounds.

Both choices are asked at the start, with the plan, not at the end.

## The action log

Every outward action is written to `ROOT/actions.log`: time, the grant used, the exact command with secrets masked, and the result. The engine writes the log itself. An action that cannot be logged is not taken. Do not write an entry by hand and do not edit the log.

## Before each phase

Say what happens next, how long it should take, and how many tokens it should cost. Then do it. The phases: inventory, reading, verification, acceptance, filing.

## The final report

The report lists:

- every action taken, from the log;
- every action refused or skipped, each with its reason;
- coverage as N of M, from `assay status`;
- tokens spent against the cap.

Nothing happened that the report does not show. Run `assay report` and paste its output; do not write the report from memory.

## Limits, said plainly

State these in the report, in these terms:

- What the audit did not read: every file outside scope, every file skipped with its reason, every unit not done.
- What it could not check: behaviour of running systems when live checks were off, and anything a finding lists under `not_checked`.
- Findings are verified by a second agent, not by a human. A reader and a verifier can both be wrong. The user decides what to fix.
