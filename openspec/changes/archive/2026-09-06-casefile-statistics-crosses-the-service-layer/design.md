## Context

`StorePort` is this project's one deliberate abstraction, reserved for a later
heavier engine. Its value depends entirely on nothing bypassing it, and one
adapter call did. The fix is small; what took the work was establishing that it
was the only one and that changing the return type broke nothing, because the
tool it feeds had no test.

## Goals / Non-Goals

**Goals.** No adapter holding a store. The port speaking in domain objects
throughout. A test that fails if either regresses, and a first test for the tool
being edited.

**Non-Goals.** Introducing a type checker. Changing the tool's payload. Giving
`case_casefile_overview` a REST or CLI counterpart. Reducing the two resolves to
one.

## Decisions

### The tool's test is written first, against the unchanged code

This is the order that matters, not a preference. The change rewrites ten `dict`
subscripts into attribute reads inside a tool nothing exercised, and there is a
trap sitting under it: the SQL aliases these columns `ingested` and `expanded`
while the payload calls them `documents_ingested` and `documents_expanded`. A
dataclass field named after the alias — the obvious thing to write while looking
at the query — produces a payload with different keys, every value still truthy,
and no existing test disturbed.

So the payload's **key set is asserted exactly**, and it was asserted before
anything moved. Watched failing afterwards by renaming one key: the assertion
reports `'ingested'` extra and `'documents_ingested'` missing.

### The statistics method takes a reference, and the tool still resolves

`statistics(reference)` matches `SearchService.mention_facets` and
`IngestionService.list_documents`, which both resolve and delegate. The tool
also needs the `Casefile` itself for the title and slug it renders, so it
resolves too — two lookups for one call.

The alternative is `statistics(casefile_id)`, which reduces it to one and hands
the adapter an id whose only use is calling a store with it. That is the shape
this change exists to remove. `case_get_passage` already resolves twice for the
same reason, so the cost is one this surface has already accepted.

### `by_type` stays a mapping inside a frozen dataclass

Freezing the dataclass does not freeze the dict, and a reviewer may reasonably
ask for a tuple of pairs. It stays a mapping because it is handed straight to
the agent as `documents_by_type` and iterated for the formatted block; making it
a tuple would change the payload for a purity argument. `Extraction.metadata` is
the precedent — a `dict[str, str]` inside a frozen dataclass, for the same
reason.

### The retype is documentation; the test is the guard

Declaring `Context.store` as `StorePort` says what a holder of a `Context` may
assume. It enforces nothing here: no type checker runs in CI or in
`pyproject.toml`, and the field still holds a `SqliteStore`. Several tests reach
`context.store._db`, which a checker would flag — worth knowing before anyone
adds one, and stated in the field's own docstring rather than left to be
discovered.

What enforces the rule is `test_no_adapter_reaches_the_store`, and its scope and
matching are both deliberate — after a first version got both wrong.

**Scope.** Every module in the package except `services/`, `storage/` and
`app.py`. An exemption list, not a list of adapters: the first version scanned
`interfaces/` alone, which is one adapter of the three this project names, and
left REST and CLI unguarded. Phrased as an exemption, a fourth adapter is
covered on the day it is written.

**Matching.** Parsing, for two reasons — it reports `<any expr>.store` rather
than the one `context.store` spelling a search would be written for, and it
cannot be tripped by the words appearing in a comment. Not for a third reason
the first version gave: a grep is *not* defeated by binding the store to a name
first, because `store = context.store` contains the string being searched for.

`_store` is matched beside `store`, and `getattr(x, "store")` beside both. The
private-field reach is the realistic one: every adapter holds a
`CasefileService`, whose `_store` is one attribute away, and reaching for it is
what someone does when the service method they need does not exist — the exact
situation that produced the breach this change fixes.

## Risks / Trade-offs

**Two resolves where there was one.** Two extra lookups per overview call, on a
tool an agent is told to call once before searching. Accepted for the reason
above.

**The guard is deliberately blunt, and it still has false negatives.** Any
`<expr>.store` or `<expr>._store` outside the exempt packages fails it,
including a future attribute that merely happens to be called `store`. That bias
is right: a false positive is a one-line conversation, a false negative is this
defect returning unnoticed.

What it does not catch is worth writing down rather than discovering later. A
module that imports `SqliteStore` and constructs one passes. So does a reach
through a name the parser cannot follow — `vars(context)["store"]`, or a store
handed to a helper as a plain argument. This catches the accident and the
shortcut, which is what the original breach was; it is not a sandbox, and
nothing here should be described as if it were.

**A frozen dataclass is a wider change than a dict at the call site.** Every
consumer moves from `stats["documents"]` to `stats.documents` in the same pass,
including four tests. That breadth is why the tool's characterisation test came
first: the compiler-shaped failures are loud, and the payload-shaped one is not.
