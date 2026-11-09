# Gate input format

This describes the checker interface, not another editorial standard. The card is readable Markdown. Its check list is fixed before drafting; commands are JSON argument arrays executed without an implicit shell.

## Card

Use each label once, with no omitted sections:

    Route: /guide/example
    Reader: The specific audience and what they already know
    Type: task
    Arrives-with: The reader's question
    Goal: The result they need
    Success: What they can observe
    Application-case: A second case chosen independently of the writer
    Prerequisites: The real requirements, or none
    Project-root: C:\path\to\documentation
    Built-root: dist
    Rendered: dist/guide/example/index.html
    Voice: docs-work/voice.md
    Must know:
    - access | The required fact | ../product/source.cs:20-24
    Moves elsewhere:
    - detail | The relocated fact | ../product/source.cs:30 | /guide/reference#detail
    Checks:
    - build: ["the-actual-executable", "its-actual-argument"]

Must know lists only what this reader needs on this page to act or to avoid a surprise. It is not an inventory of what the code does. Anything else goes under Moves elsewhere, or is left out. Replace the example's paths and command with the project's real values; it is not an executable card. Type is task, concept, lookup or troubleshoot. Use a local file reference (with an optional line range) or a primary HTTPS source for evidence. UI observations can be kept in a local evidence file. Each requirement ID is unique. Use "- none" under Moves elsewhere when nothing moves. The checker verifies every relocated route and fragment in Built-root; it does not invent a destination.

Cards can be written before the site is built: Rendered only has to exist when preflight runs, and a named check may be the build that produces it.

Where the docs are plain Markdown with no build, name a check that renders each page with a Markdown renderer the project or its host already provides, and wraps it in `<main><article>` under `docs-work/rendered/`. Set Built-root to `docs-work/rendered`, and the routes to match. Those files exist only for review and are not published.

Project-root is the working directory for every named command. On Windows, commands that require cmd.exe must name it explicitly in their argument array. Use the exact commands established by the coordinator, not a shell string reconstructed by a writer. A check that is missing, fails or cannot start blocks acceptance.

## Review files

Files are named from the percent-encoded route without its leading slash. For /guide/example they are guide%2Fexample.reader.json and guide%2Fexample.fact.json. Each carries the same single fingerprint produced by preflight: page bytes, card bytes and the renderer's article HTML. There are no individual input hashes or reviewer identity fields.

The checker requires strict JSON and rejects duplicate keys, unexpected fields, legacy PASS lines, stale fingerprints and empty required results. It checks structure and freshness; the separate reviewers judge accuracy and reader usefulness.

### Reader

The independent reader receives --reader-input output and saves this structure before warnings are available:

    {
      "fingerprint": "the fingerprint printed by preflight",
      "verdict": "PENDING",
      "answers": [
        {"question": 1, "answer": "The answer", "quote": "Exact rendered text"},
        {"question": 2, "answer": "The answer", "quote": "Exact rendered text"},
        {"question": 3, "answer": "The answer", "quote": "Exact rendered text"},
        {"question": 4, "answer": "The answer", "quote": "Exact rendered text"},
        {"question": 5, "answer": "None, or an obstacle and its cost", "quote": ""},
        {"question": 6, "answer": "None, or an obstacle and its cost", "quote": ""}
      ],
      "findings": [],
      "warnings_released": false,
      "warning_review": []
    }

Questions 1–4 require quotations present in the rendered article. Question 2 may omit its quote when the card explicitly declares no prerequisites. Use UNKNOWN for a missing answer; it blocks a passing final review. A material finding belongs in findings and makes the review fail.

The quote value can be one continuous excerpt or an array of separate exact excerpts. Never stitch different passages into one quotation or add Markdown/table punctuation. Every excerpt is checked against visible rendered text. Citation-format repairs before diagnostics must preserve the saved blind answers and findings.

Only after the answers are saved, run --warnings --reviews <dir>. The checker validates those answers, sets warnings_released in this same file, and prints the diagnostic IDs. It does not change the answers or grade the prose. The reader adds one decision per warning:

    {"id": "the diagnostic ID", "decision": "keep", "reason": "Why this wording works for the reader"}

A decision of fix remains unresolved until the page is repaired and freshly reviewed. When no warnings exist, the empty list remains valid. The reader, not the writer, sets the final verdict. The process separates the blind pass from warning assessment; it is not a cryptographic proof of reviewer independence.

### Fact review

The independent fact reviewer reads the source, card, page and reader answers:

    {
      "fingerprint": "the same single fingerprint",
      "verdict": "PASS",
      "coverage": [
        {"id": "access", "result": "supported", "evidence": "Source and checked behavior"},
        {"id": "detail", "result": "supported", "evidence": "Source and completed destination"}
      ],
      "reader_answers": [
        {"question": 1, "result": "supported", "evidence": "Why the answer agrees with the source"},
        {"question": 2, "result": "supported", "evidence": "Why the answer agrees with the source"},
        {"question": 3, "result": "supported", "evidence": "Why the answer agrees with the source"},
        {"question": 4, "result": "supported", "evidence": "Why the application answer agrees with the source"}
      ],
      "findings": []
    }

Cover every card requirement exactly once, including moved detail. Also check factual claims beyond the card and whether the named checks cover the project's real validation entry points and requested scope. Any unsupported claim or material omission fails review.

## Stage results

Preflight executes the named checks and validates the renderer output and moved destinations. Reader-input exposes the reader's request and rendered article, without length diagnostics or card rationale. Warnings cannot be released before the blind answers exist for this fingerprint. Final acceptance checks both reviews and every warning decision, reruns the named commands and refuses acceptance if validation changes the page, card or rendered article.

Only final can print ACCEPTED. Successful preflight, reader-input and warnings commands do not mean the page is done. Card corrections invalidate both reviews, including a correction to a check name or a supposedly minor requirement. Changed pages and rendered content do too.

## Multiple pages

Fix a JSON array containing every page in scope before drafting. Paths are relative to the manifest:

    [{"page":"new/example.mdx","card":"cards/example.md","reviews":"reviews","result":"results/example.log"}]

Run `python scripts/check_batch.py manifest.json --checkpoint progress.md`. It recomputes accepted N of M and the first unaccepted route, refusing missing or stale review/acceptance records. A nonzero checkpoint means work remains. Do not drop entries to make the count pass.

The manifest always lists the whole inventory. To work one batch of a large set, add `--routes /first/page /second/page` to `--preflight` or `--final`. Only those pages need reviews, and the checkpoint still counts every page.

For a related batch, add `--preflight` or `--final`. These use the same page gates, running an identical named command once when its working directory, name and argv match across the batch. Final requires every page's reviews before running checks and writes final command results only after the entire batch remains unchanged. Save the full command output alongside those results. To use individual `check_page.py --final` calls instead, save each command's complete output at its manifest result path and check its exit code. Neither preflight nor a manual status label counts as acceptance.
