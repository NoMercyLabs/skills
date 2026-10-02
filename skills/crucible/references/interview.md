# The interview

Run after `crucible init` and before any other command. Ask the 11 questions below in order, **one at a time**. Show the default with the question. Wait for the answer. Never answer for the user, never merge two questions, never skip one.

Detected facts are not asked. `crucible init` already printed remotes, languages, line counts, CI files and suggested skips. Use them to offer a default; ask only what a script cannot know. The one detected value that is always unknown is whether a repo is public or private: ask it under question 1 and write it to `repos[].public`.

There is no command that sets a config value. Write each answer into `ROOT/config.json` at the key named below, then run `crucible summary`. Show the whole summary. Run `crucible confirm` only after the user says yes.

## 1. Scope

- **Why**: the audit reads every file in scope and nothing outside it. Scope sets the cost.
- **Default**: every detected repo, whole tree, skipping the folders `init` suggested (vendored, generated, fixtures).
- **Sets**: `scope.include`, `scope.skip`, `repos[].public`.
- **Ask**: "These repos were found: A, B. Audit all of them, skipping `vendor/` and `dist/`? Is each one public or private?"

## 2. Goals

- **Why**: findings are sorted by this ordered list. A finding names the goal it hurts.
- **Default**: 1 users can use the product without help, 2 security, 3 stability, 4 features.
- **Sets**: `goals` (a list of `{id, name}`).
- **Ask**: "Findings are ranked by goal. Keep this order, or give me your own list?"

## 3. Stages

- **Why**: a finding can be placed on the user's roadmap. With no stages, every finding gets stage `none`.
- **Default**: none.
- **Sets**: `stages`.
- **Ask**: "Do you have roadmap stages findings should be placed on? List them, or say none."

## 4. Tracker

- **Why**: filed findings go to exactly one place, and the user owns that place.
- **Default**: none, a local Markdown report. The agent offers what was detected (existing boards and issue labels), a new board, issues without a board, or the Markdown report.
- **Sets**: `tracker` (`kind`, `owner`, `repo`, `project_number`, `fields`).
- **Ask**: "Where should findings go: a new GitHub Project board, an existing one (here is the list), plain GitHub issues, or a local Markdown report?"
- For a board, show the field mapping (Stage, Goal, Area, Size, Severity, Priority, each created or mapped) and get a separate yes before writing it.

## 5. Security findings in public repos

- **Why**: a security finding filed as a public issue discloses the hole before the fix.
- **Default**: private draft security advisories.
- **Sets**: `advisories` (`draft` or `none`). `none` means a private report only.
- **Ask**: "For a public repo, should security findings go to private draft advisories? That is the default. The other choice is a private report only."

## 6. Repos owned by someone else

- **Why**: findings in a repo the user does not own are a request to its owner, not a task list.
- **Default**: the user owns every repo (no entries).
- **Sets**: `owners` (per repo: `owner`, `mode` bundle or single, `assignee`).
- **Ask**: "Does anyone else own one of these repos? If so, who, and do they want one bundled issue or one per finding, and who is assigned?"

## 7. Privacy words

- **Why**: a filed issue may be public. The gate refuses any finding containing these words.
- **Default**: none beyond key-like strings, which the gate always refuses.
- **Sets**: `privacy_words`.
- **Ask**: "List names, hostnames, emails or address ranges that must never appear in a filed issue."

## 8. Budget

- **Why**: reading is the cost. The engine stops new readers at the cap.
- **Default**: no cap. Run `crucible estimate` first and show the user the units, lines and tokens per tier (about 34 tokens per line read, verification included).
- **Sets**: `budget.max_tokens`.
- **Ask**: "The estimate is N tokens. Set a hard cap, or run without one?"

## 9. Models

- **Why**: readers and verifiers need judgment, checks do not.
- **Default**: reader balanced, verifier balanced, check fast, judge strong.
- **Sets**: `models`.
- **Ask**: "Readers and verifiers on the balanced tier, checks on the fast tier, cross-unit judgment on the strong tier. Change any?"

## 10. Live checks

- **Why**: some facts live in a running system (a setting, a header), not in the code. Reading them touches a real system.
- **Default**: off.
- **Sets**: `live_checks.enabled`, `live_checks.targets`.
- **Ask**: "May I run read-only checks against running systems? Default is no. If yes, name each target. I show every command before I run it."

## 11. Permanent memory

- **Why**: without it, the next session re-learns the system and the next audit re-reads files it already read. `confirm` refuses until this is answered.
- **Default**: set up Grimoira (recommended).
- **Sets**: `memory` (`{"kind": "grimoira", "instance": "NAME"}` or `{"kind": "none"}`). Unset is `null`.
- **Detect first**: run `crucible detect`. It reports whether Grimoira is installed. Do not ask what a script can answer.
- **Ask**: "Do you want permanent memory? Three choices."

Before the three choices, say plainly what Grimoira does, so the user chooses knowing it.

**For this audit:**

- Every verified fact, finding, cause and tracker link is kept. The next session looks it up instead of reading the code again.
- The next audit reads only files that changed. Everything else is carried from the ledger.
- The session that fixes a finding can ask "what breaks if I change this?" and get the files and lines that use the symbol, across projects. That is the research-before-fix rule, made cheap.
- Each correction the user makes becomes a standing rule that every later session recalls.
- When it does not know a fact, it says so and logs the gap. It does not guess.

**For any other project:**

- Verified facts on demand (a base URL, a file path, a config key, a port) instead of guesses.
- Standing rules and past decisions, recalled in every session.
- Search over earlier conversations, and over plans, specs and docs it has absorbed.
- Cross-project "what breaks if I change this?", with files and lines.
- A session records what it learned, so the next one starts ahead. Todos and findings are kept.

**Costs and limits:**

- It needs Claude Code and the .NET 10 SDK.
- The first build takes a few minutes. The first session after an install may show a failed connection until it finishes.
- It uses disk space: one SQLite file per project.
- Everything stays on the machine and no network port is opened.
- A memory is context with a source, never proof. The file and the running code still decide.

Three choices, offered in this order:

1. **Set up Grimoira (recommended).** A public Claude Code plugin at github.com/NoMercyLabs/grimoira. It keeps a local SQLite store. Nothing leaves the machine. It needs the .NET 10 SDK. Show the user these two commands, each on its own line:

   ```
   /plugin marketplace add NoMercyLabs/grimoira
   /plugin install grimoira@nomercylabs
   ```

   The user runs them. Slash commands belong to the user; the agent cannot run them. After the user says they are done, the agent runs the `grimoira-init` skill. That skill asks three questions: where the store lives, which projects to index, what to import. The user answers them. The agent never answers for the user. Record the instance name in `memory.instance`.
2. **Use the Grimoira store already installed.** Ask which instance. Record it in `memory.instance`.
3. **No permanent memory.** Say what is lost: the next session re-learns the system, and the next audit cannot skip files already read. Record `{"kind": "none"}`.

`references/memory.md` says what is written to memory, and when.
