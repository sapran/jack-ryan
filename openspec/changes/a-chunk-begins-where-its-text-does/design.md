## Context

A chunk's stored text is its window with surrounding whitespace removed; its
recorded `char_start` is the window's start. Everything downstream that turns a
position *inside* a chunk's text into a position in the document adds the two
together, so every such position is wrong by the trimmed lead. Only one thing
currently does that — a mention's `document_offset`, derived in `replace_chunks`
— and only one thing consumes it — the identifier inventory, which distinguishes
occurrences by `(document_id, document_offset)`.

That is why the visible symptom is a count. The overlap means an identifier near
a chunk boundary is extracted twice; the inventory's job is to recognise the two
rows as one occurrence, and it does so correctly by position. When the two
windows trimmed unequal whitespace the positions differ, the recognition fails,
and one occurrence is reported as two — with the count's own definition intact.

The difference is only whitespace, which is why every check passed. Both the
chunker's own guard and `Windower._slice` compare after `.strip()`.

## Goals / Non-Goals

**Goals.**

- A chunk's offsets select its stored text exactly, so anything deriving a
  document position from them is right by construction.
- The existing rows are correctable, deliberately, without re-extracting,
  re-chunking or re-embedding — and without anyone's corpus being rewritten
  because they opened it.
- Each of those has a guard that goes red when reverted.

**Non-Goals.**

- Moving `chunks.char_start` for rows already written.
- Tightening `Windower._slice`.
- A boundary that cuts an identifier in half, so the two chunks yield different
  normalised text. The counts then describe two different strings, which is a
  different defect.
- Any change to what a citation addresses, or to any payload shape.

## Decisions

### The recorded span moves; the loop's arithmetic does not

`position` and `window_end` keep driving the paragraph-boundary search, the
step-back, and the loop's termination. What changes is only the pair of numbers
written into `TextChunk`. Deriving the loop from the trimmed start would move
chunk boundaries, which changes every chunk in every document — a corpus-wide
difference in service of an off-by-whitespace fix.

`heading_path` stays resolved from `_line_start(text, position)`, the window's
own start. A trimmed start can sit past a heading its window opened on, so
resolving from it would change the heading path recorded for chunks that have
nothing to do with this defect.

`char_start` consequently loses the guarantee of increasing strictly across
chunks — reachable only when more than half a window is leading whitespace *and*
the overlap is at least half the window. Neither the shipped 2000/200 contract
nor the suite's 400/50 can reach it, and nothing but one test's own fixture
reads that property. No monotonicity claim is added or strengthened.

### The repair is an operator's command, not a migration step

`schema-migration` says every step SHALL be additive and a step is a tuple of
SQL statements. Locating a stored text inside its own window needs Python:
SQLite's `ltrim` takes an explicit character set and would diverge from
`str.strip()` on the non-breaking spaces and Unicode whitespace a Ukrainian or
Russian scan is full of. And a step runs when a store is opened, which would
rewrite an operator's corpus with nobody asking and no status to read.

So: a service method, one CLI command, and a report. Not on the agent surface —
that is a read surface, and putting a write there would need
`mcp-surface-profiles` to say so.

### The position is recomputed, never adjusted

`text[chunk.char_start:chunk.char_end].find(chunk.text)` returns `0` for a chunk
already tight, the trimmed lead for a wide one, and `-1` when the stored text is
not there at all. That makes the pass idempotent by construction rather than by
bookkeeping: a second run computes the same positions and the `<>` predicate in
the UPDATE reports nothing changed.

`find` over the span the offsets name, never over the whole document: the same
text can occur elsewhere, and a match found there would move the mention into a
passage nobody chose.

### An unlocatable chunk is counted and left alone

Where the stored text is not inside the span its own offsets name — a
half-completed ingest leaving new text against old offsets, the same
inconsistency `Windower._slice` declines to widen — that chunk is counted and
skipped. A position guessed for it would resolve and be wrong, which is worse
than one known to be stale. `chunks_unlocatable` is in the report so a run that
skipped work is distinguishable from one that had none.

### One document at a time, one write per document

`list_document_ids` exists rather than reusing `list_documents` because the
latter carries every row's extracted text: a maintenance pass over a casefile
would hold the whole corpus in memory in order to walk it. The pass therefore
costs one document's text plus its chunks, whatever the casefile's size.

### `recompute_mention_offsets` returns an `int`

`delete_casefile` and `delete_document` already return a bare `bool` describing
what the call did. `storage-seam`'s "port hands back domain objects" scenario is
about a method *reporting counts or sizes describing stored data* returning a
string-keyed mapping — a different shape from a rowcount. No dataclass, and no
`storage-seam` delta.

## Risks / Trade-offs

- **An existing corpus stays wrong until somebody runs the pass.** Accepted
  deliberately over a migration step, for the two reasons above. The report and
  the documentation say so plainly.
- **Old `chunks.char_start` values stay wide.** Windowing trims before
  comparing, `case_cite`'s span reads a little wide exactly as it does today,
  and the repair's formula reads the stored text rather than assuming a
  convention — so it corrects a pre-fix corpus and a post-fix one identically.
- **`cursor.rowcount` after `executemany`** is relied on to sum the modified
  rows. The repair guard asserts the exact number, so a build reporting `-1` or
  a per-statement value fails loudly rather than reporting a wrong count.
