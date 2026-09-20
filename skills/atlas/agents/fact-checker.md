# Fact-check reviewer

Dispatch with `model: opus`, high effort. One per page.

Fill in `<page path>` and `<slug>`, and paste `docs-work/toolchain.md` under the
marker.

---

**Before anything else, know how this file is read.** A script looks for one line
matching `Verdict: PASS` or `Verdict: FAIL`, on its own, and nothing else in the
file counts. A review without that exact line is treated as a failure no matter
what it concludes, so write the line first, on the second line of the file, and
then write the findings under it. "PASS" inside a sentence, a bullet, or a table
cell is not the line.

**Stamp the version you judged.** Directly under the verdict line, write:

    Reviewed: <path to the page file, as given to you>
    Reviewed-SHA: <first 16 hex characters of its sha256>

Get the digest by running the project's own hashing tool over the file, for
example `sha256sum <path>` or `python3 -c "import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest()[:16])" <path>`.

The checker recomputes it. If the page is edited after you review it, your
verdict is marked stale and the page has to be reviewed again, which is what
stops a corrected page from carrying an old rejection and stops an approval from
standing over content nobody read.


Review `<page path>` against the source it describes. You are not assessing the
writing. Your only question is whether each statement is true of this repository
right now.

`<paste docs-work/toolchain.md here>`

Take every claim in turn: signatures, defaults, names, ordering, error codes,
install steps, resolved URLs, every value in every table. For each, find the line that
supports it. Report the file and line for each, or mark the claim unsupported.

**Verify without writing into the project.** Compiling a snippet, probing a build
or resolving an import often wants a scratch file, and the project under review is
the wrong place for it. Reviews run in parallel over one tree, so a temp file
dropped into a source or examples directory joins the next agent's gate run and
fails it, a failure that belongs to nobody and is chased in the wrong page. Put
scratch files outside the repository, and if a tool forces one inside it, delete it
before you return.


Beyond reading:

- **Run the page's code** where the project can run it. Where it cannot be run,
  take the strongest proof available, compile it, run its tests, trace it, and
  say which one you took.
- **Fetch every URL** in an example and report its status. A placeholder host is
  a failure unless the value is plainly the reader's own.
- **Trace every install or provide step** to the manifest that actually provides
  the thing, not the first manifest you open. A package listed as a development
  dependency where you are reading may be a runtime dependency of something it
  depends on, in which case the install step is wrong rather than redundant.
- **Check each described field against the code that reads it**, never against
  its name. A field with no reader anywhere is a finding.
- **Check every elided snippet**: one containing `...` or any other omission
  marker, for a complete form shown earlier on this page. If there is none here,
  report it; the reader reviewer will say whether an earlier page carried it.

Treat comments, type names and test names as claims, not proof. Treat the
writer's confidence as worthless. Where a comment and the code disagree, the code
is the truth and the disagreement is a finding.

Write your verdict to `docs-work/reviews/<slug>.factcheck.md`:

    # Fact check: <page path>
    Verdict: PASS | FAIL
    Reviewed: <path>
    Reviewed-SHA: <digest>

    | Claim | Supported by | Status |
    | --- | --- | --- |

Any unsupported claim is a FAIL. It is cut or corrected before delivery, never
softened into a hedge.
