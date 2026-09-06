## Why

`services/search.py` is 671 lines answering three unrelated questions. The file
says so itself: it separates two of the three with its own section comments, at
lines 482 and 549.

| Concern | Lines | Size |
|---|---|---|
| mention-filter parsing | 52–146 | ~95 |
| **section-window widening** | 33–45, 153–273, 551–671 | **~245** |
| fusion and rerank orchestration | 15–31, 332–547 | ~250 |

The widening third is very nearly pure already. Across its whole call graph it
reads exactly two attributes of `SearchService`: `self._store`, for one call —
`get_document_chunks_around` (`search.py:578-580`) — and
`self._window_max_chars`. `_slice` (`search.py:595-619`) is a method that never
mentions `self` at all.

What that costs is not readability. It is that a rule with one store call cannot
be exercised without a store, an embedder, an ingested corpus and a query. Ten
unit tests reach the pure geometry functions directly, but every test of
*assembling* a window — how far to grow, what to avoid, when to give up, when to
report `narrowed` — runs a full `context.search.search(...)`.

`CLAUDE.md` records what that already cost once:

> **Test fixtures with single-passage documents cannot exercise a window.** Three
> window tests passed while proving nothing for exactly that reason.

Those three were repaired by adding a fixture. The shape that let them pass is
still here: a window test's inputs are implied by a corpus rather than written
down, so "did anything actually widen?" is answered by a fixture nobody re-reads
when the test goes green.

## What Changes

**Current behaviour.** The window rule is spread across the search service's
module scope and four of its methods, reachable only through `search()` or
`passage_window()`.

**Desired behaviour.**

- **`services/windowing.py` owns the window rule.** The five pure geometry
  functions and `_slice` move verbatim; `_window_for` and `_widened` become
  methods of a `Windower` holding a budget and a way to find neighbouring
  passages.
- **`Windower` is given a lookup function, not the store.** It needs one
  question answered — which passages surround this one — so it takes a callable
  and imports nothing from `storage` beyond the data types it already passes
  through. The composition root's wiring is unchanged; `SearchService` supplies
  `store.get_document_chunks_around`.
- **`SearchService` keeps `passage_window`.** The agent surface calls it
  (`interfaces/mcp/server.py:362`), and a retrieval rule living in an adapter is
  the divergent definition the service layer exists to prevent. It becomes a
  one-line delegation.
- **A new test module drives `Windower` directly**, with a neighbours function
  and documents written out in the test. No fixture, no store, no ingest.

**No behaviour changes.** Every function moves with its body and its docstring
intact; the two entry points delegate. Same windows, same spans, same `narrowed`
flags, same response bound.

**Deliberately not in scope.** The two parked findings this code carries —
`WINDOW_MAX_CHUNKS_EITHER_SIDE` capping reach independently of the budget, and
`case_get_passage` collapsing two meanings of "no window" — stay parked. Both
entries in `docs/implementation-notes.md` are re-pointed at the new module and
otherwise left alone.

## Impact

- **Specs: none.** Established by falsification, not assumed. `hybrid-search`
  §*A result's text is a bounded window around the matched chunk* (188–239) and
  the response-bound requirement (95–121) state what a result carries and what a
  caller can tell about it; `mcp-tool-surface` (33–58, 104–124) and
  `untrusted-content-boundary` (10–33) state what a payload declares. None names
  a function, a method or a module, and this change alters none of the behaviour
  they describe. A `MODIFIED` block for any of them would reproduce it
  byte-identically, which the delta-authoring guidance says to cut.
- **Code:** `src/jackryan/services/windowing.py` (new);
  `src/jackryan/services/search.py` loses ~245 lines and gains an import.
- **Tests:** `tests/test_windowing.py` (new); `tests/test_section_windows.py`
  and `tests/test_result_shape.py` re-point their imports.
- **Docs:** two `docs/implementation-notes.md` entries re-pointed;
  `docs/handover.md` records what this change did and did not verify.
