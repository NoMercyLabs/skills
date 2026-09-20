# The three roles

Dispatch templates, not registered agents. Files under a skill directory are not
discovered as agents, only `.claude/agents/` is, so these are prompts handed to
the Agent tool, with `model` set per role. That keeps them portable into any
repository without installing anything.

Every dispatch is one role template plus `docs-work/toolchain.md`, which holds the
seven toolchain answers derived from this repository in Phase 1. Nothing about a
language is shipped with the skill: a general answer is recall, and recall is what
the voice forbids.

| Role | Model | Effort | Volume | Why that tier |
| --- | --- | --- | --- | --- |
| `scanner.md` | sonnet | medium | highest, one per slice, run in parallel | Copies signatures verbatim and flags drift. Cheaper than this and it returns honest-looking empty reports: the coverage gate proves a file was opened, never that anything was extracted from it. |
| `fact-checker.md` | opus | high | one per page | The insurance. It runs code, resolves URLs and traces provenance. Cheap insurance is no insurance. |
| `reader.md` | haiku | medium | one per page | Naivety is the qualification. A model that silently infers the missing step will not notice the step is missing. |
| `writer.md` | opus | high | one per page, batched in parallel | Writing is where a page is decided. A cheaper writer costs more, because a page that fails review twice spends three fact-checks and the fact-checker is the expensive role. |

Writers run in parallel because a serial writer is what makes a large set
unfinishable: reviews fanned out, writing did not, and a run filled its context
after a handful of pages.

Each writer writes one page file and nothing else. Navigation and any other
shared file is registered by the session that dispatched them.

The main session holds
the map, the ledger and the conversation with the user.

## Cost shape

Scanning is where the tokens are, a few hundred files against a few dozen pages, so the cheapest per-token role is deliberately the highest-volume one, and the
two expensive roles run once per page.

Nothing here is allowed to buy savings with coverage. The gates are unchanged
whichever model ran: the slice union is still diffed against a real walk, and a
page still needs two `Verdict: PASS` files.
