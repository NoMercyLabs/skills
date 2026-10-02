# Security

Crucible works for the person who runs it. This file lists everything the skill touches, so a reviewer does not have to read the code to know. `scripts/tests/test_safety.py` scans the code and the documents for each rule below, and it fails the suite when one is broken.

## What it never does

- No telemetry, analytics or phone-home. Nothing is sent to the publisher.
- No `eval`, `exec`, `os.system`, `shell=True`, dynamic import or encoded blob in the code.
- No download, no package install, no `curl | sh`. Python standard library only.
- It never asks for a password, token or key. A secret pasted into the chat is not used or stored; revoke it.
- It never reads the credential folders of the machine: SSH, cloud CLIs, keychains, browser data, shell history.
- It never opens a secret file of a repo: `.env*` (the `.example`, `.sample`, `.template` and `.dist` templates are plain text and stay readable), `*.pem`, `*.key`, `id_rsa`, `id_dsa`, `id_ecdsa`, `id_ed25519` (not `.pub`), `*.p12`, `*.pfx`, and JSON whose name holds `credentials`, `client_secret` or `service_account`. Inventory skips them, so no unit and no snapshot holds one, and `show` and the snapshot reader refuse them by name. `crucible safety` lists the secret files that git tracks, by path only.

## Files it reads

- Text files of the repos the user put in scope (`inventory`, `init`). Not read: `.git`, `node_modules`, `vendor`, `third_party`, `__pycache__`, symbolic links, binary files, the user's skip list, secret files.
- Its own audit folder (`--root`, default `./crucible-audit`): `config.json`, `state.json`, `coverage.json`, `actions.log`, `dryruns.json`, `approvals.json`, `filed.json`, and the `units`, `snapshot`, `candidates`, `ledger`, `review`, `findings` folders, and `private/key`.
- The reader transcript the user passes to `proof`: only the tool output blocks that carry the stamped file text.
- An earlier `coverage.json` the user passes to `inventory --delta`.
- The user's own past messages, only through `scripts/cruciblelib/prefill.py` (`read_user_messages`): the one place conversation text is read. Only with the `history` grant, only for sessions run inside a repo named in that grant and in the config, only the user's own text lines that match an interview question. Assistant text and tool output are never read out. Only the matched line, its session name and its date are kept, in `ROOT/prefill.json`. An old permission answer is never reused unasked: `crucible reuse` applies one only after the user says yes.
- Agent transcripts, only through `scripts/cruciblelib/transcripts.py`: only with the `transcripts` grant, only for repos named in that grant and in the config, only the shell command text and its exit status. The conversation and the tool output are never returned.
- `crucible costs`, through `scripts/cruciblelib/costs.py`: the same `transcripts` grant and repo scope, and only usage numbers, tool names, command shapes and result sizes. The user-wide instruction file is measured only with the `user_instructions` grant and its `targets` bound, and only its size is kept. `costs move` changes an instruction file only when the user names the file and the heading; it backs the file up first and moves the text to an on-demand file, never deletes it.
- `~/.claude/plugins`: a folder-name check for a memory plugin (`config.py`). No file inside it is opened.
- A file or folder the engine is about to change, to copy it first (`backup.py`), when backups are on.

## Files it writes

- Everything in the audit folder listed above, plus `parked`, `backups` (or the folder the user chose) and `knowledge`.
- `private/key`, a random key for the read stamps, and `private/.gitignore` so the key is never committed. No command prints the key.
- One Markdown file per finding in the folder the user chose, when the Markdown tracker is used.
- It writes inside the repos only when the user grants a blocker fix, and then it makes a backup first.
- The audit folder holds security findings. Keep it out of version control.

## Network calls

The Python code opens no socket and imports no network module. The only outward path is the `gh` command, started by `scripts/cruciblelib/trackers/github.py` when findings are filed:

- Only after the user answered the interview, granted the group, approved a dry run of the exact plan, and confirmed that the destination is private or public.
- Only to the repos, labels, assignees and board the user named. Every action is checked against the grant and written to `actions.log` with secrets masked.
- `gh` uses the user's own login. The skill never sees a token. If a scope is missing, it prints the `gh auth refresh -s <scope>` command for the user to run.

Reads of outside knowledge sources are separate, are granted one by one and are read-only. Only the tracker adapters and a knowledge adapter may import a network module; `test_safety.py` refuses it anywhere else. The model provider that runs the agents receives the code of the files in scope; the plan says so before the user grants anything.

## Subprocesses

Every call is an argument list, never a shell string. `test_safety.py` allows `subprocess` only in the files below.

| File | Command | When |
| --- | --- | --- |
| `cruciblelib/config.py` | `git -C PATH remote get-url origin` | `init`, to detect the remote |
| `cruciblelib/config.py` | `grimoira help` | `init` and `detect`, to see whether the memory command answers |
| `cruciblelib/safety.py` | `git -C PATH ls-files -z` | `crucible safety` |
| `cruciblelib/trackers/github.py` | `gh repo view`, `gh project view`, `gh auth status`, `gh label create`, `gh issue create`, `gh issue view`, `gh project item-add`, `gh pr create` (one pull request per fixed blocker, only inside the `blocker_fixes` grant, landing `pr`, after the `blocker_pushes` push), `gh api` (security advisories), `gh api graphql` (create board views, set their filters, read them back) | filing and its checks; the view writes only inside the `tracker_board` grant |
| `cruciblelib/knowledge.py` | `gh issue list`, `gh pr list`, `gh api graphql` (a read-only discussions query), through the helper in `trackers/github.py`; one HTTPS GET for a `url` source | `knowledge fetch`, only inside the `knowledge_sources` grant and its `sources` bound; text is masked and checked for privacy words before it is written |
| `cruciblelib/clones.py` | `git clone --quiet --no-hardlinks` | `workspace clone`, only inside the `workspace_clones` grant (no grant, no folder and no process) |
| `cruciblelib/clones.py` | `git clone --quiet --no-hardlinks`, for a `git:URL` knowledge source | `knowledge fetch`, only inside the `knowledge_clone` grant and its `sources` bound, after the `knowledge_sources` grant (no grant, no folder and no process); the clone sits in a scratch folder and is removed after the read |
| `cruciblelib/clones.py` | `git push --quiet origin BRANCH` | `fix run`, only inside the `blocker_pushes` grant, after the fix passed its proof and was committed locally (no grant: no push, the blocker stays `fixed-local`) |
| `cruciblelib/clones.py` | `git ls-remote --symref SOURCE HEAD` | `workspace`, a read-only query of a remote source's default branch, only inside the `workspace_clones` grant (no grant: the branch shows as unknown and no process starts) |
| `cruciblelib/blockers.py` | the `change` and `proof` commands of a fix plan the user approved, as an argument list from `shlex`, never a shell | `fix run`, only after the `blocker_fixes` grant and its mode check; every command is written to `actions.log`; the local `git checkout -b`, `add` and `commit` of the fixed files run inside the same grant |

## Text from the audited code

Repo files, issues and fetched knowledge can hold text that looks like instructions. The reader, verifier and fetch briefs treat all of it as data to report. A finding about such text is a finding.

## Report a problem

Open an issue at https://github.com/NoMercyLabs/skills (the Security tab takes a private report). Say which file or command, and what it did that this file does not list. A difference between this file and the code is a bug, and the fix is to the code or to this file.
