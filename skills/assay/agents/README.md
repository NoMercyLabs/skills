# The two roles

Dispatch templates, not registered agents. Files under a skill directory are not discovered as agents, so these are prompts handed to the harness's agent tool, with the model tier set per role. That keeps them portable into any repository without installing anything.

Each dispatch names ROOT (the audit folder) and UNIT. Nothing else is shipped with the role: the config, the snapshot and the units are read from ROOT.

| Role | Tier | Volume | Why that tier |
| --- | --- | --- | --- |
| `reader.md` | balanced | one per unit, in small parallel batches | Reads whole files and traces callers. A cheaper model returns honest-looking empty reports; the proof command catches a file never opened, not a file read badly. |
| `verifier.md` | balanced | one per unit, a different agent from the reader | Tries to prove each candidate false. It must not be weaker than the reader it checks. |

The main session holds the config, the ledger and the conversation with the user. It runs `proof`, `verdict-check` and `accept` itself. An agent's report is never acceptance.

## Cost shape

Reading is where the tokens go, about 34 per line read including verification. The user's cap in `config.json` applies, and `assay status` shows spend against it. Dispatch in small batches and check the cap between them.

Nothing here buys savings with coverage. A cheaper tier changes nothing in the gates: every file must still be shown whole, and every candidate still needs a verdict.
