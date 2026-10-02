# Permanent memory

Question 11 of the interview sets `config.memory`. This file says what the choice means after the user confirms.

## The three options

| `memory` | Meaning |
| --- | --- |
| `{"kind": "grimoira", "instance": "NAME"}` set up now | The user installed the plugin, the `grimoira-init` skill ran, the user answered its three questions. |
| `{"kind": "grimoira", "instance": "NAME"}` already installed | The user named an existing instance. Write into that one, never another. |
| `{"kind": "none"}` | The audit folder is the only record. |

Without memory, two things are lost. The next session re-learns the system from scratch. The next audit cannot skip files already read, because the sha256 of each read file lives only in the old audit folder's `coverage.json`. `inventory --delta OLD_COVERAGE` still works from that file if the user keeps the folder; nothing else carries over.

## What is written, and when

Nothing is written before `crucible confirm`. After it, only what passed a gate is written.

| What | When | Source |
| --- | --- | --- |
| Confirmed scope, goals, stages and tracker | right after `confirm` | `config.json` |
| Verified facts about the system: repos, live instances, where configuration lives | when a verifier's checked lines prove them | `review/verdicts-UNIT.json` |
| The method rules, as rules | once, after `confirm` | `references/method.md` |
| Each filed finding: id, tracker URL, file and line, cause | after `file --verify` passes | `findings/F-NNNN.json` |
| Each user correction, as a rule | the moment the user corrects the audit | the conversation |

A hypothesis is never written as a fact. A finding whose `why.verified` is false is written only as an open lead, with its `cause:` entry from `not_checked`.

## Which tools to call

Before the first write, name the memory tools you will call, and read the names from the installed plugin's own tool list in this session. Never guess a tool name from this file, from memory or from another project. If the plugin's tools are not listed (the plugin is installed but its server has not connected, which can happen for the first session after an install), say so, record nothing, and keep working with the audit folder. Tell the user memory is not active this session.

Memory is context. A recalled fact is a lead. The source file and the running system are the proof, so every recalled fact used in a finding is re-checked against the snapshot.

## Keep what is processed

The ledger stores the sha256 of every file read. `crucible inventory --delta OLD_COVERAGE` makes units only of files that changed or were added; unchanged files already marked done are carried, with the old unit named as proof. Nothing is deleted until the user says it is obsolete.
