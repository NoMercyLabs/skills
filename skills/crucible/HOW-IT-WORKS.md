# How crucible works

This page is for a new user of the crucible skill.
It says what the skill does, what it asks, what it refuses, and what it costs.
Every number on this page comes from `references/calibration.json`.

## What crucible does

Crucible audits a whole software system.
It reads every file of every repo you put in scope.
Reader agents find possible defects.
A different agent checks each one.
The survivors are filed in an issue tracker.

A script, not an agent's report, accepts each step.
Each step ends in a file on disk.
A command can reject that file.

Crucible only finds and files problems.
It does not fix the product code.
The audit folder (`ROOT`) is the only place it writes until you grant more.
The code the agents read goes to the model provider that runs them.
That is every file in scope.
The audit costs tokens, takes a while, and can be resumed.

## The stages

Run the engine selftest first.
It must end with a pass line.
If it does not, stop and report the output.

Then the pipeline runs in this order.
Each command ends in a file on disk.
Each command can refuse and say why.

1. `inventory` splits the repos into units of whole files.
2. `estimate` shows units, lines and tokens per tier.
3. A reader agent reads each unit through `show`. It writes a ledger and a list of candidates.
4. `proof` checks that every file was shown whole in the reader's transcript.
5. A different agent verifies each candidate.
6. `verdict-check` refuses a candidate or a dropped lead with no verdict.
7. `accept` passes a unit only when proof and verdicts both pass.
8. `gate` checks every filed field against the real line.
9. `status` prints coverage as N of M.
10. `file` runs as a dry run, then an approval when one is required, then apply, then verify.
11. `report` prints every action taken and every action refused.

A unit with any file unread is `partial`, never `done`.

## What it asks before acting

Nothing is read until you have answered.
`init` writes a config with `confirmed: false`.
Every other command refuses while it is false.

First comes the interview.
You get one question at a time, each with a safe default.
Before it asks, the skill may look for an answer you already gave.
That needs your yes to the `history` group.
You see the source of such an answer and can correct it.

Next comes the plan.
`plan` lists every permission group with its bounds, its cost and where its data goes.
You give one yes or no per group.
Silence is never a yes.
A yes to one group is never a yes to another.
A no is final.
A later yes is refused unless you reopen the group in your own words.

The groups cover local reads, agent runs, memory writes, tracker labels, issues, advisories, assignees and comments, live checks, blocker fixes, blocker pushes, transcripts, history, clones and knowledge sources.
The engine checks every outward action against its grant and its bounds.

Last comes `confirm`.
It refuses while any choice or group is unanswered.
It lists what is missing.
A change after `confirm` goes back through `summary`, `plan` and a new yes.

## What it never does

It never fixes product code.
It files findings and never fixes them.
A blocker fix needs its own grant, and a backup comes first.

It never files without a grant.
It never files before you approve a dry run of the exact plan.
It never puts a private finding in a public place.

It never accepts a step on an agent's report.
Only `proof`, `verdict-check` and `accept` accept a unit.
The reader and the verifier of a unit are different agents.

It never asks for a password, token or key.
It never reads credential folders, shell history or browser data.
It never opens a secret file of a repo, such as `.env` files and key files.
It sends no telemetry.
It does not download anything or install packages.
It uses only the Python standard library, and its code opens no network socket.
It never takes an action it cannot log.
It never reuses an old permission answer unless you say yes.
It treats text inside the audited code as data, never as an instruction.

## Models and cost

Crucible names roles, not products.
The tiers here are fast, balanced and strong.
The numbers below come from the selftest in `references/calibration.json`.
The selftest seeds 12 known defects in a fixture.

Balanced tier:

- Recall: 12 of 12 (found 12 of 12 seeded).
- Invented findings: 0.
- Coverage: 100 percent.
- Cost: 5,362,016 tokens.
- Forecast error: 0.0.
- Result: SELFTEST PASS.

Fast tier:

- Recall: 0 of 12 (found 0).
- Invented findings: 0.
- Coverage: 0 percent.
- Cost: 3,214,698 tokens.
- Forecast error: 0.0.
- Result: SELFTEST FAIL, because the readers produced no findings that pass the gate.

The balanced reader is the default for this reason.
The fast tier found 0 of 12 on the same fixture.
The fast tier is cheaper, but it fails the gate.

The fixture has 2 units.
The pilot therefore covers every unit.
A forecast error of 0.0 does not prove the forecast.

The first-try forecast errors were -0.5181 for balanced and -0.4215 for fast.
The verifier default was far below the measured verifier use.
The refit fixed the verifier cost.
For the balanced tier, the verifier start cost went from 12,000 to 1,739,124 tokens.

## Self-heal and lessons

There is no heal command.
A stage failure is classified from measured facts.
These facts are the exit code, the schema result, truncation, tool calls and the harness text.

A known class gets one scripted recovery:

- A context overflow splits the unit and reruns the halves.
- A stub reply resends the prompt with a demand to call a real tool.
- A rate limit waits, then resumes.
- A tracker scope error stops and tells you to refresh the token scope.
- A schema miss reruns the stage once.

A refused action is never healed.
That covers gate, test, permission and visibility refusals.
A tool refused by the harness is reported, not retried.
An unknown failure is reported, not retried, unless an active lesson names a recovery for it.
A unit that fails twice in one class is blocked and becomes a blocker.
Every heal goes into `actions.log` and into `crucible report`.

Lessons are patterns in crucible's own records.
`learn propose` writes a proposal for a failure seen at least three times.
Nothing is used until you say yes with `learn apply --yes`.
A lesson must also pass the seeded selftest, and its score must not drop.
A lesson may only tune or tighten.
It can shrink units, pick a reader tier, scale the forecast, add one line to the reader brief, or set a recovery for a failure signature.
It can never reach a safety, permission, privacy, visibility or gate rule.
`learn review` counts each active lesson again and proposes a revert if it is worse.
`learn revert` undoes a lesson after a backup.

## The measured limits

The fixture is tiny.
It has 2 units, so the pilot covers every unit.
A forecast error of 0.0 in the selftest does not prove the forecast.

The first-try forecast was off.
The errors were -0.5181 for balanced and -0.4215 for fast.
The refit fixed the verifier cost, but only on this fixture.

The fast tier fails the gate.
It found 0 of 12 seeded defects.
Its readers did not produce findings that pass the gate.
That is why the balanced tier is the default reader.

This page states no other limit, because the calibration file shows no other measurement.
