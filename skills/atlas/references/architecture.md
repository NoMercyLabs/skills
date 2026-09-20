# Scope, destination, and the documentation map

## Phase 0: Settle the scope

"Document this repository" does not say how much. A repository holding several applications, packages or services can mean all of them, one of them, or the three someone actually cares about, and the difference is the whole size of the job. Guessing wide wastes weeks; guessing narrow delivers something the user considers unfinished.

Enumerate the candidates first, the applications, packages, services or modules a reader would think of as separate things, then put the choice to the user. Offer the whole set as one option and a selection as the other, and when they choose to select, present the full list so they can tick what they want rather than typing names from memory. Ask this as a real question with the options listed, not as an open prompt: someone who has not seen the inventory cannot answer accurately, and an inventory they can read is also the first proof you understand the shape of their repository.

Ask what is deliberately excluded in the same round, because it changes the plan rather than the wording. Internal-only packages, deprecated modules and things about to be rewritten are all common, and each is cheaper to hear now than to discover after a page exists.

**Ask nothing here that reading would answer.** This phase runs before the existing documentation has been found, let alone read, so it is the easiest place in the whole workflow to spend the user's attention on a question the repository settles. Scope and exclusions qualify because no file states them. Audience, depth, tone and structure do not: where documentation exists it has already answered them, and where it does not, they are settled at the map, after reading, as a proposal the user corrects rather than a blank question they have to fill in.

Record the answer at the top of the documentation map. Scope that lives only in a conversation gets relitigated.

## Phase 4: Audit and back up existing documentation

Read all existing documentation completely before deciding anything about it. It usually contains knowledge that is nowhere in the code: rationale, history, hard-won operational advice, warnings. That content is expensive to lose and impossible to regenerate.

Classify each meaningful claim as **still true**, **stale**, or **wrong**, checking it against the code rather than against plausibility. Carry the true parts forward, rewritten to fit the new structure and voice, but with their substance intact.

Then back up before writing anything new:

```
docs-backup-<YYYY-MM-DD-HHMM>/
```

Copy the original files in there with their structure preserved. Never move originals, copy them, so the project keeps working if someone is mid-review. Mention the backup location to the user when reporting results.

## Phase 5: Choose the shape

**First: does a documentation system already exist?** A project with a docs site, a navigation manifest, a content collection, or its own build gates has already chosen its shape. Extend it. Do not regenerate a flat `docs/` folder beside it and do not back it up as though it were a draft, because the site IS the product. In that case the real Phase 5 work is finding the existing conventions: where content files live, what registers a page in navigation, which gates run in the build, and which components the site can render. Match all four, then write.

**Match the platform, judge the prose.** Those four are mechanics, the site breaks without them, and inheriting them costs nothing. Tone, density, page shape and how much a page tries to carry are not mechanics, and copying them is how a rewrite reproduces the thing it was asked to replace. Being asked to redo documentation that already exists usually means the prose failed, so the existing pages are evidence of what the reader is getting, not a specification of what to write.

Say which of the two you are inheriting when you report. "Matched the site's conventions" reads as one decision and is two, and the user cares far more about the second.

### When there is no system yet, the destination is the user's call

Where a project has never had documentation, do not default to a `docs/` folder because it is easiest. Where the documentation lives decides how files are named, how deep they may nest, how pages link to each other, how navigation is expressed and whether anything can be rendered live, so the map cannot be drawn until it is settled.

Arrive at that question with researched options rather than a blank prompt. Before asking, look for what this user already leans towards:

- Config or dependencies for a documentation generator sitting unused in the repository, or in their other repositories.
- How their existing READMEs are written, and whether the project already leans on a static site generator whose ecosystem includes a documentation theme.
- Their public presence, where they have one: a personal site, a documentation site for another project, a profile that links somewhere. What they already ship is the strongest available signal of what they will want to maintain.

Then put the real choices to them, with the consequences attached rather than the names alone:

- **Plain Markdown in the repository.** Nothing to build, reads on any host, and navigation is manual.
- **The hosting platform's own wiki.** First-party and immediate, with its own conventions for structure and sidebars, and generally flatter and more constrained than a site you build.
- **A documentation framework.** Search, versioning, navigation from a manifest, deep nesting, live examples. Costs a build and a dependency, and each one imposes its own file conventions and authoring workflow.
- **A specific theme or template they already have in mind**, including a paid one, and possibly ported to a generator they prefer.

The last case is common and worth asking about explicitly, because someone who has already chosen an aesthetic will reject a technically fine alternative. When a framework is chosen that you have not worked in, research its conventions before drawing the map, file layout, navigation, linking, and what its build enforces, since a map drawn against the wrong conventions has to be redrawn.

The shapes below apply when the project has no documentation system and the user has no preference.

Scale the output to the project. Documentation that is heavier than the thing it documents just goes stale.

- **A single script or micro-project** (a handful of files, one purpose): one `README.md` covering everything. Splitting this into folders makes it worse.
- **A normal project** (multiple subsystems, a real build, several contributors): `README.md` as the front door plus a `docs/` directory. This is the common case.
- **A large or multi-package project**: `README.md`, a `docs/` directory with a clear index, and per-package READMEs that link back up rather than repeating the shared material.

Say which shape you chose and why when you report back, since the user may disagree, and changing it later is cheap only if it is surfaced early.

### Settle the architecture before writing a single file

Writing eagerly and organizing later is how a documentation set ends up duplicated, contradictory and half-finished. Every page written before the map exists is a page that may have to move, merge or be deleted, and each one silently commits you to decisions you have not made yet, which topic owns a concept, which tier carries the detail, what a page is allowed to assume its reader already did.

Produce the map first, and get agreement on it:

- **The page list**, with each page's tier and its one job. A topic appearing twice at the same tier is a merge to resolve now, not after both are written.
- **Ownership of every shared concept.** One page holds the full explanation, and the others carry a short purpose paragraph and a link. Decide which, before either is drafted.
- **The dependency order.** A guide that defers detail needs the page it defers to. Every page a deferral could reach is a row before writing starts, and the order in which they get written is then a scheduling question rather than a correctness one.
- **The reader's route.** What a page assumes has already been read, and where a reader goes next.

Keep a concept ledger as you go: one line per concept, naming the page that owns it and the pages that may reference it. It costs a few lines and it is the only thing standing between a set and its most common flaw, which is telling a reader something they were told two pages ago.

Keep it small on purpose. The temptation is to build a full map of the documentation, every page, every link, every topic, cross-referenced, and that map is a second artifact to maintain, drifting from the pages the same way documentation drifts from code, except that nothing checks it. A stale map is worse than none, because it is consulted with confidence.

Most of what such a map would hold already exists and should be read rather than copied:

- **The route is the project's own navigation.** A sidebar manifest, a table of contents, a nav config: whatever orders the pages already answers what a reader has seen before this page. It is maintained because the site depends on it, so it cannot silently rot.
- **The references are the links themselves.** Where the project checks links in its build, that check is the map of what points where, kept honest automatically. Where it does not, a sweep at the end is cheaper than a register maintained throughout.
- **Ownership is the one thing nothing records.** No file says "the event model is explained here and only here". That is what the ledger is for, and being the only unrecorded dimension is what keeps it to a handful of lines.

So: read the nav for order, trust the link check for references, and write down only which page owns which concept. If a project has real tooling for the rest, use it and keep the ledger even smaller.

That flaw is invisible from inside a page. Every page is written as though it might be the reader's first, each explanation is correct, and nothing looks wrong until someone reads them in order and meets the same paragraph three times. By then the fix is expensive, because the explanation has been woven into three different arguments.

So before explaining anything, check the ledger. If a concept is already owned, the later page names it and links, in a clause rather than a section: enough to carry the reader through the sentence they are in, never enough to re-teach. A concept you find yourself explaining twice is telling you the ownership decision was wrong, resolve that rather than writing the second explanation better.

The distinction worth holding is between reminding and re-teaching. Reminding is a phrase that reactivates something known and keeps the sentence moving. Re-teaching is the full account arriving again, and it reads as either the page assuming they learned nothing, or the set having lost track of itself.

The cost of this is one planning pass. The cost of skipping it is rewriting pages that were fine in isolation and wrong together.

### Write the map to a file, and settle it with the user

Do not hold the plan in your head or scatter it through a conversation. Produce one file, call it the documentation map, as the last act of research and the first thing the user sees. It is the artifact you both point at, and the moment to disagree about structure is while it is a list, not after twenty pages exist.

Scale the map to the project, and keep it in every case. A single script needs three rows and takes a minute. A large repository, or a monorepo documenting many packages across hundreds of pages and thousands of source files, cannot be planned by intuition at all: there, every structural mistake made without a map is discovered late and paid for in rewrites. The small version costs almost nothing, so there is no size at which skipping it is the cheaper choice.

The map has one row per planned page:

- **Page**: its path, and its tier.
- **Job**: one sentence. A page whose job needs two sentences is two pages.
- **Owns**: the concepts explained here and nowhere else. Most pages own nothing and that is correct.
- **Assumes**: the pages a reader has already been through.
- **Links to**: the pages this one defers to.
- **Covers**: the source paths this page is answerable for. It is where the page's evidence lives, and `Job` is what the page answers; before dispatch, check that every public member under a `Covers` path is claimed by some row's `Job`, because a member that falls between two rows is written by neither.
- **Status**: planned, drafted, reviewed.

Render it however it gets read. A table is enough; a tree or a diagram of the route helps when the shape itself is what is being argued about. The format is disposable, the four invariants below are not.

### One page is the reference, and the rest are matched to it

A list of rules produces pages that each obey the rules and still do not sound like one person wrote them. Rules settle what is allowed; they do not settle the hundred small shapes that make a set recognizable, how an outcome sentence reads, how a table's cells open, how a caveat attaches to a step, how a page closes.

So the set gets one page that is right, and every later page is matched against it rather than against the rules alone.

Where the user has approved a page, that is the reference and there is nothing to decide. Where none exists, write one first, a page whose subject is rich enough to exercise the shapes, which usually means a walkthrough rather than a reference entry, and settle it with them before the rest. A reference page agreed early is worth more than the same conversation repeated over twenty drafts, because every correction to it is a correction to all of them.

Name it on the map, and hand it to the reader reviewer alongside the page under review. "Does this sound like it came from the same set" is a question a reviewer can only answer with both in front of them, and it is the question that catches drift no rule names.

Where a project has house rules of its own, they still outrank the reference page, and the reference page outranks anything in this skill.

### The four invariants that make a map worth having

A map that merely lists intentions is a wish. What makes this one hold is that it can be checked by reading it, with no tooling at all:

1. **Every source area appears in some page's "covers".** An area claimed by nothing is an admission that part of the project is undocumented, which is a decision to make deliberately, not a gap to discover a year later.
2. **Every page covers something.** A page answerable for no source is a page invented to fill a shape, and it will be padded to justify itself.
3. **Every concept is owned exactly once.** Owned twice, a reader is taught it twice. Owned zero times, every page assumes another page explained it and none did.
4. **Every "links to" names a page on the map.** A link to a page nobody planned is a hole; it either becomes a row or the deferral becomes inline detail.

Check those four before writing, and again before delivering. Three of them are counting, and counting is exactly the thing that does not degrade when the set gets large.

The map is also the honest answer to coverage. "We documented the project" is unfalsifiable; "these source areas are covered by these pages, and these three are deliberately not" is a claim someone can audit, including the person who has to trust it.

### Ask what only the user can answer

Some decisions are the user's and cannot be derived. Ask them before writing, in one round rather than as they arise.

Ask only for what the project does not already answer. Where documentation exists, its conventions are the answer, and asking about something already settled by the current docs is a sign of not having read them.

The test is whether the answer exists anywhere in the repository. What survives it is usually intent rather than fact: what the product wants emphasized, how much the set is worth investing in, a plan that is not in the code yet, and anything where two reasonable choices produce very different documentation.

Where a question would otherwise be legitimate but the repository half-answers it, do not ask it open. Derive the answer, put it on the map as a proposal, and let the user correct one line instead of composing a paragraph. An audience already visible in how the existing documentation is organized is derived, not asked.

Never ask a question whose answer is a project-specific fact you could have looked up. That is research disguised as consultation.
