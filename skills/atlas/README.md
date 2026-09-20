# Atlas

The skill an agent loads when asked to document a project, repo, or codebase.

## Contents

- [How a run goes](#how-a-run-goes)
- [The work directory](#the-work-directory)
- [The checker](#the-checker)
- [The roles](#the-roles)
- [Skill layout](#skill-layout)
- [Installing](#installing)
- [Design decisions](#design-decisions)

## How a run goes

1. **Scope.** The agent lists the candidate apps, packages and services and asks which are in. Nothing else is asked; audience and depth are read from the repository.
2. **Terrain.** Cheap commands: tree, manifests, configs, existing docs, recent git log. Then the seven toolchain questions are answered from this repository into `docs-work/toolchain.md`.
3. **Read it as one system.** The tree is cut into slices and each slice is scanned in parallel. Every non-test source file is opened, and the coverage gate proves it.
4. **Verify.** Scripts, environment variables, commands, versions and endpoints are checked against the code, not the old docs.
5. **Audit existing docs.** Every claim is classified as still true, stale or wrong. Originals are backed up before anything is written.
6. **Map.** One row per planned page: job, owned concepts, assumed pages, links, covered source, status. Settled with you before a page is written.
7. **Write.** Writers run in parallel batches, one page each. The session registers each page in navigation.
8. **Review.** Every page gets a fact-check and a reader review, each writing a verdict file stamped with the page's hash. A FAIL is fixed and re-reviewed in the same run.
9. **Report.** The report opens with the generated status block. DELIVERED means every row reviewed with every verdict passing. Anything else is INCOMPLETE with the fraction.

## The work directory

Everything the run produces beside the documentation lives in `docs-work/`:

```
docs-work/
├── scope.md          what is in and what is out, in your words
├── toolchain.md      the seven answers, derived from this repository
├── slices/           one scanner report per slice
├── map.md            the page map, parsed by the checker
├── reviews/          <slug>.factcheck.md and <slug>.reader.md per page
├── report.md         opens with the generated status block
└── skill-findings.md defects found in the skill itself, applied between runs
```

Keep it as the audit trail, or ask the agent to remove it at the end.

## The checker

```sh
python3 scripts/check_docs.py all --map docs-work/map.md --src src --docs docs
```

| Gate | Passes when |
| --- | --- |
| `coverage` | The union of every slice's opened-file list equals a real walk of the source tree. Secret-bearing files are skipped out loud and fail the gate if a slice opened one. |
| `map` | Every source path is covered by a page or excluded with a reason, every concept is owned by one page, every link and assumption names a planned page, every job is one sentence. |
| `reviews` | Every row is `reviewed` and carries two `Verdict: PASS` files whose `Reviewed-SHA` matches the page's current content. |
| `links` | Every internal link in the docs resolves to a file or a mapped page. |
| `status` | Prints DELIVERED or INCOMPLETE. Exits non-zero while any row is not reviewed, so it can be a stop condition. |
| `mermaid` | Renders the map as a graph. |

Exit code 0 is a pass. Anything else is not.

## The roles

Dispatch templates under `agents/`, not registered agents, so nothing needs installing in the target repository. Each is handed `docs-work/toolchain.md` so it works from this repository's conventions rather than from recall.

| Role | Model | Runs |
| --- | --- | --- |
| `scanner.md` | sonnet | Once per slice, in parallel. |
| `writer.md` | opus | Once per page, in parallel batches. Writes one file and nothing else. |
| `fact-checker.md` | opus | Once per page. Every claim to a line. |
| `reader.md` | haiku | Once per page. Reads the page, not the source. |

## Skill layout

```
atlas/
├── SKILL.md                     the workflow, gates and operating boundary
├── agents/                      the four dispatch roles
├── assets/map-template.md       the map in the shape the checker parses
├── references/
│   ├── voice.md                 the authoring position
│   ├── research.md              phases 1 to 3 and what may be run
│   ├── architecture.md          scope, destination, the map and its invariants
│   ├── writing.md               tiers, walkthroughs, examples
│   ├── review.md                the two reviews and delivery
│   ├── toolchain.md             the seven questions
│   └── project-types.md         where meaning hides per ecosystem
└── scripts/check_docs.py        the gates
```

## Installing

```bash
npx skills add NoMercyLabs/skills --skill atlas
```

Or install it as a Claude Code plugin: `/plugin marketplace add NoMercyLabs/skills` then `/plugin install nomercylabs@nomercylabs`, which gives you `/nomercylabs:atlas`.

To make ending early impossible rather than discouraged, wire `check_docs.py status` into your harness's stop condition. In Claude Code that is a `Stop` hook that runs it and exits non-zero while it fails.

## Design decisions

**Gates, not rules.** A rule in a prompt is a promise, and a broken promise costs nothing. Every phase ends in a file on disk, and four of them end in a command that can reject the work.

**A verdict is stamped with the version it judged.** Edit the page and the verdict goes stale. Without that, a fixed page keeps an old rejection and a rewritten page keeps an old approval.

**Nothing language-specific ships.** A pack saying tests end in `Test` is recall, and it is wrong in exactly the projects with a house convention. The toolchain answers are derived per repository.

**The run does not edit the skill.** Defects found mid-run go in `docs-work/skill-findings.md` and are applied once, between runs, so every page in a run was judged by the same rules.

**Secrets are never opened.** A real `.env`, key or keystore is not read, counted or quoted. The example file beside it is.
