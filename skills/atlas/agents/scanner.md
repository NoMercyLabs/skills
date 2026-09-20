# Scanner

Dispatch with `model: sonnet`. One per slice, in parallel, as many at once as the
work allows.

Fill in `<slice directories>` and `<slice name>`, and paste `docs-work/toolchain.md`
under the marker.

---

Read every non-test source file under `<slice directories>`. Enumerate them
yourself with a directory walk, you have not been given a file list, and there
is no list to ask for. Do not sample. Do not decide a file is uninteresting.

`<paste docs-work/toolchain.md here>`

Those answers were derived from this repository. Confirm each one as you use it,
and where the repository contradicts an answer, the repository wins and the
contradiction is a trap worth reporting.

Return exactly this, and nothing else:

    # Slice: <slice name>
    Files given: <M>
    Files opened: <N>

    ## Files opened
    - <one path per line, all of them>

    ## Public surface
    | Symbol | Signature (verbatim) | File:line |

    ## Literal defaults
    | Setting | Default (verbatim) | Read by | File:line |

    ## Comment versus code
    | Claim in the comment | What the code does | File:line |

    ## Traps
    | Behavior | Why it surprises | File:line |

Rules that decide whether your report is usable:

- A signature is **copied**, never retyped from memory or normalized into a
  prettier form. If it is long, it is long.
- A default is the **literal in the code**, not what the name suggests. A setting
  whose default you could not find is reported with an empty cell, not a guess.
- A field is described by the code that **reads** it. Search for the name, read
  every hit that is not its own declaration.
- Every row carries a file and a line.
- `Files opened` must equal `Files given`, and the list must be as long as the
  count.

**An empty section is a claim, and it is the claim most often wrong.** Reporting
no drift and no traps across a real slice usually means the pass was shallow,
not that the code is clean. Where a section is genuinely empty, say which files
you checked for it and why nothing qualified. A report that lists its files and
finds nothing in any of them will be rerun.
