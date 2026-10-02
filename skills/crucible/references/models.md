# Models

`crucible models` writes the model plan from the user's scope and answers. It gives each role a tier, a one-line reason and a token estimate. Explain the plan in plain words. The user accepts it or changes it, and the answer is recorded.

Model availability is not checked. Say so: the user's plan may not include a model or may have its own limit.

## Tiers

| Tier | Maps to | Used for |
| --- | --- | --- |
| `fast` | Claude Haiku | readers of low-risk units: docs, tests, fixtures, generated and vendored code |
| `balanced` | Claude Sonnet | readers of normal and high-risk units, verifiers, first blocker fixes |
| `strong` | Claude Opus | critical-finding verifiers and the complex jobs when Fable is not allowed |
| `top` | Claude Fable | the four complex jobs below, only with the user's yes |

In another harness, map the tiers to its nearest models. Never put the verifier on a cheaper tier than the reader.

## Roles

- **No model where a script can do it.** Inventory, stamps, reading proof, verdict check, gate, scans, coverage and estimate cost no tokens.
- **Reader.** A script scores each unit from its paths and content. High risk (auth, sessions, crypto, payments, input parsing, public endpoints, deploy and infra config, migrations) and normal units get the reader tier from the config, `balanced` by default. Low-risk units get `fast`.
- **Verifier.** A different agent. It gets only the candidates and their cited lines, never the whole unit. A critical finding gets a verifier from the strong tier.
- **Blocker fix.** `balanced`. The strong tier only after one failed attempt, with the failure as input.
- **Complex jobs.** Group findings by shared cause, verify critical findings, find the root cause of a blocker after one failed fix, and set the final priority order. These are small inputs and few calls.

## Fable

Fable is a step up from Opus on the four complex jobs and nowhere else. Bulk reading and ordinary verifying never use it.

- Ask: "May I use Claude Fable for the complex jobs?" Name the four jobs, why each needs it, and show the estimate with and without Fable (`crucible models` prints both).
- Record the answer with the user's words: `crucible answer models.fable yes --words "..."` or `no`.
- `crucible confirm` refuses until it is answered. An unanswered question counts as no.
- Yes: the four jobs use `top`. No: they use `strong`.

## Haiku, Sonnet and Opus

These need no per-model permission. The plan is still explained and the user may change it with `crucible answer models '{"reader": "strong"}' --words "..."`. The `agent_runs` grant for budget and data still applies.

## Token numbers

The estimate follows the plan: `crucible estimate` prints the tokens per tier of the current plan. The per-line, verifier and judgment numbers are planning defaults until measured; do not quote them as prices.
