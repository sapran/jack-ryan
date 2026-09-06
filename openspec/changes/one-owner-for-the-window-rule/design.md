## Context

Widening was built in the `measured-retrieval-quality` slice and has been
correct since. Nothing here is a bug fix. What changed is that the rule has
grown to a third of its file while keeping exactly one dependency on everything
around it, and the tests still have to assemble that everything to reach it.

The subgraph, read from `origin/develop` at `aed01d2`:

| Member | Lines | Reads from `self` |
|---|---|---|
| `_HEADING_LINE`, `_section_bounds`, `_clip_to_headings`, `_widen`, `_keep_clear`, `_avoid` | 153–273 | — (module functions) |
| `_slice` | 595–619 | nothing — a method that never says `self` |
| `passage_window` | 551–559 | `_window_max_chars` |
| `_window_for` | 561–593 | `_store`, once |
| `_widened` | 621–671 | `_window_max_chars`; module `MAX_RESPONSE_CHARS` |

One store call. One setting. Everything else is arithmetic over spans and one
slice of a string.

## Goals / Non-Goals

**Goals.**

- The window rule lives in one module and can be exercised without a store, an
  embedder, a corpus or a query.
- The move is provably behaviour-preserving: bodies and docstrings unchanged,
  entry points delegating.
- A test that widens nothing cannot pass by accident, because its neighbours are
  written out rather than implied by a fixture.

**Non-Goals.**

- Changing any window, span, `narrowed` flag or bound.
- Touching the fusion or rerank stages, or the mention-filter parsing that is
  the file's third concern. Those stay where they are; only one of the three
  moves.
- Fixing either parked finding in this code.
- Turning `MAX_RESPONSE_CHARS` into a declared parameter. It is a module
  constant read live today, which is what one test relies on; making it a
  constructor argument is a second change wearing this one's clothes.

## Decisions

### The module is given a way to find neighbours, not the store

`Windower.__init__` takes `neighbours: Callable[[str, int, int], list[Chunk]]`
and a budget. `SearchService` passes `store.get_document_chunks_around`.

The alternative — passing `StorePort` — is one fewer indirection and reads more
plainly at the composition site. It was rejected because it keeps the property
this change exists to remove: a test of the window rule would still have to
produce something satisfying `StorePort`, and the cheapest way to do that is a
real store. With a callable, the test writes three chunks in a list and returns
them. That is the whole difference between "the rule is testable" and "the rule
is testable if you first build a corpus".

It is also honest about what the module needs. `StorePort` declares nineteen
methods; the window rule uses one. A dependency on all nineteen would overstate
the coupling by eighteen.

### `MAX_RESPONSE_CHARS` is not re-exported from `search.py`

The constant moves to `windowing.py`, and `search.py` does **not** import it
back. Two test modules re-point instead: `tests/test_section_windows.py:13` and
`tests/test_result_shape.py:179`.

This matters more than it looks. `tests/test_section_windows.py:211` does

```python
monkeypatch.setattr(search_module, "MAX_RESPONSE_CHARS", 1200)
```

and the widening loop reads the constant off its own module at call time. A
re-export would let that patch bind to a name nothing reads: it would succeed,
change nothing, and the test would go on asserting against the real 60,000-char
bound.

That test carries what looks like a guard against exactly this —
`assert narrowed, "the bound was never reached, so this test says nothing"`.
**It does not catch it.** Measured by adding the re-export and repointing the
patch: the test fails, but three assertions later, on
`all(h.text == h.chunk.text for h in narrowed)`. The guard passes because
`narrowed` is also set by the *neighbour-blocking* path — a result cut back to
make room for another result's passage — and those results exist in this fixture
whether the bound was reached or not. The failure is real but incidental: it
depends on the fixture producing results that keep a window, and it reports a
symptom that names neither the bound nor the patch.

So the protection is weaker than the guard's wording suggests, which is the
argument for removing the question rather than relying on it.
`tests/test_result_shape.py` has no guard at all. Making a stale reference an
`ImportError` costs two lines.

**This is the opposite of the decision `one-owner-for-a-file-signature` made**,
and deliberately so. There, `legacy_office` was required to import
`_OLE2_MAGIC` *by name* precisely so that `legacy_office._OLE2_MAGIC` kept
resolving for sixteen tests that read it that way. The rule underneath both is
the same: a name that survives a move must still mean what the reader thinks it
means. There the readers only read the value, so an alias is honest. Here a
reader *writes* it, and an alias would swallow the write.

### `passage_window` stays on `SearchService`; `_window_for` does not

`passage_window` is the service layer's answer to "what surrounds this passage",
and `interfaces/mcp/server.py:362` calls it. It stays, as a one-line delegation
to `Windower.for_passage`.

`_window_for` becomes `Windower.around` with no shim left behind. Two tests call
it directly (`tests/test_section_windows.py:287-289`, `:314-316`) and re-point to
`context.search._windows.around(...)`. A compatibility shim would be a second
name for one rule inside the change that exists to remove second names.

### `_slice` becomes a module function

It never referenced `self`. Dropping the parameter is not a refactor of its
logic — the body is unchanged — it is deleting an argument that was never read.
Both callers are inside `Windower`.

### The reranker still sees the passage, never the window

`CLAUDE.md` requires it, and the reason is concrete: the reranking library
truncates the query-and-passage pair at the model's own limit with no override,
so a window would be cut inside it and the score would describe a fragment
nobody chose.

The split does not put a window in that path and cannot. `_reranked` stays in
`search.py`, runs inside `search()` before line 447, and scores `chunk.text`.
Widening happens strictly after, on the ranked list. Stated here because the
guarantee now spans two modules and a reader of either one alone cannot see it.

## Risks / Trade-offs

**A pure-move change is exactly where a silent edit hides.** The mitigation is
mechanical rather than argued: `git diff --stat` must show the lines leaving
`search.py` and arriving in `windowing.py` in matching quantity, and the 19
existing window tests must pass untouched apart from their import lines. A test
that needed its *assertions* changed would mean the move was not a move.

**One more module in `services/`, holding no service.** `services/` currently
holds three classes that own domain rules and are wired at the composition root.
`windowing.py` holds a helper the search service composes. The alternative
placement — a `retrieval/` package beside `reranking/` — is a bigger change that
would also move fusion, and this slice does not know yet whether that is the
right shape. `services/` is where its only caller lives, and moving it later is
one import line.

**`Neighbours` is documentation, not enforcement.** Nothing in this repository
type-checks, so a caller passing the wrong callable fails at the call, not at
the wiring. This is the same trade `Context.store: StorePort` records, and the
compensation is the same: a test that the composition root wires the real thing.
