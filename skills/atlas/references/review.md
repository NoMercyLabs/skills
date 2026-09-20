# Review and delivery

## Phase 7: Two reviews on every page

No page is finished on the writer's own judgment. Every file gets both reviews below before it is delivered, and they are separate passes because they fail on different things and one masks the other: a page can be entirely true and unreadable, or a pleasure to read and false.

Run them as agents, both for every page and a whole batch at a time, and give each the file plus the source it claims to describe. One agent per review per page, never two on the same page at once: the verdict file is named by the page, so a second run overwrites the first whenever it finishes and the record shows the slower one. The prompts and the model each runs on are in `../agents/fact-checker.md` and `../agents/reader.md`.

**The fact-check review.** Its only question is whether each statement is true of this repository right now. It takes every claim in turn, signatures, defaults, names, ordering, error codes, install steps, resolved URLs, every value in every table, and finds the line that supports it, reporting the location or marking the claim unsupported. It runs the page's code where the project can run it. It treats the writer's confidence as worthless and comments in the source as claims rather than proof. It returns a verdict per claim, not an impression of the page, and anything unsupported is cut or corrected before delivery, never softened.

**The reader review.** Its reviewer is someone who does not know this system and is trying to get something done, and its question is whether the page carries them. Give it the route as well as the page: which pages come before this one, and what the ledger says those pages already taught. A reviewer holding only the page under review cannot tell a necessary explanation from the third copy of one, and will approve every one of them. It flags a term used before it is introduced, a step whose outcome is not stated, an example that models nothing they would do, an order that demands knowledge from further down the page, and any sentence that would leave them unsure whether they had succeeded. It is equally alert to the opposite fault: a sentence that is true and irrelevant, a caveat about a case they will never hit, a detail that belongs in reference and is padding here. Every word earns its place by carrying meaning for that reader, and what does not is cut.

**Both reviews enforce the project's own conventions over this skill's.** A repository that specifies code style, formatting, spelling, terminology, example data, or documentation structure has already decided those questions, and its decisions win wherever they differ from anything written here, including in the code inside examples, which is held to the project's style exactly as its source files are. Read the project's own instructions before reviewing, and treat a conflict as this skill yielding rather than as an inconsistency to reconcile.

A page that fails either review goes back to the writer. Two clean reviews are the bar for calling a file done.

**A finding a project gate would reject is not a finding.** Where a reviewer's suggestion and one of the project's own gates disagree, the gate is the answer and the suggestion is recorded as declined. A reader asked for a catalog table on a tier 1 page; the project's tier gate caps table rows there, and building the table broke the build.

**A page that fails goes back inside this run.** Not into the report as an outstanding item, not left `drafted` while the run moves on to fresh rows. Repair it, review it again in full, and repeat until it carries two passing verdicts. A batch is finished when every page in it does, and only then does the next batch start.

**A repair is new writing, and it is verified like new writing.** Correcting a fact-check finding means composing sentences that have never been checked, and they fail at the same rate as the originals: one page had its four findings fixed and came back with six, five of them in the paragraph that had been repaired. A page returning from a fix is reviewed in full, not diffed against the findings it was sent back for.

**A repair often fails in a different category than the one it answered.** Tightening a sentence for density turns loose phrasing into a checkable promise, and cutting a clause for repetition strands the sentence that depended on it. So a page repaired for a reader finding goes back to the fact check as well, and one repaired for a fact finding goes back to the reader.

**Several findings in one passage mean the passage was written from a wrong model.** Patching them claim by claim leaves that model in place and produces a paragraph that is wrong in a new way. Where a cluster appears, three or more findings inside a few sentences, throw the passage away and write it again from the evidence the reviewer gathered, which is usually measurements the original was guessing at.

**A verdict judges one version, and it is stamped with that version.** Each review file carries the page's path and a digest of its content, and the checker recomputes it: edit the page afterwards and the verdict is marked stale rather than counted. Without that, a fixed page keeps an old rejection and a rewritten page keeps an old approval, and both look identical to a report written later from the review directory.

**A review finding is a claim, and it is verified before it is acted on.** A reviewer reads the same way a writer does and completes from a plausible design in the same way: one review reported that two fields were incompletely enumerated when the fields were free strings with no closed set to enumerate. Read the source the finding names before changing anything. A finding that turns out to be wrong is reported back rather than quietly ignored, because it usually means the page invited the misreading.

**A finding about a term used too early is often the map being wrong, not the page.** When a reader review says a page uses something it was never taught, check which page owns that concept. If the owner is not in this page's `Assumes`, the route is wrong and the fix is a map edit, not an explanation bolted onto the page. Fixing it on the page teaches the concept twice.

**A page that a fact check rejects for describing unpublished behavior is a release decision, not a writing defect.** Record it, keep it off the page, and put it in the report as something the user may want to ship rather than something you failed to write.

## Phase 8: Check it holds together

Before delivering, go through the docs once more as a whole rather than as separate files:

- **Consistency**: one name per concept across all files, one architecture story, no contradictions between pages.
- **Links**: every internal link resolves; every referenced file path exists.
- **Commands**: every command appears exactly as verified, with correct paths and flags.
- **Coverage**: `check_docs.py map` accounts for every source path, either as a page's responsibility or as an excluded entry carrying its reason. Read the excluded list back to the user at delivery, because it is the part they may disagree with.
- **The onboarding test**: could someone follow `getting-started.md` from scratch, on a clean machine, without asking a single question? Where the answer is no, that is the next thing to fix.
- **The project's own gates**: when the project ships documentation checks, they are the acceptance criteria, not an afterthought. Run every one and leave them green. Check which of them the build actually invokes, because a check that exists and is not wired into the build has been passing by not running, and the drift it was written to catch is already there. Report an unwired gate rather than wiring it: what runs in someone's build is their decision. A docs site commonly carries checks for link resolution, navigation placement, example compilation, prose rules and density; a page that fails them is not finished no matter how it reads.
- **Rendered, not inferred**: look at the built page, not only the source. Color, spacing and table behavior are decided by CSS and a syntax theme, and neither is visible in Markdown. Where the project deploys, check the deployed URL rather than a local preview.

## Reporting back

Tell the user, briefly:

- Which documents were written and where
- Which output shape was chosen and why
- Where the backup of the old documentation is
- **Mismatches found between old docs and code**: this is often the most valuable output of the whole exercise
- Open questions and anything that could not be verified, so they know exactly what still needs a human

Keep this short and factual. The documentation is the deliverable; the report just tells them where to look and what to double-check.
