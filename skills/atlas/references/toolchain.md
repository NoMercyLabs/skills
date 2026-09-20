# The toolchain answers

Seven questions, answered from the repository in front of you, before any slice is
scanned. The answers go in `docs-work/toolchain.md` and every scanner and
fact-checker is handed that file.

They are not answered from what the language usually does. A general answer is
recall wearing a checklist, and it is wrong in exactly the projects where being
wrong costs most: the ones with a house convention. Every answer names a file, a
config key, or a command that exists here.

## The questions

1. **What makes a declaration reachable by a consumer?** Find the mechanism, an
   exports map, a visibility keyword, a module manifest, a route table, and name
   the file that holds it. A symbol reachable in the source and not through that
   mechanism is unreachable, which is a finding rather than an entry.
2. **Everywhere a value can be defaulted, in the order they override each other.**
   Name the layer that wins. A project with three layers and no stated precedence
   is a project whose configuration is about to be documented wrong.
3. **What is a test file here?** The pattern, and the config that says what the
   suite touches before you run any of it.
4. **What is the doc-comment convention, and does anything check it?** A
   convention nothing checks is the highest-drift surface in the repository. One
   that is compiled or executed cannot silently rot, which changes how much weight
   a comment carries.
5. **What command formats a snippet the way this project would?** Take it from the
   formatter config or the CI workflow, not from the language's usual tool. Where
   there is none, say so, and take the shape from the surrounding source instead.
6. **What is the cheapest command that proves a claim?** A type check, one test, a
   help flag, a build of one module. Every later verification depends on this
   answer, so it is the one to get right and the one to actually run once before
   writing it down.
7. **What has already drifted?** Before slicing, check two or three claims from
   the existing documentation or from doc comments against the code. What you find
   is the drift pattern for this repository, and it is a better predictor of where
   the rest is wrong than any general list.

## Where the answers come from

Build files, the CI workflow, the formatter and linter configs, the test config,
and the existing tests. A CI workflow is the strongest of these, because it is the
set of commands somebody keeps green.

Questions six and seven are the two that must be run rather than read. An
unverified verification command means every claim it was supposed to prove is
unproven, and a drift pattern guessed rather than found is a guess about guesses.

## A repository with several languages

Answer the seven per language present, in one file, under a heading each. A slice
spanning two languages gets both sections. Language is a property of a file, not
of a job, so a mixed slice is normal rather than a routing problem.

## What this file is not

It is not a reusable artifact. It describes one repository, it is written fresh
for each one, and it stays in `docs-work/` with the rest of the evidence. Carrying
it to the next project would reintroduce exactly the recall it exists to replace.
