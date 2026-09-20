# Documentation map

Copy this to `docs-work/map.md` and fill it in. The column names and order are
fixed, because `scripts/check_docs.py` parses this table. Lists inside a cell are
separated by semicolons. An empty list is `-`.

**Scope:** which packages, apps or services are being documented, in the user's words.
**Excluded:** below, with a reason each.
**Audience:** who each tier is written for.
**Destination:** where the documentation lives, and what that decides about naming, nesting and links.
**Conventions:** the project's own style rules, and where they are stated.

## Excluded

- `path/to/thing`: why it is deliberately not documented

## Pages

| Page | Tier | Job | Owns | Assumes | Links to | Covers | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| /guide/introduction | introduce | What this is and whether it is for you. | - | - | /guide/quickstart | src/index.ts | planned |
| /guide/quickstart | quickstart | Get one working result on the reader's machine. | - | /guide/introduction | /reference/config | src/setup.ts | planned |
| /reference/config | reference | Every setting, its default, and what a wrong value does. | configuration | /guide/quickstart | - | src/config | planned |

**Tier** is one of `introduce`, `quickstart`, `examples`, `reference`, `catalog`.
**Status** is one of `planned`, `drafted`, `reviewed`.
**Job** is one sentence. A job that needs two sentences is two pages.
**Owns** names the concepts explained here and nowhere else. Most pages own nothing.
**Covers** names the source paths this page is answerable for.
