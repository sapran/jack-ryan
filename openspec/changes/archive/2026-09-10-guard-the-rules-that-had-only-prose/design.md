# Design

## The contract, fixed before any fan-out

Five units are built by parallel agents, so every signature they share is
settled here rather than discovered by each of them separately.

### `BoundedPage` — one continuation rule (`storage/port.py`)

A plain mixin, not a dataclass. The three pages differ only in what their entry
list is called — `documents`, `passages`, `carriers` — so the base asks for the
list through one property and each page supplies its own:

```python
class BoundedPage:
    """The continuation rule every bounded page answers identically."""

    total_matching: int   # annotation only; each page declares its own field
    offset: int

    @property
    def entries(self) -> Sequence[object]:
        raise NotImplementedError

    @property
    def truncated(self) -> bool:
        return self.offset + len(self.entries) < self.total_matching

    @property
    def continue_from(self) -> int | None:
        return self.offset + len(self.entries) if self.truncated else None

    @property
    def beyond_the_end(self) -> bool:
        return not self.entries and bool(self.offset) and bool(self.total_matching)
```

**Why a plain class and not a frozen dataclass base.** `@dataclass` collects
fields from its own `__annotations__` plus the `__dataclass_fields__` of
dataclass bases. A non-dataclass base contributes no fields, so the bare
annotations above are documentation and type information only: every page keeps
declaring `total_matching`, `offset` and `limit` itself, in its current order,
and no constructor signature moves. A frozen dataclass base would reorder fields
and break every construction site — the opposite of a change that alters no
behaviour.

`entries` is deliberately a property rather than a field: a field would appear
in `__init__` and in every construction site, and would let a page's entry list
and its `entries` disagree.

### `StoredDocument` (`storage/port.py`)

```python
@dataclass(frozen=True)
class StoredDocument:
    document: Document
    location_is_new: bool
```

The boolean is named at the seam rather than at the call site. `store_document`
returns it; `services/ingestion.py` reads the two attributes.

### `CasefileCoverage.ground` (`services/casefiles.py`)

```python
GROUND_NONE = ""                              # the verdict is not `unknown`
GROUND_NO_RUNS = "no-runs"
GROUND_CONTINUITY_BREAK = "continuity-break"
GROUND_DOCUMENTS_PREDATE = "documents-predate-first-run"
```

Precedence, decided in the service: no runs, then a continuity break, then
documents predating the first run. That is the order the overview tool applies
today, so every sentence an agent sees is unchanged. The service's own verdict
test is a disjunction, in which order does not matter; the *ground* needs an
order, and this is where it is now stated.

`GROUND_NONE` is the empty string rather than `None` so that the field is always
a string, and so a surface that words the ground cannot accidentally print
"None".

A fourth ground is now a change to the service, the published requirement that
fixes the count at three, and the sentence that words it — together, in one
change, instead of a false sentence appearing on its own.

### The shared renderers (`rendering.py`)

```python
def location_paths(record: DocumentLocationRecord) -> list[str]
def render_location_record(record: DocumentLocationRecord, *, drop_empty_note: bool) -> dict[str, Any]
def render_carrier_page(page: MentionDocumentPage, mention: str, *, render_row: Callable[[Document], dict[str, Any]]) -> dict[str, Any]
```

Both parameters exist because the two human surfaces genuinely diverge, and the
existing `render_hit(..., round_scores=...)` is the precedent for expressing a
divergence as one parameter rather than as a second copy:

- `drop_empty_note` — the CLI omits `locations_note` when it is empty; REST
  always includes the key. Preserving both payloads byte-identically is the
  point, so the difference becomes an argument.
- `render_row` — the CLI's rows come from `render_document` and REST's from
  `serialize_document`, which is `render_document` plus REST's own extras. The
  envelope is shared; the row renderer is passed in.

The CLI's non-JSON path prints two of the five location keys, so it takes those
two from the returned block rather than spreading all five into a row it then
prints line by line. That keeps the human output identical.

### One listing bound (`services/`)

One `DEFAULT_LISTING_PAGE = 50` and one `MAX_LISTING_PAGE = 200`, imported by
the document listing, the passage listing and the carrier enumeration, and by
the three adapters for their parameter defaults.

**`MAX_SEARCH_RESULTS` is not part of this.** It is the agent surface's own
*search* bound, deliberately set below the service's `MAX_LIMIT`, because a
search result carries prose while a listing row carries metadata. Folding it in
would move the clamped search maximum from 50 to 200 — an observable change in a
change that claims none.

## Waves, by file ownership

No two concurrent agents touch one file.

| Wave | Unit | Files owned |
|---|---|---|
| 1 | Page continuation | `storage/port.py`, `interfaces/mcp/server.py`, `tests/test_document_paging.py` |
| 1 | Shared renderers | `rendering.py`, `cli.py`, `server.py`, `tests/test_result_shape.py`, `tests/test_document_locations.py` |
| 2 | Coverage ground | `services/casefiles.py`, `interfaces/mcp/server.py`, `tests/test_mcp_surface.py` |
| 2 | Named store result | `storage/port.py`, `storage/sqlite.py`, `services/ingestion.py`, `tests/test_store.py` |
| 2 | Prose-only guards | `tests/test_architecture_invariants.py` (new file only) |
| 3 | One listing bound | `services/ingestion.py`, `services/search.py`, `cli.py`, `server.py`, `interfaces/mcp/server.py` |

Wave 2 follows wave 1 because both waves' units touch `storage/port.py` and
`interfaces/mcp/server.py`. Wave 3 is last because it touches five files three
earlier units own, and it is small enough to run inline.

## Guard oracles

A guard whose expectation is computed by the code it guards is blind. Each guard
here parses a declaration rather than calling the thing it protects:

- **Port speaks in domain objects** — walk `StorePort`'s method definitions in
  the AST of `port.py` and reject a return annotation that is a tuple in any
  form, a bare `dict`, or a `dict[K, V]` whose value type is not a domain class
  declared in `port.py` itself. The oracle is the declaration, which no
  implementation change can move, and the guard fails on a *new* method with the
  old shape rather than only on the one being fixed.

  The dict clause is narrower than "reject every subscripted `dict`", which was
  this design's first wording, and the narrowing is deliberate: `get_chunks`
  returns `dict[str, Chunk]`, a keyed batch of domain objects, and the pitfall
  this rule exists for is a dict standing in for a *row* — field names living in
  strings, where a typo is a `KeyError` at the surface and a rename is silent.
  `dict[str, str]` and `dict[str, Any]` still fail. The permitted value types are
  derived from the module's own top-level class definitions rather than from a
  list in the test, so adding a domain type does not require editing the guard.
  It is restricted to classes carrying a `dataclass` decorator, which every
  domain type in `port.py` has: review proved that deriving from every class
  admitted a `TypedDict`, which is a row with its field names in strings and so
  exactly what the rule refuses.
- **The absence guards** (`MAX_RESPONSE_CHARS` re-export, `CorpusIdentity.parse`,
  `from .migrations import`, `rendering` imported by `interfaces/`) — parse the
  module and assert the name is absent. Each must be mutation-proved by adding
  the thing it forbids and watching it go red; an absence assertion that cannot
  fail certifies nothing.
- **One definition per file signature** — collect byte-literal assignments whose
  name marks them as a signature and assert no two names hold the same value.
  Stated as duplicate detection rather than as "they all live in `sniffing.py`",
  because `containers.py` legitimately holds the RAR signatures, which answer a
  different question — which reader libarchive should use, not what a file is.
- **Vacuity** — every guard asserts its own scan was non-empty. A guard that
  inspected nothing passes, and that is how a guard goes blind rather than red.
