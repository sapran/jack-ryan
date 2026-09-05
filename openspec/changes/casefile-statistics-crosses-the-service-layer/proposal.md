## Why

`storage-seam` says it plainly:

> The service layer SHALL NOT contain SQL, and no adapter SHALL reach a store
> directly.

One line contradicted it. `interfaces/mcp/server.py` called
`context.store.casefile_statistics(resolved.id)` — the only place in `src/`
where an adapter held a store, and the only `StorePort` method with no service
caller at all. The agent surface otherwise reaches `context.casefiles` seven
times, `context.search` five and `context.ingestion` twice; this was its single
exception.

Three things made it possible, and each is worth naming:

1. **There was nowhere else to go.** `CasefileService` had no `statistics`.
   `case_casefile_overview` has no REST or CLI counterpart, so nothing ever
   forced the service method to exist.
2. **The type permitted it.** `Context.store` was declared as the concrete
   `SqliteStore` rather than as `StorePort`, so reaching past the service layer
   was not even a type error — and this repository runs no type checker.
3. **Nothing tested the tool.** `case_casefile_overview` had no test of any
   kind. The only occurrence of its name outside `src/` asserted that the
   analyst pack mentions it.

There is a second, quieter breach in the same call. `casefile_statistics`
returned `dict[str, object]` — the only port method returning an untyped dict,
against the same requirement's first sentence: the port "SHALL speak in domain
objects rather than rows".

## What Changes

**Current behaviour.** The agent surface resolves a casefile through the
service, then calls the store itself for its counts, then reads five keys out of
an untyped dict to build a payload.

**Desired behaviour.**

- **`CasefileService.statistics(reference)`**, resolving like every other query
  on that service and delegating to the port. The agent surface calls it, and
  `context.store` becomes unreachable from every adapter.
- **The port returns a `CasefileStatistics`**, a frozen dataclass, rather than a
  dict of five keys. `by_type` stays a mapping inside it — it is handed to the
  agent as a payload field and iterated for a formatted block, and
  `Extraction.metadata` already sets the precedent for a mapping in a frozen
  dataclass.
- **`Context.store` is declared as `StorePort`.** A claim about what a holder of
  a `Context` may assume. Documentation while no type checker runs, which is why
  it ships with the test below rather than instead of it.
- **A guard test that matches the reach, not the string.** Any `<expr>.store`
  under `interfaces/`, found by parsing rather than grepping, so
  `store = context.store` on one line and `store.anything()` on the next cannot
  slip through and a mention in a comment cannot trip it.

**Deliberately not in scope.** The tool still resolves the casefile itself for
the title and slug it renders, and `statistics` resolves again for the counts —
two lookups where the old code did one. That is the price of the adapter not
holding an id it can call a store with, and `case_get_passage` already pays it.

## Impact

- Affected specs: `storage-seam` (MODIFIED — two scenarios making the existing
  SHALLs testable: that no adapter reaches a store, and that the port hands back
  domain objects)
- **Not** affected: `service-adapter-boundary`. Established by reading it rather
  than assumed. Its rule is about domain rules living in the service layer, and
  its scenario asks that no adapter "validates input or resolves references
  itself" — which the old code satisfied, since it resolved through
  `context.casefiles.resolve`. What it did wrong was reach a store, which is
  `storage-seam`'s rule. A MODIFIED block would reproduce it byte-identically,
  which the delta guidance says to cut.
- **Not** affected: `mcp-tool-surface`. The payload keys are unchanged, which is
  the point of writing the tool's first test before changing it.
- Affected code: `src/jackryan/storage/port.py`, `src/jackryan/storage/sqlite.py`,
  `src/jackryan/services/casefiles.py`, `src/jackryan/interfaces/mcp/server.py`,
  `src/jackryan/app.py`
- New tests: the first behavioural test of `case_casefile_overview`, and the
  adapter-reach guard. Four existing tests move off the store and onto the
  service method.
- No migration, no schema change, no corpus-identity component. The SQL is
  untouched; only what it is packed into changed.
