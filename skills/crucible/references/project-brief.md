# Project brief

`ROOT/project-brief.md` is written by `crucible brief`. It holds the user's answers to seven questions, word for word, next to an agent summary of what the project says about itself. The summary is labelled "agent-written, not confirmed", and every line of it names its source file.

The audit never works against the user. Every agent reads this brief. The verifier checks each finding against it, and the gate requires an `intent` field on every finding.

| Field | Question | Why it is asked |
| --- | --- | --- |
| `purpose` | What is the project for, and who uses it? | A defect is judged by who it hurts. |
| `good` | What must always work? | It ranks what is serious. |
| `intentional` | What is intentional, even if it looks odd? | An odd choice the user made on purpose is not a defect. |
| `must_never_change` | What must never change? | A fix must never touch these. |
| `accepted_risks` | Which risks did you accept on purpose? | An accepted risk is not filed again. |
| `out_of_scope` | What is out of scope or not a goal? | It is listed, not filed. |
| `known_issues` | Which issues do you already track or decided not to fix? | They are not filed twice. |

How a finding meets the brief (`intent`, `intent_kind`):

- No conflict: `intent` is `no conflict with the brief`. The finding is filed.
- Conflicts with what the user called intentional or must never change: it is not filed. It becomes a question in the report.
- Matches an accepted risk: it is marked accepted by the user and not filed, unless the user asks.
- Out of scope: it is listed in the report, not filed.
