# The interview

Run after `crucible init` and before any other command. Ask the questions below in the order `crucible next` gives them (the engine's `INTERVIEW_ORDER`), **one at a time**. Show the default with the question. Wait for the answer. Never answer for the user, never merge two questions, never skip one.

**The principle.** Every choice about the user's own system, risk or workflow is a question with the safest default. The agent never decides a user policy and never hard-codes one. Where the user has no preference, the default applies and the summary shows it.

Detected facts are not asked. `crucible init` already printed remotes, languages, line counts, CI files and suggested skips. Use them to offer a default; ask only what a script cannot know. The one detected value that is always unknown is whether a repo is public or private: ask it under question 1 and record it in `repos[].public`.

Never edit `ROOT/config.json` by hand. Record each answer with:

```sh
python scripts/crucible.py --root ROOT answer KEY VALUE [--words "the user's words"]
python scripts/crucible.py --root ROOT next
```

`VALUE` is JSON or a plain string. `KEY` is a dotted config key, named in each question below. The engine stores the answer and the user's words in `config.answers`, and refuses an unknown top-level key. `crucible next` prints the next unanswered key. After the last interview key come the permission groups (see `permissions.md`). Then run `crucible summary`, show the whole output, and run `crucible confirm` only after the user says yes. `confirm` refuses, and lists what is missing, until the project brief is confirmed, the memory choice, the filing choice, the blocker-fix choice and every permission group are answered.

Order: scope, goals, stages, tracker, auto_file, advisories, owners, privacy_words, budget, models, live_checks, blocker_fixes, backups, memory, knowledge_sources, then the permission groups. Two more answers are asked before filing: `visibility` (confirm each repo and board with `crucible visibility confirm SLUG public|private --words`, after `crucible visibility detect`) and `private_destination` (`advisory`, `private_repo` or `local_report`).

## 0. The project brief

Ask this first, before scope. The audit must never work against the user, so it learns what the project is and what the user expects of it.

1. Collect, then read. `crucible brief collect` lists the files the project describes itself with: READMEs, docs folders, manifests, contribution and security notes, decisions. It prints paths only and skips secret files. Read those files, then store a short summary with `crucible brief summary FILE`: a JSON list of `{"line": ..., "source": ...}`, every source one of the collected paths. The summary is labelled "agent-written, not confirmed".
2. Ask the seven questions one at a time, and record the user's own words with `crucible brief answer FIELD --words "..."`. The brief never fills an answer for the user.
   - `purpose`. Ask: "What is the project for, and who uses it?" Why: a defect is judged by who it hurts.
   - `good`. Ask: "What does good mean for you: what must always work?" Why: it ranks what is serious.
   - `intentional`. Ask: "What is intentional, even if it looks odd?" Why: an odd choice made on purpose is not a defect.
   - `must_never_change`. Ask: "What must never change: public contracts, data formats, compatibility promises, behaviour users rely on?" Why: no fix may touch these. Separate items with a new line or a semicolon.
   - `accepted_risks`. Ask: "Which risks have you accepted on purpose?" Why: an accepted risk is not filed again.
   - `out_of_scope`. Ask: "What is out of scope or not a goal?" Why: such findings are listed, not filed.
   - `known_issues`. Ask: "Which issues do you already track or decided not to fix?" Why: they are not filed twice.
3. Show the result with `crucible brief show`. The user corrects it. Then run `crucible brief confirm` only after the user says yes. A later `brief answer` or `brief summary` needs a new confirm. `crucible confirm` refuses until the brief is confirmed.

## 1. Scope

- **Why**: the audit reads every file in scope and nothing outside it. Scope sets the cost.
- **Default**: every detected repo, whole tree, skipping the folders `init` suggested (vendored, generated, fixtures).
- **Key**: `scope` (`scope.include`, `scope.skip`); `repos[].public` is answered here too.
- **Ask**: "These repos were found: A, B. Audit all of them, skipping `vendor/` and `dist/`? Is each one public or private?"

## 2. Goals

- **Why**: findings are sorted by this ordered list. A finding names the goal it hurts.
- **Default**: 1 users can use the product without help, 2 security, 3 stability, 4 features.
- **Key**: `goals` (a list of `{id, name}`).
- **Ask**: "Findings are ranked by goal. Keep this order, or give me your own list?"

## 3. Stages

- **Why**: a finding can be placed on the user's roadmap. With no stages, every finding gets stage `none`.
- **Default**: none.
- **Key**: `stages`.
- **Ask**: "Do you have roadmap stages findings should be placed on? List them, or say none."

## 4. Tracker

- **Why**: filed findings go to exactly one place, and the user owns that place.
- **Default**: none, a local Markdown report. The agent offers what was detected (existing boards and issue labels), a new board, issues without a board, or the Markdown report.
- **Key**: `tracker` (`kind`, `owner`, `repo`, `project_number`, `fields`).
- **Ask**: "Where should findings go: a new GitHub Project board, an existing one (here is the list), plain GitHub issues, or a local Markdown report?"
- For a board, show the field mapping (Stage, Goal, Area, Size, Severity, Priority, each created or mapped) and get a separate yes before writing it.

## 10b. Filing automatically (asked right after the tracker)

- **Why**: the user owns the tracker, so the user decides whether the skill writes to it without a pause.
- **Default**: no. The dry-run list is shown and filing waits for the user's go.
- **Key**: `auto_file` (`null` unset, `true`, `false`).
- **Ask**: "May I file the findings there automatically?"
- **Yes**: `file --apply` runs within the granted bounds without asking again. It still needs a `file --dry-run` of the same plan first, and it stops at the bounds.
- **No**: the dry-run list is shown at the end, and filing waits for the user's go, given by `crucible approve PLAN_HASH` for that exact plan. A changed plan has a new hash and needs a new go.

## 5. Security findings in public repos

- **Why**: a security finding filed as a public issue discloses the hole before the fix.
- **Default**: private draft security advisories.
- **Key**: `advisories` (`draft` or `none`). `none` means a private report only.
- **Ask**: "For a public repo, should security findings go to private draft advisories? That is the default. The other choice is a private report only."

## 6. Repos owned by someone else

- **Why**: findings in a repo the user does not own are a request to its owner, not a task list.
- **Default**: the user owns every repo (no entries).
- **Key**: `owners` (per repo: `owner`, `mode` bundle or single, `assignee`).
- **Ask**: "Does anyone else own one of these repos? If so, who, and do they want one bundled issue or one per finding, and who is assigned?"

## 7. Privacy words

- **Why**: a filed issue may be public. The gate refuses any finding containing these words.
- **Default**: none beyond key-like strings, which the gate always refuses.
- **Key**: `privacy_words`.
- **Ask**: "List names, hostnames, emails or address ranges that must never appear in a filed issue."

## 8. Budget

- **Why**: reading is the cost. The engine stops new readers at the cap.
- **Default**: no cap. Run `crucible estimate` first and show the user the units, lines and tokens per tier (about 34 tokens per line read, verification included).
- **Key**: `budget.max_tokens`.
- **Ask**: "The estimate is N tokens. Set a hard cap, or run without one?"

## 9. Models

- **Why**: readers and verifiers need judgment, checks do not.
- **Default**: reader balanced, verifier balanced, check fast, judge strong.
- **Key**: `models`.
- **Ask**: "Readers and verifiers on the balanced tier, checks on the fast tier, cross-unit judgment on the strong tier. Change any?"

## 10. Live checks

- **Why**: some facts live in a running system (a setting, a header), not in the code. Reading them touches a real system.
- **Default**: off.
- **Key**: `live_checks.enabled`, `live_checks.targets`.
- **Ask**: "May I run read-only checks against running systems? Default is no. If yes, name each target. I show every command before I run it."

## 10c. Blocker fixes

- **Why**: a blocker stops the audit or the filing. Fixing it changes the user's system, so it is the user's call. Product findings are a different thing: they are filed, never fixed by this skill.
- **What counts as a blocker**: a tool the inventory needs is missing; a build or test command the readers need fails; the tracker lacks a field or a label; a token lacks a scope. Nothing else.
- **Key**: `blocker_fixes` = `{"mode", "landing", "branch", "live_changes"}`.
- **Ask, part 1 (`mode`)**: "May I fix things that block the audit or the filing?" Choices: `each` (ask for every fix), `within_limits` (all fixes inside limits you name), `never`. Default: `never` until the user chooses.
- **Ask, part 2 (`landing`)**: "How should a fix land?" Choices: `pr` (one pull request per fix; the default; the user merges), `local_branch` (commits on a local branch), `push_branch` (push to a branch the user names; record it in `branch`).
- **Ask, part 3 (`live_changes`)**: "May a fix change a running system?" Default `"never"`. Otherwise a list of the systems the user names, one by one.
- `references/blockers.md` has the commands and the rules.

## 10d. Backups

- **Why**: a change can lose data (a file, a tracker board or field, a config, a memory store, a running system's setting). A backup is made first.
- **Default**: on. Backups go to `ROOT/backups/<timestamp>-<label>`.
- **Key**: `backups` = `{"enabled": true, "path": null}`.
- **Ask**: "Backups are on by default and go to `ROOT/backups`. Keep that place, or choose another folder? Turning them off is your choice and is recorded."
- If a backup is enabled and the copy fails, the change is not made.

## 10e. Where the other repos live

- **Why**: a system is often more than the repo in front of you. Reading one repo of several loses the depth between them, and the audit must say so.
- **Detect first**: run `crucible layout` (single repo, monorepo, or a folder holding many repos) and `crucible related` (repos the code points to, each with file:line; `--same-owner` also lists the owner's other repos, read-only). Do not ask what a script can answer.
- **Default**: this repo only, with the lost depth stated plainly (`crucible status` and `report` say it).
- **Key**: `workspace` = `{"mode": "this_repo" | "existing_checkouts" | "base_folder", ...}`. Unset is `null`; `confirm` refuses while it is unset.
- **Ask**: "These repos look related: LIST, each with the line that points to it. Read this repo only, add checkouts you already have (read-only), or clone them into a fresh base folder outside your repos? Your own checkouts are never touched, switched or written."
- Show the clone plan first: `crucible workspace plan --base FOLDER` prints branch and disk size per repo. It writes nothing.
- Record the choice with the user's own words: `crucible workspace choose this_repo|existing_checkouts|base_folder [--base FOLDER] [--repo PATH] --words "..."`. The base folder must be fresh (empty or new) and outside every user repo.
- Cloning needs the `workspace_clones` grant: `crucible workspace clone`. Clones are read-only copies made without hard links.

## 11. Permanent memory

- **Why**: without it, the next session re-learns the system and the next audit re-reads files it already read. `confirm` refuses until this is answered.
- **Default**: set up Grimoira (recommended).
- **Key**: `memory` (`{"kind": "grimoira", "instance": "NAME"}` or `{"kind": "none"}`). Unset is `null`.
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
   /plugin marketplace add NoMercyLabs/skills
   /plugin install grimoira@nomercylabs
   ```

   If you already added NoMercyLabs/grimoira as a marketplace, keep it: it lists the same plugins.

   The user runs them. Slash commands belong to the user; the agent cannot run them. After the user says they are done, the agent runs the full onboarding below. Record the instance name in `memory.instance`.
2. **Use the Grimoira store already installed.** Ask which instance. Record it in `memory.instance`.
3. **No permanent memory.** Say what is lost: the next session re-learns the system, and the next audit cannot skip files already read. Record `{"kind": "none"}`.

### Full onboarding when Grimoira is accepted

Accepting Grimoira means its full init, so that every piece of knowledge is onboarded. Do these in order and show the user the output of each step.

1. Run the `grimoira-init` skill. It asks the user three questions: where the store lives, which projects to index, what to import. The user answers. The agent never answers for the user.
2. The skill runs `init --full`.
3. For every extra root the user named: `project`, then `index-code`.
4. For an existing database the user named: `import`.
5. For past conversations the user chose: `index-chat`.
6. The proof: `projects`, `stats`, and one `recall`.

A line that starts with `FAILED` stops the onboarding. Show that line to the user and wait. Never run `init --full` again on an existing instance without telling the user first.

Use only the verbs the installed Grimoira lists. If one is not listed, say so and do not invent a replacement.

### Absorb the local sources

Then absorb every local knowledge source in scope:

- docs folders, decision records, runbooks and READMEs: `index-docs --from <dir>`;
- memory files: `index-memory --from <dir>`;
- package identities: `index-packages`.

### Where does more knowledge live outside this machine?

Then ask this question (key `knowledge_sources`, a list of `{"name", "kind", "target"}`, with `kind` one of `github`, `url`, `folder`):

"Where does more knowledge live outside this machine?"

Offer these examples, and let the user name others:

- the repos' issues, pull requests, discussions, wiki and releases on GitHub;
- a docs website;
- a knowledge base, such as Confluence or Notion;
- chat exports;
- CI logs;
- another machine or a shared drive.

Default: none. For each source the user names:

1. Record it as a named entry in `knowledge_sources`.
2. Grant it read-only: `crucible grant knowledge_sources yes --bound sources=NAME` (see `permissions.md`).
3. Fetch it: `crucible knowledge fetch NAME`. The engine writes Markdown into `ROOT/knowledge/NAME/`. A `github` source uses read-only `gh` calls. A `url` source is a site or a git repository. A `folder` source is an export the user points at (for example a Confluence, Notion or chat export).
4. Absorb it: `index-docs --from ROOT/knowledge/NAME`.

Grimoira reads local folders only, which is why the fetch step exists. The engine masks secrets and refuses privacy words before it writes anything. A source the engine cannot reach is reported with what the user can export, and the report lists it as not absorbed. It is never skipped silently.

`references/memory.md` says what is written to memory, and when.
