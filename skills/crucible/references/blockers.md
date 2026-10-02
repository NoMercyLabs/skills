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

   It writes `ROOT/fixes/BLOCKER_ID.json`: the cause with evidence, the change, the backup, how the fix lands (from the user's answer, default one pull request), and the proof command. Show the plan to the user. The method rules apply: find the cause, check siblings, and where code changes, a test fails first.

3. **Run the fix.**

   ```sh
   python scripts/crucible.py --root ROOT fix run BLOCKER_ID [--yes-words "the user's words"]
   ```

   It refuses without a `blocker_fixes` grant (see `permissions.md`). With mode `each`, it also needs the user's yes for that plan: pass the user's own words in `--yes-words`. With mode `never`, no fix runs. Every run is logged in `actions.log`.

   The plan lists `touches`: every file, setting or behaviour the fix changes. The engine refuses a plan whose `touches` is empty, or that names an item the user said must never change in `project-brief.md`; that item is a question for the user, not an action.

4. **Backup first.** Before the change, the engine backs up what can be lost (a file, a tracker field, a config, a running system's setting). If a backup is enabled and it fails, the fix is not made.

5. **Prove it.** The engine re-runs the check of the stage that was blocked. It must pass. If it does not, the blocker's status is `failed` and the report says so. The fix, the backup path and the proof go to the log and the report.

## How a fix lands

The user chose this in the interview (`blocker_fixes.landing`):

| `landing` | What happens |
| --- | --- |
| `pr` (default) | one pull request per fix; the user merges |
| `local_branch` | commits on a local branch; nothing is pushed |
| `push_branch` | a push to the branch the user named in `blocker_fixes.branch` |

## Live changes

`blocker_fixes.live_changes` is `"never"` by default. A fix that changes a running system runs only for a system the user named in that list. Everything else is a question to the user, not an action.
