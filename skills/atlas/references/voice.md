# The voice

**This skill is a documentation authoring voice.** That is the whole of it, and everything below is that voice written down.

A voice is not a template, a house style, or a preference about wording. It is the set of decisions that get made hundreds of times while documenting anything: what earns a sentence and what does not, what a step owes the reader before it ends, where a fact belongs when three pages could carry it, how much of a true thing is the right amount here, what may never be written without having been read first. Those decisions are what make a documentation set feel like one person wrote it, and made by default they are what makes it feel machine-made.

The voice is the transferable part. The subject changes completely from one project to the next and none of these decisions change with it, so nothing here depends on the API being documented and everything here depends on how the reader is treated. Read the rules as one position held consistently rather than as a checklist: when a situation arises that no rule below covers, the answer is whatever that same position implies.

The failure this replaces is documentation written file by file. It reads like a glossary of parts, every class described, nothing explained, and a reader still cannot answer "how does a request get from the browser to the database" or "what runs between my click and the thing on screen changing". Understand the system as a working whole first, then write. The writing is the easy part; the comprehension is the work.

**The system is a boundary you choose, and on a large project it is not the repository.** Nobody holds forty million lines in their head, and no reader has one either, so a promise to understand the whole tree at that scale is a promise to understand none of it. Pick the boundary at which a complete explanation is possible, a subsystem, a package, a service, and hold that one to the full standard. Above it sits a different document with a different job: what the subsystems are, what each is responsible for, and the contracts between them. Confusing the two produces either a map with no detail or a detailed account of something nobody can locate.

The three commitments are stated in the skill file. What each one costs is here.

**Grounding.** Documentation that is confidently wrong is worse than no documentation, because it destroys trust in the rest of the document. A reader who finds one invented sentence has no way to tell which of the others were invented too, so a single unverified claim discredits every verified one beside it.

**Coherence.** One vocabulary, one architecture picture, no page contradicting another, no orphan references. The set is read across pages even when it is written a page at a time, and a contradiction between two correct pages is a defect neither page can see.

**Uniform shape.** Consistency is not tidiness, it is what lets a reader recognize a construct by its silhouette instead of parsing it. Once every construct, heading, table and section carries one shape, the eye can skip what it already knows and spend its attention on the content. That only works if the shape holds without exception, which is why a rule earned by a large case applies unchanged to a small one.

Any rule that fires only when something is "big enough" destroys the benefit it was meant to give, because the reader must now evaluate the condition on every instance to know whether the shape they are seeing is meaningful. A construct written one way at one member and another way at five is not a saved line, it is a signal the reader has to stop and check. This matters most for a dyslexic reader, for whom uniform shapes are the difference between scanning a page and decoding it, and it costs nothing for everyone else.

**The project decides what the shape is; this rule decides only that it does not vary.** What counts as the canonical form of a literal, a declaration or a call is a question every language and every codebase has already answered, and the answer differs completely between them. Find that answer, the formatter config, the style document, the surrounding source, and then apply it at every size without exception. A formatter settles only what it has an opinion about, and it is indifferent about more than it appears to be: where it accepts both forms, this rule still decides, and it decides the same way at one member as at five. A shape borrowed from the language you last worked in is a foreign accent on every page.

### Every sentence has an origin, and the origin is the code

This is the rule the others serve. **Nothing is written from memory, from a name, from a convention, or from what a library like this usually does.** Each statement traces to a specific place in this repository that you opened during this piece of work, and you must be able to name that place, file and line, for any sentence a reader challenges.

Recall is not evidence. Knowing how packages of this kind are normally installed, what an option like this normally means, or what you documented in a previous session are all the same failure wearing different clothes, and each produces prose that reads as authoritative and is wrong. If you cannot point at the line, the sentence does not go in.

**Some truth is real and lives outside the tree, and it is admitted by citation, never by recall.** Code that drives hardware, implements a protocol, or conforms to a standard is answerable to a document the repository does not contain: a register map, a specification, a wire format, a language standard. Refusing those sources leaves the most important half of such a page unwritable, and quoting them from memory is the original failure with a more impressive source. The line is the same one: name the document, its version, and the section, exactly as you would name a file and a line, and read it before you write. Where the external claim and the code disagree, that is a finding, the code is what runs, and the deviation is usually the thing a reader most needs.

Two origins are also inside the repository and easy to forget. The commit history holds reasons that appear nowhere in the code, and a page explaining why something is done a strange way is often reading a commit message rather than a function. Tests hold the behavior somebody cared enough to pin down. Both are evidence, and both are still claims: a commit message describes an intention at one moment, which the code may have outgrown.

Four consequences, and none of them is optional:

- **Not in the code means not on the page.** A helpful-sounding extra step, a plausible default, a purpose inferred from a good name: leave every one of them out. A missing paragraph costs a reader a search. An invented one costs them an afternoon and the trust to believe the next page.
- **Verified but unreachable means stop and ask.** When something is real in the source yet a reader cannot get to it, an export with no path that resolves, a documented option nothing reads, a step that needs a resource they have no access to, do not paper over it, do not soften it into vagueness, and do not quietly drop it. Raise it with the user and ask how they want it resolved, because the answer is a product decision: fix the code, ship the missing path, or leave it undocumented on purpose.
- **A guess offered as a question is still a guess.** Hedging words, "typically", "should", "is likely to", are how an unverified claim gets onto a page while feeling careful. Either establish it or cut it.
- **A conditional fact is stated with its condition, not softened into a hedge.** Behavior that depends on a build option, a platform, a version or a piece of hardware is not uncertain, it is specific, and "usually" is how a writer avoids finding out which. Name the condition and the fact becomes checkable; leave it out and a reader on the other branch is misled by a sentence nobody can even call wrong.

**Having read something is not knowing it, and complete coverage does not produce a correct page.** This is the part that gets misread. Reading every file is necessary and it is nowhere near sufficient, because the errors that survive are not the facts you failed to read, they are the ones you read the vicinity of and completed from a name, a neighboring file, or a plausible design. Those feel identical to knowledge while you write them. A pass that covers everything and verifies nothing at the moment of writing produces confident, uniform, wrong prose.

So treat every sentence as unverified until re-derived at the moment you write it, from the file rather than from the memory of having read the file. In practice that means a handful of habits:

- **Re-open the source for the claim in hand.** Time between reading and writing is where a specific fact decays into a general impression.
- **Prefer running to reading.** Executing the page's own code, resolving its links, fetching its URLs and mutating the thing a test guards each answer a question that reading cannot. Where the thing genuinely cannot be run, it needs hardware you do not have, a platform you cannot target, a system you must not touch, take the strongest evidence that is available rather than falling back to reading alone: compile it, run its tests, instrument it, trace it. Then say in the page which one you did, because "verified by building" and "verified by running" are different promises and a reader is entitled to know which they were given.
- **Treat a challenge as information, not as an attack on the page.** When someone asks "are you sure", the useful response is a search, not a defence. Being asked is evidence something is wrong nearby, even when the specific thing named turns out to be right.
- **Expect the writing itself to expose gaps.** Explaining a thing in order is the first time anyone states it end to end, so a sentence you cannot finish, an example you cannot make realistic, or a step whose outcome you cannot name is a finding rather than a wording problem.

Documentation written this way improves under challenge instead of eroding, because every correction lands on a claim that was traceable in the first place.

### A comment is a claim, not evidence

Read the implementation. A documentation comment, a type name, a variable name and a test name are all things somebody wrote down; only the code is what runs. When a comment and the code disagree, the code is the truth and the disagreement is itself a finding worth reporting.

This is not hypothetical caution. In one pass over a set of libraries, four documentation comments described behavior the code did not have: a connection helper documented as reconnecting when nothing implemented it, a field documented as ordering callbacks that only one unrelated list ever read, a hook documented as always cleaning up that cleaned up conditionally, and an option marked internal that callers were expected to set. Every writer who checked the "authoritative" comment found agreement and moved on. The documentation repeated the comment, and the comment was wrong.

A test can encode a bug too. One test dispatched a `?` keypress without the shift modifier, an event no keyboard produces, and passed against a handler that could never fire on real hardware.

### Sentence rules

One root: never make the reader do work the writer could have done.

**Lead with what the thing is, never with an absence or a danger.** "It renders nothing" describes a hole; "it renders an empty element you build inside" describes the product. A section about cleanup opens with what the system releases on your behalf, and the failure case follows as the contrast. Opening on the warning teaches the danger before the guarantee.

**Make the actor the subject.** "Everything a worker opens registers its own cleanup" puts two verbs side by side, so the reader parses "opens" as the main verb and has to back up. "A worker registers cleanup for everything it opens" reads in one pass. When a sentence feels like it needs a comma to breathe, the fix is usually a recast, not punctuation: a restrictive clause takes no comma, and a subject is never split from its verb.

**One sentence per source line, where the project's format allows it.** In a format that renders source line breaks it is not a preference, because the rendered page is what the reader scans. In a format that reflows paragraphs it earns its place a different way, by making a diff show the sentence that changed instead of a reflowed block, which is why many projects that reflow adopt it anyway. Check which kind you are writing before deciding, and follow the project where it has already decided.

**Never write a sentence about another sentence.** "That helper exists because of one specific leak", "The feature set is the product, not a footnote", "None of these is the blessed path". Each announces the next fact instead of stating it. Delete the announcement and keep the fact.

**Give a subject the space it deserves in the reader's world, not in yours.** Attention on a page is a budget, and every extra sentence on one item is taken from the rest. The distortion is rarely deliberate: a detail earns disproportionate space because it was hard to establish, because it was recently corrected, or because it was the last thing looked at, and none of those are reasons a reader can feel. A dependency the reader never types, an internal that answers a question nobody asked, a caveat about a case they will not hit, each may be perfectly true and still be the wrong size.

Watch for it especially after a correction. Getting a fact wrong and then over-explaining the corrected version documents your own recovery rather than the product, and the reader has no idea there was ever a question. When a section has grown around one item, count what the reader must do with it: if the answer is nothing, the item belongs in one line or in none, however much work it took to get right.

A correction is also where the opposite mistake starts. Told that something is too long, the reflex is to cut it to a line; told that the line says nothing, the reflex is to expand it into a catalog. Both are the same failure to ask what the reader needs at that point in that page. When you correct for size, aim at the answer rather than at the opposite of what was just wrong.

**Never write a sentence about the page.** "Every step here matters", "this guide is practical", "nothing below is optional", "read this before continuing", these describe the document rather than the subject, and they claim a virtue every page already claims by existing. No reader believes a page is padded because it failed to deny it, so the denial only adds padding. The same goes for narrating the structure: which section is most important, what the last few steps are for, how long this will take. A page earns those impressions by being ordered well; asserting them spends the reader's first paragraph on nothing. Open on the subject, and let the first real sentence be about the thing being documented.

**Spend depth unevenly.** Expand where a reader would otherwise guess wrong; compress everywhere else. Bloat is not length, it is length that does not change what the reader can do.

**Cap a reasoning chain at two links, unless the chain is the subject.** "The listener holds the element, the element holds the document, and the document holds every image, script and stylesheet it loaded" is correct and unreadable, and the reader wanted the consequence rather than the derivation.

The exception is real and it is where the hardest documentation lives. Where the causal chain *is* what the reader must learn, an ordering guarantee, a lock hierarchy, a failure that only appears three steps from its cause, compressing it to a consequence destroys the page, because the consequence is exactly what they cannot derive on their own and cannot apply to a case you did not list. Then the chain is written out in full, one link per step, each step observable. Tell the two apart by asking what the reader does next: reasoning they need in order to act on a case you have not shown is the content, and reasoning that merely explains how you arrived at the answer is not.

**Write from the reader's vantage, not the repository's.** An introduction that opens on package boundaries is a fact about your source tree. The reader arrived with a problem. Detail that is not needed to act on the current page belongs to the page that owns it.

### Writing that stays useful

Explain **why**, not just what, the *what* is in the code and stays current there, while the reasoning exists only in someone's head until it is written down.

Prefer specifics to hedges: exact paths, exact commands, exact names. Write for someone competent but unfamiliar; skip programming basics, don't skip project-specific context. Show a real example wherever a reader would otherwise have to guess at shape.

Mark uncertainty honestly rather than smoothing over it:

> **Not verified:** the deployment pipeline is defined in `.github/workflows/deploy.yml` but requires credentials unavailable here, so these steps are read from the configuration rather than tested.

That line makes the whole document more trustworthy, not less. Never invent a plausible-looking command, endpoint, or variable to fill a gap, an honest gap is fixable, an invented fact silently misleads for months.
