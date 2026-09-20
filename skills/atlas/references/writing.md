# Writing

Write in the language the project's own documentation and code comments use, regardless of the language of the conversation.

**The project's conventions outrank your habits, and they have to be found rather than assumed.** Before writing, settle: which spelling variant, which punctuation the project avoids, tabs or spaces and how wide, how identifiers are cased, and any terminology it insists on. A contributor guide or an agent-instruction file states them outright where one exists; otherwise infer them from the existing documentation and from a linter or formatter config, which is the version that is actually enforced.

Apply them to identifiers in examples too, not only to prose. A reader copies the identifier, and a spelling that disagrees with the codebase spreads from the page into their project.

Code in the documentation is held to the same shape as code in the repository, because a reader copies it and because a cramped snippet is exactly as hard to scan as a cramped source file. Format every example the way the project's own formatter and lint config would, never the compact form that fits a chat message. Vertical space carries meaning, so a snippet gets blank lines between its logical steps rather than being packed tight. A guard clause is always followed by a blank line, because the guard and the work it protects are two thoughts and running them together is what makes a short function look dense. Setup, action and assertion separate the same way. The reader should be able to see how many steps a snippet has before reading any of them, which is the same reason prose here gets short paragraphs with space between them: a wall is hard to enter regardless of whether it is made of sentences or statements.

Where the project ships a formatter, run it over the extracted snippets rather than imitating it by eye. It settles every question it has an opinion about, and it settles them the way the project already answered them.

**A formatter is indifferent about more than it looks, and indifference is not permission.** Most will preserve whichever form the author wrote for a small literal, so running one over a cramped snippet returns the cramped snippet, formatted. Wherever the tool accepts both forms, the choice is still yours and the rule below decides it.

A construct that carries a body, an argument list, a literal collection, a set of named fields, breaks across lines at one member as readily as at five. Not when it grows too long: at one member, always. The shape is what the reader recognizes, and a shape that changes with size is one they have to measure before they can trust it. A construct that is a pattern being matched rather than a body being built stays inline, and that is its own shape held to just as firmly. Which constructs fall on which side is a question about the language, not about this rule: in one it is a destructured parameter, in another an initializer, in another a keyword argument list. Take the answer from the surrounding source, and hold it without exception.

**Write for a reader who scans, not one who reads.** This is the rule with the widest reach on the page, and it is the first one to go when a sentence gets interesting to write. A dense page is not a page with too much in it: it is a page that cannot be entered, and a reader who cannot enter it does not read it more slowly, they leave.

Five things make the difference, and each one is checkable without judgment:

- **One idea per sentence.** Two clauses joined by a comma are two sentences.
- **One sentence per line**, where the format allows it.
- **Three sentences to a paragraph**, then a blank line. A fourth is a new paragraph, not a longer one.
- **Four parallel facts are a table**, never a paragraph.
- **Nothing between a step and its outcome.** A caveat goes after the result, not before it.

Long is not the problem. A page of short paragraphs can be long and still read easily. A single paragraph of six joined sentences cannot, however true every one of them is.

Three more that cost nothing to hold. No filler opener that restates the heading. A page states what is true now and never narrates what changed, so no "previously", "superseded by", or "used to". Never document a non-functional option: fix it or leave it out.

The audience is deliberately mixed: someone joining the project, someone maintaining it a year from now, someone just trying to run it, and someone integrating against it. Serve them by separating concerns into documents with a single job each, rather than by writing one document that hedges between audiences.

### The README

The front door. Someone should be able to tell within thirty seconds whether this project is what they need, and be running it within ten minutes.

```markdown
# Project name
One or two sentences: what it does and who it is for.

## What it does
A short paragraph of real substance, the problem being solved, not marketing.

## Requirements
Concrete versions, verified against manifests and CI.

## Getting started
Numbered steps, copy-pasteable, ending in something the reader can see working.

## Configuration
The variables that must be set to start. Full reference lives elsewhere and is linked.

## Project structure
The handful of directories that matter, one line each.

## Documentation
Links into docs/, with a line describing what each one answers.
```

Keep the deep material out of the README and link to it. A README that tries to be complete stops being usable.

### The docs/ directory

Include what the project actually warrants, an empty section is worse than a missing one:

- **`architecture.md`**: the system as a whole. Components, responsibilities, how they communicate, and at least one complete end-to-end trace from Phase 2. Include a diagram in Mermaid where it earns its place; a picture of five boxes and their arrows beats three paragraphs describing the same thing.
- **`getting-started.md`**: full local setup for someone who has never seen the project: prerequisites, install, configuration, running, and how to tell it worked. Include the failure modes you hit while verifying.
- **`configuration.md`**: every setting: name, purpose, type, default, required or optional, and what happens with a wrong value.
- **`api.md`**: for anything others integrate with. Endpoints or public exports with parameters, return shapes, errors, and a realistic example per operation. Generated where a spec exists; hand-written where it doesn't.
- **`development.md`**: how to work on it: branching, tests, linting, build, conventions the code actually follows, and how to add a typical new feature.
- **`deployment.md`**: where it runs, how it gets there, what it needs, and how to tell whether it is healthy.
- **`data-model.md`**: entities, relationships, lifecycles, migrations, where state lives.

Naming and division should follow the project. A Unity project may need `scenes.md` and `input.md` more than `deployment.md`; a library needs a thorough API reference and barely any deployment section.

### Use the project's own components, not plain Markdown

A docs site that ships custom directives has already solved presentation. Writing a fenced code block where the project has a live-example component produces a page that works and looks like it came from somewhere else.

Find the directive set before writing. Wherever the site registers its content pipeline, plugins, shortcodes, components, macros, depending on the generator, that registration is the inventory. Read it, then count what existing content actually uses, because a directive that ships and is never used is usually unfinished, and one used on every page is the house style.

Write the inventory down before drafting, one row per directive, recording for each: what it is for, what it takes, and whether the build checks anything about it. That last column is the one that matters, a directive whose content is compiled, type-checked or executed cannot drift from the code it shows, which makes it worth reaching for even when a plain block would read the same.

Sort the inventory into what the site can do that plain text cannot: run an example, render reference rows from data, mark an aside so it does not read as body text, carry a symptom with its cause and fix, and lay out navigation. A gap in that list is a page shape the project has decided not to support, and writing around it beats inventing a directive that does not exist.

**A rendered snippet has to contain every call the prose around it names.** A directive that pulls part of an example file will happily show the config object while the paragraph beside it discusses the constructor and the setup call, and the page then describes code the reader cannot see and cannot copy. Read the rendered output, not the directive: whatever the page talks about is in the block, or the block is the wrong slice of the file.

Where the project can render a live example, a page teaching a visible feature uses it rather than a fenced block, because the reader can then watch the thing run. Write the example as a real file in whatever directory the project compiles, so the build proves it, and reference it from the page.

### One page, one job

A reader who lands on a topic should find it whole, not half of it in two places. Three tiers, and every page does exactly one of them:

- **Introduce**: what it is, why it exists, when you reach for it, the mental model. Never enumerates an API.

Tier one usually wants two pages rather than one, because they do different jobs for different readers. An **introduction** is the page someone arrives on, often from a search, and its job is to let them decide whether this is for them: what the thing is, what shape it has, what it can do, why it was built this way. It is the only page where making the reader interested is a legitimate goal. A **quickstart** assumes they already decided, and gets them to something working with as little friction as possible, and while doing that, it shows how the project thinks, which is the part that makes the rest of the documentation feel predictable. One page cannot do both well: framing slows down the reader who wants to start, and starting immediately never explains why they should.
- **Detailed examples**: how you actually do it, with code that runs.
- **Full API spec**: the exhaustive catalog. The only tier allowed to be complete.

A topic gets at most one page per tier. Two pages in the same tier on one subject is a merge.

Not every topic wants three pages. A single component, command or endpoint is a **catalog entry**: one page carrying purpose, usage and reference as sections in that order. Splitting one of those across three pages produces pages nobody wants. The three-page arc is for the things a reader sits down to learn.

The failure this prevents is measurable. Where a topic is split, the two pages share almost no wording but name nearly the same symbols, so it does not look like duplication in a diff and reads as a gap to the reader. Symbol overlap between two pages on one subject reaching most of the smaller page is the signal.

**The tier decides how much of a true fact belongs on the page.** A detail can be correct, verified, and still the wrong size for where it sits: a complete list of accepted formats, every option a call takes, every error a call throws. In an introducing or example page, give the shape of the answer with one or two concrete anchors, then link to the tier that carries the rest. The reader of a walkthrough needs to know whether their case is covered and where to look when it is not; they do not need the catalog mid-step. Answering with an exhaustive list there is the same defect as answering with nothing, because both stop the reader from moving.

Every page a deferral could name is already a row before any writing starts, so at this point the link resolves by construction. Reaching for one that does not exist is not a hole to note and move past: it is the map being wrong, discovered from inside a sentence.

Stop there and settle it on the map, with the user if the answer changes the shape. Either the page becomes a row, planned, and the delivery gate fails until it is written and reviewed, or the deferral was mistaken and the detail belongs inline in the page you are writing. Then go back to the sentence.

Writing on past it is how the set acquires a permanent gap. A note that a page is outstanding lives in a session that ends, while the dangling link ships.

### Writing a walkthrough

A page that takes someone from nothing to a working result, a quickstart, a setup guide, a tutorial, carries four obligations the other shapes do not.

**Reach a working result early, then layer.** The first thing a reader wants is evidence that any of this works on their machine. Order the page so the smallest thing that runs comes as early as the subject allows, and treat everything after it as adding one capability at a time. A page that spends five steps on preparation before anything can be observed asks for trust it has not yet earned, and a reader who hits a problem in step two has no idea whether they broke it in step one.

**Every step says what the reader should now see.** A step whose outcome is unstated cannot be checked, so a reader who has quietly failed carries the failure forward and discovers it somewhere unrelated. State the observable result in the reader's terms, what appears, what changes, what becomes possible, and where a step has a common way of going wrong, name the symptom next to it. That turns a silent failure into a diagnosis without a paragraph of troubleshooting.

**The outcome sentence has one shape, and it is marked.** A reader scanning for "did that work" should find the answer without reading the step again, so the sentence naming the result is written the same way every time, second person, present tense, about what is now on their screen, and visually distinct from the prose around it. Once it has a silhouette they can skip everything else and still check themselves at every step. Where the step can fail visibly, the symptoms follow immediately and each names its cause: one sentence per way it goes wrong, in the order the reader would meet them.

**Steps are numbered and headed by the action.** A heading that names what the reader does, install it, give it a container, wait for it, lets someone returning to the page find the step they are on without reading. Numbers matter for the same reason a later step can then say which earlier one it modifies, by number, instead of by description.

**Name the exit ramp.** A walkthrough that adds capability in layers passes several points where a particular reader already has what they came for, and saying so is not an admission that the rest is optional padding. It respects that they came with a smaller problem than the page solves. One clause is enough, at the point it becomes true.

**Alternate doing and understanding.** The balance a walkthrough is judged on is not how much it explains, it is the rhythm: a thing to do, then the short reason it works that way, then the next thing to do. A reader who only acts finishes with a working result they cannot adapt; a reader who only reads never gets the evidence that any of it runs. Keeping the two interleaved means someone arrives at the end with a running result and a model of it, having felt taught rather than instructed.

The measure of a good explanation between steps is that it changes what the reader would do next or what they would expect to see. Anything that fails that test is padding no matter how true it is, and the step it interrupts was better without it.

**Give a reader the model, not just the move.** Every step introduces something the reader now has to reason about, and the step is only finished when they can picture it. A container is not "an element you provide"; it is the thing that becomes the root, carries the state your CSS can hook, and holds the pieces in an order that decides what sits above what. A method is not "how you set the volume"; it is where that value lives and what else observes it. State what the thing becomes, what it holds, what it exposes, and what a reader may bring of their own, because that is the difference between following the page once and being able to work without it.

The failure this catches is a true, complete, useless sentence. It answers the step and leaves the reader unable to do anything the page did not literally show, and it reads as finished, which is why it survives review. When a line names something the reader will carry through the rest of the page, three or four sentences of model are worth more than any later paragraph of prose.

**Where a system supports two ways, recommend one and price the other.** A step that shows a single path leaves the reader guessing whether the other thing they were about to try is wrong, unsupported, or simply undocumented, and they find out later in a context where it looks like their mistake. Naming both is not a digression; it is the difference between following instructions and understanding the system.

Do it in one move: say which order to prefer and why, then what changes if they do it the other way. Two sentences is usually enough, and the shape is what keeps it from overwhelming, a recommendation first gives the reader a default they can take without deciding anything, and the alternative arrives as information rather than as a question they must answer. Presenting the options as equals is what creates the paralysis, not the existence of the second one.

**Explain between the steps, do not stack them.** A sequence of bare instructions is faster to write and worse to learn from, because it never says why any step exists, and a reader who does not know why cannot adapt it to their case. A few sentences between steps, carrying the reason or the consequence, is what turns a list into something someone can follow into their own project. This is not license to pad: the test is whether the sentence would change what the reader does or expects.

**Show an addition as an addition.** Once a page has established a call, a later step that adds to it shows the new lines and says where they go, not the whole call again with the new parts inside. Restating it makes the reader diff two blocks to find what changed, and it contradicts the earlier step by implying the call happens twice.

The danger is worse than redundancy. A restatement is almost never complete, because the instinct is to trim it to what the section is about, and the result is a *different, broken* call: fields the reader had are silently missing, so copying it over their working code removes settings they need and sends them debugging the wrong thing. The shorter the restatement, the more it deletes.

The opposite extreme fails too. A bare line with no surroundings makes the reader work out where it belongs, and a wrong guess is the same misconfiguration by another route.

The shape that works keeps the enclosing structure and elides the rest: the call or block that anchors the position, an ellipsis where the unchanged parts were, and the new line in its place.

```js
fetch('/api/items', {
	...
	cache: 'no-store',
});
```

The ellipsis is doing real work, it marks the snippet as a fragment so nobody reads it as complete, and it says the omitted parts stay as they are.

**It only works if the reader has already seen what it elides.** An ellipsis is a pointer back to a complete form, so with nothing to point at it is not an addition, it is a fragment of a call the reader has never met, and they cannot tell what the omitted parts were, whether they have them, or where the block goes. Two placements make it legitimate: the full form appears earlier on this page, or it appears on a page this one's map row lists under **Assumes**, which is the record of what the reader arrived having read. Nothing else counts, not another page that happens to exist, and not a form shown in a different tier the reader had no reason to open.

Where neither holds, the complete form is what goes on the page, once, and every later step elides against it. A first appearance is always whole.

Where the reader has several of the thing, keep enough identifying members to say which one.

```js
{
	name: 'my-package',
	...
	sideEffects: false,
}
```

Where the project marks partial snippets, use that marker as well.

**An addition names the step it goes in.** "Two additions to the call from step 4" places the fragment exactly, and it costs three words. Without it the reader has the new lines and a search, and on a long page they will paste into the wrong block.

**When a design will read as a defect, say it is deliberate, immediately.** Two plugins for one capability, two ways to configure one value, a method that exists only to be overridden: a reader meeting one of those assumes an accident and starts working around it. Name it as a choice in the same sentence that introduces it, then give the reason in one line. Left unexplained it becomes a support question, and worse, it teaches the reader to distrust the design where it is actually load-bearing.

**State a constraint by its symptom, not as a prohibition.** "Do not register both" tells a reader what to avoid and abandons them the moment they have already done it. "Registering both leaves two handlers on the same event and every shortcut fires twice" is the same instruction plus a diagnosis, and the diagnosis is the half they need at the point they go looking. Every rule in a page is also a debugging aid for whoever broke it, and writing it as a symptom costs nothing.

**A convenience shown in an example is labeled as one.** Aggregate imports, inline credentials, a wildcard, a shortcut that keeps a snippet short: each is right for reading and wrong for shipping, and a reader copying the page cannot tell which. Where an example takes a convenience, one sentence says what to use in what they ship and why. Otherwise the convenience is what propagates, since the example is the part that gets copied.

**One call shown once, within one concern.** Where several steps use the same call with a different argument, showing that call in a separate block each time teaches the call repeatedly and the differences not at all. Group them into one block, with a comment naming what each line is for. Keep a block separate only where the code genuinely differs in shape, such as a branch that picks one option among several, since that is a different construct rather than the same one again.

**Sections are cohesive or they mislead.** Cohesion is the old module-design scale, and it grades a documentation section exactly as well as it grades a unit of code. A section has *functional* cohesion when everything in it serves one job the reader recognizes, and that is the target. Two weaker kinds are what go wrong in practice.

*Logical* cohesion groups things because they are the same kind of operation, every registration call, every setter, every endpoint that happens to be a POST. The similarity is in the syntax, not in the subject, and a reader takes adjacency as meaning: put an unrelated capability beside two that belong together and they will look for the relationship that is not there.

*Coincidental* cohesion groups whatever is left over, and it announces itself in the heading: "the rest", "other", "miscellaneous", "additional options". A leftovers heading is not a naming problem, it is the section telling you it has no subject, and the fix is to split it along the concerns already inside it rather than to rename it.

The previous rule is about repetition inside one concern. It is not license to merge concerns because their code looks alike.

### Enumerations belong in tables

The density that hurts a reader is not sentence length. It is parallel facts chained into a wall: four short sentences each naming a different status code, option value or enum member. Every sentence reads fine and the paragraph is unusable.

When consecutive sentences each name a different value of the same thing, that is a table: one intent sentence above it, the facts inside it, the caveat in a short sentence below.

### Documenting a surface

**Every member gets its own heading.** A method mentioned only inside a sentence about a different method is undocumented. If it has a name a reader will type, it is a section, not a clause. Uneven depth across a surface reads as "the author knew three of these well."

**Order so the page only ever refers backward.** Introduce each member once, in a sequence where nothing needs a member the reader has not met. When a section has to send the reader back to an earlier one, the order is wrong, not the wording. Behavior that belongs to two members lives with the one that owns it: how to remove a one-shot subscription belongs under the one-shot method, not inside the removal method, or the page zig-zags between them.

**A passing reference to a second system is a decision, not a phrase.** Scene-setting sentences hide whole subsystems: "the server announces every state change" was standing in for a state machine with its own vocabulary, its own event payload, and behavior a reader must know to use it. Every time you write a clause like that, decide which it is. Trivial enough to state in full, right there, in a sentence that actually says the thing. Or a system in its own right, in which case it earns a page and this becomes a link. What is never acceptable is the third option, where the clause implies the reader already understands something the docs never explain anywhere.

The test is whether you could write the full explanation in two sentences without losing anything a reader would act on. If not, it is a page.

**A fact true of the whole surface belongs above the members, never inside one.** The test: would this sentence be equally true under three other headings? Then it is a property of the system, and stating it under one member implies it is special there. Give those facts a short section before the members and let each member carry only what is its own.

**Document the deviation, not the convention.** Where the library behaves the way the platform does, say nothing. Explaining that a listener is removed by reference teaches a JavaScript developer what they already know, and it trains them to skim the paragraphs that do carry a surprise. Spend the words where the behavior would surprise them.

The same test applies to consequences. Do not warn about an outcome the reader meets the instant it happens: turning on two interfaces shows two interfaces, and the screen says so before any sentence could. A caution earns its place when the result is silent, delayed, or presents as an unrelated problem, the cases a reader cannot connect back to the choice that caused them. Source comments are a common way this leaks in, because a note written for the next developer touching a branch, who cannot see the rendered result, becomes a statement of the obvious once it reaches someone looking at the screen.

**Prose under a table adds what the table cannot hold.** When to choose a row, what happens next, why one row differs in kind. Restating a cell in a sentence is padding that reads as thoroughness.

**Changing one part of a page invalidates the parts that summarize it, in both directions.** A page is one argument, so an edit lands in three places and only one of them is where you typed. Below it, a sentence that carried the new fact locally becomes repetition, and a sentence that was true when the page said less can become false: a closing line naming three causes reads as the complete set until a table above it lists four, and the same unchanged words now contradict the page. Above it, every overview, intro table, or "what this covers" line promised the scope of the section you just grew, so a section that gains a capability leaves the summary describing a smaller surface than the page documents. That upward direction is the one that gets missed, because nothing about writing a new subsection draws the eye back to the top.

After any edit, reread the whole page rather than the part you changed, and ask of each claim whether it is now repetition, whether it is still true, and whether it still describes the full scope of what it introduces. Enumerations are the first place this breaks: a summary that lists what a section offers is stale the moment that section gains a member.

**An instruction the reader cannot carry out is not documentation.** "Raise its priority", "enable the flag", "increase the timeout" name an action without saying where the thing is set, what it is called, what it defaults to, or which direction is which. The writer knows the surrounding code and reads the phrase as complete; the reader has only the page. Whenever a sentence tells someone to change something, that sentence, or the lines under it, must show the declaration or call that changes it, along with the default and the units or direction, since "higher" and "lower" are not self-evident for a value nobody has seen. The check is to ask whether a reader with only this page open could do the thing named. If not, the sentence is a gesture at documentation rather than the thing itself.

**Every mechanism has an acting side and an observing side, and both are the documentation.** Writing how to cancel, retry, defer, or reject an operation covers the code that decides. It leaves out the code that has to answer for the result, which is usually a different part of the application and often written by a different person. A page that explains how to stop an action and never names the event announcing that an action was stopped has documented half a feature, and the missing half is the half the interface needs, because a control that has to explain itself to a user is the one asking what happened.

The tell is a passive sentence about the outcome. "The action does not run" and "the request is retried" describe a result without saying how anyone learns of it. When you write one, follow it with the name of the event, return value, status, or callback that carries that result, its shape, and the full set of values it can hold. The reason a result exists is that something reacts to it.

**Name a shape and you owe the reader its structure.** Writing `event.data`, `result`, or `context` introduces an object the reader cannot picture, and describing one member of it while the others stay unmentioned leaves them believing they have seen the whole thing. Decide by size, and take one of three paths. A small shape goes inline as a type block, where seven members read faster than seven paragraphs and show at a glance what combines with what. A shape with a handful of members whose meanings need prose gets a property table. A large or shared shape gets one sentence of purpose and a link to its reference entry, never a partial list, because a partial list of an object's members is indistinguishable from a complete one.

Closed sets of values are part of the shape. A status, a reason, a mode, or any union type is enumerated in full or not mentioned as a set at all; naming three of four possible values is the same error as documenting three of seven members, and the one left out is often the one the reader most needs, since it tends to be the case their own code did not cause.

**A table of outcomes owes an example per outcome.** Where a surface offers several independent things a reader may want to do, listing them in a table and then showing one of them documents that one and leaves the rest as names. Each outcome gets its own short heading and its own minimal example, because the reader arrives wanting one of them specifically and needs to see it done. This is where a surface most often looks covered while being covered once: an interception API with mutate, cancel, defer and halt is four features, not one feature with four rows.

Say which outcomes are independent, too. Two calls that appear together in an example read as a pair unless you state that either works alone.

**An example models a situation, not a signature.** A snippet that calls a method and immediately undoes it proves the call compiles and teaches nothing: subscribing with a one-shot and unsubscribing on the next line is code nobody writes. Show the case a reader is actually in. For a one-shot that is removed early, the situation is that the event may never arrive and the view is closing anyway. When the only honest example is contrived, the sentence was enough on its own, so write the sentence and skip the snippet.

Where the example depends on something the code cannot express, one comment line supplies it. Two calls that happen at different moments look simultaneous on the page, and a line like `// The viewer left before playback ever started.` is the difference between a demonstration and a use case. That is the bar for a comment in an example: it carries context the reader cannot get from the code, never a restatement of what the next line does.

**When a structure holds more than one shape, label the shapes inside the code.** A list that accepts either a bare value or a wrapped one, a config key taking a string or an object, a union of any kind: shown without labels, the members sit adjacent and read as an inconsistency rather than a choice, and the honest reaction is that the example contains a typo. A blank line between the forms separates them; a short comment on each says which case it is. Explaining the split in prose underneath is weaker, because it asks the reader to hold the code in mind while they read about it, and it is invisible to the many people who take everything they need from the snippet and never read the paragraph. Put the distinction where the distinction is, and drop the prose that would have restated it.

**Trace how a thing is obtained through the whole chain, not the first manifest you open.** Telling a reader to install, enable, or provide something is a claim about provenance, and provenance is the easiest thing to get backwards, because the file in front of you shows a local view of a global fact. A library listed as a development dependency in the package you happen to be reading may be a runtime dependency of the package that one depends on, in which case it arrives on its own and the instruction to install it is not merely redundant, it is wrong: it tells the reader their setup is incomplete when it is finished. Follow the chain to the manifest that actually provides the thing before writing a setup step, and where a step turns out to be unnecessary, say plainly that nothing further is needed. An install list with one invented entry costs more trust than a missing paragraph.

**Every host, path, and identifier in an example must resolve, and you check that it does.** Placeholder hosts are the reflex, and they are worse than they look: a reader who copies the page gets a broken result and cannot tell whether the library failed or the example was fiction. Use resources the project actually publishes, take the exact values from a working example or fixture in the repo rather than reconstructing them from memory, and then fetch them and confirm the response. Placeholders remain legitimate only where the value is genuinely the reader's own, such as their server or their key, and those read as obviously theirs rather than as something that might work.

**A field is described by its consumer, never by its name.** For any option, config key, parameter, or data field, find the code that reads it before writing a sentence about what it does. A well-chosen name suggests a purpose so strongly that the description writes itself, and what you have then written is a guess carrying the confidence of a fact. Two failures follow from it: a field whose real use is narrower than its name implies, and a pair of similarly named fields where the one you assumed is not the one that applies. Search for the name, read every hit that is not its own declaration, and describe what those lines do with the value. A field with no reader anywhere is a finding to report, not a row to fill in.

**A mechanism is not documented until you have read what feeds it.** A branch on a lookup table means nothing until you have read the table; a config field means nothing until you know its default; a strategy means nothing until you know which implementation ships. Reading the code that consults the data, and stopping there, produces confident sentences about behavior you have not seen. One rename map documented as a general renamed-event warning turned out to hold a single legacy alias, which belonged in a migration note rather than in the concept page.

**Read the implementation of the surface you are documenting, not its callers.** Fluency from usage is enough to write a page and not enough to make it complete. A page written that way can miss an entire subscription form, an extra call shape, and a diagnostic event, while passing every prose and density check.
