# Finding schema

`crucible gate` enforces this. A reader writes candidates in this shape with `"id": "CAND"`. Accepted findings are `findings/F-0001.json` and up.

## Fields

| Field | Type | Rule |
| --- | --- | --- |
| `id` | string | `CAND` in a candidate, `F-NNNN` once accepted |
| `repo` | string | repo name from the config |
| `title` | string | 10 to 120 characters |
| `area` | string | a folder, module or layer name |
| `goal` | integer | an `id` from `goals` in the config |
| `severity` | string | `critical`, `high`, `medium` or `low` |
| `size` | string | `S`, `M` or `L`, the size of the fix |
| `stage` | string | a stage from the config, or `none` |
| `who` | object | `affected` (who is hit), `owner` (who fixes it) |
| `what` | object | `summary`, `observed`, `expected` |
| `where` | list | `{kind, ref, commit?}`; `kind` is `file`, `route`, `screen`, `workflow`, `config` or `other` |
| `when` | object | `trigger`, `frequency` (`always`, `often`, `sometimes`, `once` or `unknown`) |
| `why` | object | `cause`, `verified` (boolean) |
| `how` | object | `reproduce` (list of steps), `fix`, `prove` |
| `evidence` | list | `{kind: file_line or command, ref: "path:line", quote}` |
| `siblings` | list | paths, or `searched: <query>, 0 more` |
| `not_checked` | list | every claim not opened or run; `[]` when none |
| `labels` | list | strings the tracker adapter maps |
| `before_you_fix` | object | `current_behaviour`, `callers`, `consumers`, `earlier_fixes`, `instances` |

No field is empty. The text `not checked` is allowed. Placeholder text (`TBD`, `?`, `n/a`, `...`, `-`) is not.

## What the gate checks

- `why.verified: true` needs at least one `file_line` evidence whose `quote` equals the real line in the snapshot.
- `why.verified: false` needs a `not_checked` entry starting `cause:`.
- No privacy word from the config, and no key-like string, in any field. Write `<token, masked>` instead of a secret.
- No private path and no person's name in any field: a finding may be filed on a public repo.

Copy each `quote` exactly from the `show` output, one line or a few whole lines, without the line-number prefix. The gate refuses an empty quote and a quote that is not at the cited lines.

## Source id

A candidate's source id is `<unit>#<first 8 hex of sha1(title)>`. Verdicts are keyed by it.

## Example finding

```json
{
 "id": "CAND",
 "repo": "orders-api",
 "title": "Order lookup builds its SQL from the request parameter",
 "area": "handlers",
 "goal": 2,
 "severity": "high",
 "size": "S",
 "stage": "none",
 "who": {"affected": "every caller of the order lookup route", "owner": "orders-api, handlers"},
 "what": {
  "summary": "The order lookup handler concatenates the id parameter into a SQL string.",
  "observed": "A request with id set to `1 OR 1=1` returns every order.",
  "expected": "The id is bound as a parameter and a non-numeric id is rejected with 400."
 },
 "where": [{"kind": "file", "ref": "src/handlers/orders.py", "commit": "9f2c1ab"}],
 "when": {"trigger": "any request to GET /orders/{id}", "frequency": "always"},
 "why": {
  "cause": "The handler formats the query with an f-string and the shared db helper has no bound-parameter variant for single-row reads.",
  "verified": true
 },
 "how": {
  "reproduce": ["Start the service with the sample database.", "Request GET /orders/1%20OR%201=1.", "Observe every row in the response."],
  "fix": "Use a bound parameter in the handler and add a bound variant to the db helper.",
  "prove": "A test that requests the injected id fails on the unchanged code and returns 400 after the fix."
 },
 "evidence": [
  {"kind": "file_line", "ref": "src/handlers/orders.py:41", "quote": "row = db.query(f\"SELECT * FROM orders WHERE id = {order_id}\")"},
  {"kind": "file_line", "ref": "src/db.py:18", "quote": "def query(sql):"}
 ],
 "siblings": ["src/handlers/invoices.py:57", "src/handlers/refunds.py:33"],
 "not_checked": ["the production database user's privileges"],
 "labels": ["type/bug", "area/handlers", "security"],
 "before_you_fix": {
  "current_behaviour": "Route returns the full row for a valid id; an injected id returns every row.",
  "callers": "web/orders.js:12 calls the route; no other caller found by searching for the route path.",
  "consumers": "none; the service has no mirror repo in the config.",
  "earlier_fixes": "git log on src/handlers/orders.py shows no earlier change to this query.",
  "instances": "production and staging (from the config); not checked whether both run this commit."
 }
}
```

The two siblings above are handlers with the same f-string pattern found by searching for `db.query(f"`. A finding with the same cause in three files is one finding with siblings, not three findings.

## Verdict file

`review/verdicts-<unit>.json`, written by the verifier:

```json
{
 "orders-u01#3fa81c20": {
  "verdict": "accept",
  "reason": "The handler passes order_id from the route into an f-string; the db helper does no escaping.",
  "checked": ["src/handlers/orders.py:41", "src/db.py:18"]
 },
 "orders-u01#a1b2c3d4": {
  "verdict": "fix",
  "reason": "Real, but the cause is proven: the helper lacks a bound variant.",
  "checked": ["src/db.py:18"],
  "fix": {"why.verified": true}
 },
 "orders-u01#0badf00d": {
  "verdict": "reject",
  "reason": "The route table puts an integer converter in front of this handler, so a non-numeric id never arrives.",
  "checked": ["src/routes.py:12"],
  "other_defect": "none"
 },
 "_leads": {
  "src/handlers/refunds.py:33": {
   "verdict": "cleared",
   "reason": "The value is validated by the schema check two calls up.",
   "checked": ["src/handlers/refunds.py:20", "src/validation.py:9"]
  }
 }
}
```

- `verdict` is `accept`, `reject` or `fix`. A reject carries `"other_defect": "none"`.
- `fix` is a dotted path into the candidate mapped to its full new value. A fix to an evidence ref also gives the new `quote`, copied exactly from `show`.
- `checked` lists the lines opened that decide the verdict. A verdict with no reason or an empty `checked` counts as no verdict.
- `_leads` has one entry per lead the reader dropped, `real` or `cleared`. A `real` lead becomes a candidate with its own verdict.
