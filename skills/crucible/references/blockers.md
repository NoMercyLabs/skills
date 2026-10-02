# Blockers

A blocker is a thing that stops the audit or the filing. Nothing else is a blocker.

| Counts as a blocker | Example |
| --- | --- |
| A tool the inventory needs is missing | the language runtime a repo's build uses is not installed |
| A build or test command the readers need fails | the command a reader runs to check a claim exits non-zero |
| The tracker lacks a field or a label | the board has no Severity field |
| A token lacks a scope | the tracker token cannot create issues |

A defect in the user's product is not a blocker. It is a finding. Findings are filed and never fixed by this skill.

## Steps

1. **Record it.** When a stage cannot go on, stop that stage and run:

   ```sh
   python scripts/crucible.py --root ROOT blocker add DESCRIPTION [--stage S]
   python scripts/crucible.py --root ROOT blocker list
   ```

   Other stages go on. The blocker appears in the report.

2. **Plan the fix.**

   ```sh
   python scripts/crucible.py --root ROOT fix plan BLOCKER_ID
   ```

   ```sh
   python scripts/crucible.py --root ROOT fix plan BLOCKER_ID --cause TEXT --evidence TEXT --root-cause FILE:LINE      --touch ITEM --test NAME=FILE:LINE --change COMMAND --proof COMMAND --why TEXT
   ```

   It writes `ROOT/fixes/BLOCKER_ID.json`: the cause with evidence, the root cause link (`file:line`), `touches`, the tests, the backup (every touched file that exists), how the fix lands (from the user's answer, default one pull request), the `change` command, the `proof` command and `why_symptom_patch_not_enough`. `--evidence`, `--touch` and `--test` repeat. Commands are split like a shell line and run without a shell, in the first repo; use forward slashes in paths. Show the plan to the user. The method rules apply: find the cause, check siblings, and where code changes, a test fails first.

   The engine refuses a plan that does not touch the root cause file (a change only at the symptom), that names no test whose target is the root cause file, or that has no reason why a symptom patch is not enough.

3. **Run the fix.**

   ```sh
   python scripts/crucible.py --root ROOT fix run BLOCKER_ID [--yes-words "the user's words"]
   ```

   It refuses without a `blocker_fixes` grant (see `permissions.md`). With mode `each`, it also needs the user's yes for that plan: pass the user's own words in `--yes-words`. With mode `never`, no fix runs. Every run is logged in `actions.log`.

   The plan lists `touches`: every file, setting or behaviour the fix changes. The engine refuses a plan whose `touches` is empty, or that names an item the user said must never change in `project-brief.md`; that item is a question for the user, not an action.

4. **Backup first.** Before the change, the engine backs up what can be lost: the plan's `backup` files. Then it runs the plan's `change` command. If a backup is enabled and it fails, the fix is not made.

5. **Prove it.** The engine re-runs the check of the stage that was blocked. It must pass. If it does not, the blocker's status is `failed` and the report says so. The fix, the backup path and the proof go to the log and the report.

## How a fix lands

The user chose this in the interview (`blocker_fixes.landing`):

| `landing` | What happens |
| --- | --- |
| `pr` (default) | commits the touched files on the branch `crucible/fix-BLOCKER_ID`, pushes it (grant `blocker_pushes`), then opens one pull request per fixed blocker with `gh pr create`; the user merges |
| `local_branch` | commits on the branch `crucible/fix-BLOCKER_ID`; nothing is pushed |
| `push_branch` | commits on, and pushes (grant `blocker_pushes`), the branch the user named in `blocker_fixes.branch` |

The commit uses the user's own git config for the author, and the checkout stays on the fix branch so the next stage runs on the fixed code. The push is its own grant, `blocker_pushes`. If the commit, the push or the pull request fails, the blocker's status is `fixed-local` with the reason in `actions.log`, never `fixed`; the report lists it.

## Live changes

`blocker_fixes.live_changes` is `"never"` by default. A fix that changes a running system runs only for a system the user named in that list. Everything else is a question to the user, not an action.
