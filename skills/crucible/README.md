# Crucible

The skill an agent loads when asked to audit a whole system: every repo, every file, with proof that each file was read.

## How a run goes

1. **Interview.** The agent detects your repos by script, then asks 11 questions one at a time: scope, goals, stages, tracker, advisories, other owners, privacy words, budget, models, live checks, permanent memory. Nothing runs until you say yes to the summary.
2. **Inventory.** Each repo is cut into units of at most 90 KB of whole files.
3. **Read.** One reader agent per unit reads every file through a command that stamps what it shows.
4. **Prove.** A script checks the reader's transcript: every file shown whole, every stamp valid.
5. **Verify.** A different agent tries to prove each candidate false.
6. **Accept.** A script promotes the surviving candidates to findings and checks every field.
7. **File.** The findings go to the tracker you chose, with a "Before you fix" block, and are read back.

## The engine

```sh
python scripts/crucible.py selftest --replay
python scripts/crucible.py --root ./crucible-audit init --repo ./my-service
```

Python 3.10 or newer, standard library only. The GitHub adapter needs the `gh` CLI.

| Part | What it is |
| --- | --- |
| `scripts/crucible.py` | the command line |
| `scripts/cruciblelib/` | the engine |
| `scripts/test_portability.py` | proves no project-specific word entered the skill |
| `fixtures/seeded/` | a small sample system with known defects, used by the self-test |

## Layout

```
crucible/
├── SKILL.md              trigger, interview, pipeline, guarantees
├── agents/               reader and verifier briefs
├── references/
│   ├── interview.md      the 11 questions
│   ├── memory.md         permanent memory
│   ├── method.md         the nine method rules
│   └── finding-schema.md the finding and verdict shapes
├── scripts/              engine and tests
└── fixtures/             sample system and recorded replays
```

## Installing

```bash
npx skills add NoMercyLabs/skills --skill crucible
```

Or as a Claude Code plugin: `/plugin marketplace add NoMercyLabs/skills`, then `/plugin install nomercylabs@nomercylabs`.

## Design decisions

**The engine enforces the interview.** A rule in a prompt is a promise. Every command refuses to run while the config is unconfirmed.

**A script accepts, never a report.** A reader's "I read everything" is checked against stamps only the engine can make. A verifier's "this is real" is checked for quoted lines that exist.

**Coverage is a count.** "Found nothing" means nothing without N of M from the ledger.

**Nothing leaves the machine by default.** The tracker is the one place findings go, and the user chooses it.
