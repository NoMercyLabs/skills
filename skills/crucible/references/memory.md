# Permanent memory

Question 11 of the interview sets `config.memory`. This file says what the choice means after the user confirms, how Grimoira is onboarded, and how outside knowledge flows in.

## The three options

| `memory` | Meaning |
| --- | --- |
| `{"kind": "grimoira", "instance": "NAME"}` set up now | The user installed the plugin, the `grimoira-init` skill ran, the user answered its three questions. |
| `{"kind": "grimoira", "instance": "NAME"}` already installed | The user named an existing instance. Write into that one, never another. |
| `{"kind": "none"}` | The audit folder is the only record. |

Without memory, two things are lost. The next session re-learns the system from scratch. The next audit cannot skip files already read, because the sha256 of each read file lives only in the old audit folder's `coverage.json`. `inventory --delta OLD_COVERAGE` still works from that file if the user keeps the folder; nothing else carries over.

## The full init steps

Run when the user chose to set up Grimoira. Show the output of each step.

1. The user runs the two install commands from `interview.md`.
2. The agent runs the `grimoira-init` skill. It asks three questions (store folder, projects to index, what to import). The user answers.
3. `init --full`. Never run it again on an existing instance without telling the user first.
4. For each extra root: `project`, then `index-code`.
5. For an existing database: `import`. For past conversations: `index-chat`.
6. The proof: `projects`, `stats`, one `recall`.

A line that starts with `FAILED` stops the onboarding. Show it to the user. Do not continue past it.

Use only the verbs the installed Grimoira lists. Do not invent one.

## Knowledge flow

Grimoira reads local folders only. There is no remote fetch in it. So knowledge reaches it in two ways.

**Local sources in scope.** Absorb them directly:

| Source | Command |
| --- | --- |
| docs folders, decision records, runbooks, READMEs | `index-docs --from <dir>` |
| memory files | `index-memory --from <dir>` |
| package identities | `index-packages` |

**Sources outside this machine.** The user names each one in the interview (key `knowledge_sources`) and grants it read-only. Then:

```sh
python scripts/crucible.py --root ROOT knowledge fetch SOURCE_NAME
```

The engine writes Markdown into `ROOT/knowledge/SOURCE_NAME/`. Then absorb it: `index-docs --from ROOT/knowledge/SOURCE_NAME`.

- Source kinds: `github` (the repo's issues, pull requests and discussions, by read-only `gh` calls; wiki and releases are not read), `url` (one public https page, as text), `folder` (an export folder the user points at, for example a knowledge base or chat export). A `git` source is recorded as not reached, with the advice to clone it and name its docs folder as a `folder` source.
- A source is a name from `knowledge_sources`, or written inline as `github:OWNER/REPO`, `url:ADDRESS` or `folder:PATH`. The grant lists it in `sources=`, exactly as written. `knowledge list` shows each source and its status.
- The command prints the `index-docs --from` line the memory step runs. It never runs it.
- The fetch needs the `knowledge_sources` grant and is logged in `actions.log`.
- Secrets are masked and privacy words refused before anything is written. A refusal stops the whole write for that source.
- A source that cannot be reached is not skipped silently. The engine prints what the user can export and records the source as not absorbed. `crucible report` lists it with the reason.
- The final report lists every source absorbed, with counts from `stats`, and every source named but not absorbed.

## What is written, and when

Nothing is written before `crucible confirm`. After it, only what passed a gate is written, and each write goes through the `memory_writes` grant.

| What | When | Source |
| --- | --- | --- |
| Confirmed scope, goals, stages and tracker | right after `confirm` | `config.json` |
| Verified facts about the system: repos, live instances, where configuration lives | when a verifier's checked lines prove them | `review/verdicts-UNIT.json` |
| The method rules, as rules | once, after `confirm` | `references/method.md` |
| Each filed finding: id, tracker URL, file and line, cause | after `file --verify` passes | `findings/F-NNNN.json` |
| Each user correction, as a rule | the moment the user corrects the audit | the conversation |

A hypothesis is never written as a fact. A finding whose `why.verified` is false is written only as an open lead, with its `cause:` entry from `not_checked`.

A memory store can be lost, so a backup of it is made before the first write (see `permissions.md`, Backups).

## Which tools to call

Before the first write, name the memory tools you will call, and read the names from the installed plugin's own tool list in this session. Never guess a tool name from this file, from memory or from another project. If the plugin's tools are not listed (the plugin is installed but its server has not connected, which can happen for the first session after an install), say so, record nothing, and keep working with the audit folder. Tell the user memory is not active this session.

Memory is context. A recalled fact is a lead. The source file and the running system are the proof, so every recalled fact used in a finding is re-checked against the snapshot.

## Keep what is processed

The ledger stores the sha256 of every file read, in `coverage.json`. On a re-audit:

```sh
python scripts/crucible.py --root NEWROOT inventory --delta OLD_COVERAGE
```

A file whose sha256 equals the old entry, and whose old unit was done, is marked `carried` and is not read again. Units made only of carried files get status `carried`. `status` counts them as covered and names the old unit. Changed and new files form new units.

Nothing is deleted until the user says it is obsolete. That covers the old audit folder, its coverage file, the knowledge folders and the memory store.
