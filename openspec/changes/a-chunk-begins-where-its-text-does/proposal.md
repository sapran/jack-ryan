## Why

Three lines, read together, make one occurrence of an identifier count twice.

| Line | What it does |
|---|---|
| `ingestion/chunker.py:113-115` | stores `piece.strip()` while recording `char_start=position`, the **untrimmed** window's start |
| `storage/sqlite.py:523` | derives a mention's document position as `parent.char_start + mention.char_start` |
| `storage/retrieval.py:178` | counts `COUNT(DISTINCT document_id \|\| ':' \|\| document_offset)` |

A mention's chunk-relative offset is an offset into the *stored*, trimmed text.
Added to a start naming the *window*, the result lands before the characters it
claims to address — wrong by exactly the whitespace that was trimmed off the
front. Chunks overlap, so an identifier near a boundary is extracted once per
chunk covering it; when two overlapping windows trimmed unequal whitespace, one
textual occurrence acquires two document positions, and the inventory — whose
own definition of an occurrence is correct — counts it twice.

The defect survived because the guard that looks like it covers it does not.
`tests/test_mentions.py:984`
(`test_one_occurrence_across_two_overlapping_chunks_counts_once`) states its two
chunks and their shared document offset outright, so it proves the counting SQL
and nothing about the offsets the SQL counts. Nothing exercised what an ingest
actually records. `tests/test_chunking.py:27` compares
`TEXT[chunk.char_start:chunk.char_end].strip()` with the chunk's text — trimming
before comparing, which is precisely the difference at issue — and whether any
of `TEXT`'s windows opens on whitespace is incidental anyway.

## What Changes

**Current behaviour.** A chunk's recorded offsets name the window it was trimmed
from. A mention's document position is derived from that start and is wrong by
the trimmed lead. An identifier lying inside the overlap of two chunks that
trimmed unequal whitespace is reported as two mentions.

**Desired behaviour.**

- **The chunker records the trimmed span**, not the window:
  `source[char_start:char_end] == text`, exactly. `position` and `window_end`
  keep driving the loop and the step-back arithmetic unchanged — only what is
  *recorded* moves. The heading path stays resolved from the window's own start,
  deliberately, so chunks this change is not about keep the heading they have.
- **`sqlite.py:523` is untouched.** The derivation is right; the fix is to make
  its input true.
- **The store gains two reads and one write**: `list_document_ids`,
  `list_document_chunks`, and `recompute_mention_offsets`, which rewrites only
  `mentions.document_offset` and only where it differs.
- **`IngestionService.repair_mention_offsets(casefile)`** recomputes each
  mention's document position from the stored text, one document at a time, and
  reports documents and chunks examined, chunks whose text could not be located,
  and positions corrected.
- **`jackryan repair mention-offsets <casefile>`** is how an operator invokes
  it. CLI only: REST gains nothing, and the agent surface is a read surface.
- **A window that adds only whitespace stops being a window.** Found by review,
  and a consequence of the tightening rather than a separate wish: a section's
  last passage is now followed by the paragraph break its own span no longer
  covers, so clipping at the next heading left a span two characters wider than
  the chunk's — `is_widened` true, two spans in provenance, and `\n\n` between
  them. `_slice` decides by comparing the text rather than the span, which
  subsumes the old "is this the chunk's own span" test for rows written under
  either convention.
- **No payload shape changes on any surface.** `case_mentions` returns the same
  two counts; they become right for anything ingested from now on, and right for
  an existing corpus once the repair is run. `case_get_passage` and
  `case_search` keep their shape too; what changes is that a whitespace-only
  widening is no longer reported as one.

**Deliberately not in scope.** An occurrence whose two chunk views disagree
about the value's *own* span — a boundary cutting an identifier, so the two
chunks yield different normalised text — is a different defect, and the counts
are then describing two different strings. Pre-fix `chunks.char_start` values
are left as they are: windowing trims before comparing, `case_cite`'s span reads
a little wide exactly as it does today, and the repair's formula is
convention-agnostic, so nothing needs them moved.

## Impact

- **Specs:** `chunking-and-embedding` (1 MODIFIED — the offsets must now select
  the stored text exactly), `mentions` (1 MODIFIED — an occurrence is
  distinguished by document and position, and that position derives from where
  the stored text begins; 1 ADDED — the repair), and `hybrid-search` (1 MODIFIED
  — its window requirement asserted that "a chunk's stored text has been
  stripped of the whitespace its offsets still describe", which this change
  makes false for new rows; the corrected clause says offsets select the stored
  text up to surrounding whitespace and that every such comparison trims, which
  is what lets one rule serve a store holding both conventions). No `Purpose`
  block is falsified, and a delta could not reach one in any case. There is no
  `openspec/config.yaml` in this repository, so no project context counts to
  re-check.
- **Code:** `ingestion/chunker.py` (the arithmetic and the `TextChunk`
  invariant), `storage/port.py`, `storage/sqlite.py`, `services/ingestion.py`,
  `cli.py`, and `services/windowing.py`'s `_slice`. That comparison is **not**
  tightened to exact equality: every chunk row written before this change
  carries the wide offsets, and an exact comparison would return `None` for all
  of them, silently switching windowing off for every existing corpus. It is
  *widened* instead, from a span test to a text test, so a widening of pure
  whitespace is refused under either convention.
- **Tests:** `tests/test_chunking.py` (exact equality, plus a window that opens
  on whitespace), `tests/test_mentions.py` (two ingest-level count guards and
  two repair guards), `tests/test_cli.py` (the repair reports a corpus that
  needs nothing), `tests/test_windowing.py` (the whitespace-only refusal, and
  the response-bound test given three results instead of four — with four, every
  result's neighbour is also a result and each window could only grow into the
  blank lines, so the count it makes was a count of whitespace).
- **Data:** no schema step and no automatic rewrite. Existing
  `mentions.document_offset` rows stay stale until an operator runs the repair;
  existing `chunks.char_start` values stay wide for ever, and that is safe.
  No real corpus is touched by this change.
