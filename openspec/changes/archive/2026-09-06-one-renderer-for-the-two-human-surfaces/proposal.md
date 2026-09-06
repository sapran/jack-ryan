## Why

The CLI and the REST route describe the same three domain objects for the same
kind of reader — a person, or a script a person wrote — and had written those
descriptions twice.

The copies had already drifted, which is the whole argument:

1. **A casefile**: `cli._render` and `server.serialize` were byte-identical,
   seven keys, no difference at all. Two functions maintaining one fact.
2. **A search hit**: seventeen keys, identical expressions, differing only in
   that the CLI rounds `score` and `rerank_score` to six decimal places and REST
   does not.
3. **A document**: **five** differences. REST carries `casefile_id` and
   `updated_at` and always emits the summary; the CLI adds `found_at` and
   `children` only when they say something, and omits an empty summary.

Nothing structural held the shared parts together. Every field added to
`SearchHit`, `Document` or `Casefile` had to be added twice, by hand, and the
only thing catching a divergence was a test comparing the surfaces after the
fact — which covered the fields someone thought to compare.

## What Changes

**Current behaviour.** Two modules build the same dictionaries independently,
agreeing by coincidence and maintenance rather than by construction.

**Desired behaviour.**

- **`src/jackryan/rendering.py`** holds what the two human surfaces agree on:
  `render_casefile` (no options — they were identical), `render_hit` with a
  single `round_scores` parameter for the one real difference, and
  `render_document` returning the **nine** fields both carry.
- **Each adapter keeps its own function**, calling the shared one and adding its
  own extras. `cli._render_document`, `server.serialize_document` and
  `server.serialize_hit` stay importable by name — three test call sites import
  them directly, and one of them reports `render.__module__` in its failure
  message, so aliasing all three to a single implementation would cost that test
  its point.
- **The agent surface is deliberately excluded.** `interfaces/mcp` renders the
  same objects differently on purpose — `document_id` rather than `id`, every
  corpus value collapsed to one line, no chunk summary at all, which
  `tests/test_mcp_fencing.py` pins. Folding it in would make those differences
  look like drift.
- **Two tests assert the split**: that the nine shared fields agree across both
  surfaces, and that nothing but the rounding separates the two hit renderings.
  Both watched failing by reintroducing drift.

**Deliberately not in scope.** A single `render_document` taking five flags. It
would be an interface as wide as the implementation it hides, which is the shape
this change exists to remove rather than reproduce.

## Impact

- **One observable change, stated rather than buried: REST's JSON key order.**
  `casefile_id` moves from third to tenth, and `summary`/`summary_by` from
  before `created_at` to after it. The key **set** and every value are
  unchanged, verified by construction. No test asserts key order, JSON objects
  are unordered by specification, and no client contract in this repository
  depends on it — but it is observable on a public API and it belongs in the
  proposal rather than in a diff someone reads later.
- Affected specs: **none.** Established by falsification, not assumed.
  `service-adapter-boundary` is the only spec that mentions REST; its
  requirements are about where rules live and how errors are translated, and
  this change moves neither. `extraction-quality-gate` requires the CLI and REST
  to report `read_as` "using the same name and the same words" — this change
  makes that structural rather than duplicated, so it satisfies the requirement
  more strongly and falsifies nothing. A MODIFIED block for either would
  reproduce it byte-identically, which the delta guidance says to cut.
- New code: `src/jackryan/rendering.py`
- Affected code: `src/jackryan/cli.py`, `src/jackryan/server.py` — 101 lines
  removed, and the now-unused `read_as` import dropped from both
- New tests: two in `tests/test_result_shape.py`
- No migration, no schema change, no corpus-identity component.
