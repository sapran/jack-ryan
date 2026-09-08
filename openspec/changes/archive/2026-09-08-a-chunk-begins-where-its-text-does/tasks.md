## 1. The rule in the published specs

- [x] 1.1 Read `chunking-and-embedding` and `mentions` in full; verify which
      published requirement each change falsifies and which are untouched.
      *`chunking-and-embedding`'s "Chunking follows the corpus contract and stays
      locatable" and `mentions`' "A casefile's identifiers can be inventoried as
      a facet" — one each. The other seven requirements across the two specs are
      untouched.*
- [x] 1.2 Reproduce every published scenario of both MODIFIED requirements
      verbatim by title, since a `MODIFIED` requirement replaces the whole
      requirement and scenarios join by title; verify with
      `openspec validate a-chunk-begins-where-its-text-does --strict` before any
      code is written. *Valid on the first run, before the chunker was touched.*
- [x] 1.3 Establish that no other spec is falsified: `storage-seam` (a rowcount
      is not a "counts or sizes describing stored data" mapping),
      `schema-migration` (no step is added), `mcp-surface-profiles` (nothing is
      added to the agent surface), `hybrid-search` (no retrieval predicate
      moves). Record the falsification in `## Impact`. *Recorded. The one
      retrieval SQL edit in the diff is the mutation table's, not the change's —
      `mention_facets` ships exactly as it was.*

## 2. The chunker records the trimmed span

- [x] 2.1 In `chunk_text`, record `char_start` at the first non-whitespace
      character of the window and `char_end` at `char_start + len(text)`; verify
      `position` and `window_end` still drive the paragraph search, the
      step-back and the loop's termination unchanged. *They do: the diff adds
      `body` and `start` and touches nothing below the `chunks.append`.*
- [x] 2.2 Keep `heading_path` resolved from `_line_start(text, position)`;
      verify against a document whose window opens on whitespace after a heading
      that the recorded heading path is unchanged by this edit. *Unchanged —
      `tests/test_chunking.py` and `tests/test_section_windows.py` pass with no
      edits to their heading assertions.*
- [x] 2.3 State the invariant in the `TextChunk` docstring:
      `source[char_start:char_end] == text`, and why.
- [x] 2.4 Leave `services/windowing.py`'s `_slice` comparing after `.strip()`;
      verify by reasoning recorded in `design.md` that an exact comparison there
      would return `None` for every chunk row written before this change.
      *Untouched; the argument is in `design.md` and in the corrected root
      `CLAUDE.md` bullet.*
- [x] 2.5 Add no monotonicity claim about `char_start`; verify the one test that
      reads that property does so against its own fixture.
      *`test_chunks_are_ordered_and_numbered_from_zero` reads it off `TEXT` under
      120/20, which cannot reach the case; nothing was strengthened.*

## 3. Chunker guards

- [x] 3.1 Change `test_offsets_locate_each_chunk_in_the_source` to exact
      equality.
- [x] 3.2 Add `test_offsets_select_a_chunk_whose_window_opened_on_whitespace`,
      with the whitespace at exactly the offset the second window opens from;
      verify the fixture asserts that precondition itself, so it cannot silently
      stop proving anything. *It asserts `text[400 - 50].isspace()` and that
      more than one chunk was produced. Both go red when the chunker records the
      window again.*

## 4. Ingest-level count guards

- [x] 4.1 Keep `test_one_occurrence_across_two_overlapping_chunks_counts_once`
      and amend its closing sentence to point at the new ingest-level guard
      rather than to argue one cannot be written.
- [x] 4.2 Add `_overlapping_occurrence_document`, built from the contract rather
      than from literals; verify it asserts the identifier fits inside the
      overlap. *`assert len(lead_in) + len(value) < overlap`; 34 < 50 under the
      suite's contract and 34 < 200 under the shipped one.*
- [x] 4.3 Add
      `test_one_occurrence_in_two_overlapping_chunks_counts_once_after_a_real_ingest`
      through the shipped pipeline; verify it asserts that exactly two chunks
      carry the identifier and that they agree on its document position, since
      the count below means nothing otherwise. *Both asserted, plus that the
      extractor did not change the text.*
- [x] 4.4 Add `test_one_occurrence_in_each_of_two_documents_counts_as_two`;
      verify the two files differ, since identical bytes deduplicate to one
      document. *They differ by a trailing line; the test reports `(2, 2)` and
      goes red when the count drops the document from its key.*

## 5. Port and store

- [x] 5.1 Add `list_document_ids`, `list_document_chunks` and
      `recompute_mention_offsets` to `StorePort`; verify the docstring for the
      first says why it is not `list_documents`.
- [x] 5.2 Implement all three in `SqliteStore` in the shape of the neighbouring
      chunk reads — `self._lock`, `_row_to_chunk`, rollback on failure.
- [x] 5.3 Verify `recompute_mention_offsets` writes only `document_offset` and
      carries the `<>` predicate that makes a repeated run report nothing.
      *Dropping the predicate turns the second-run assertion red;
      `cursor.rowcount` after `executemany` summed the modified rows on this
      build, which the exact-count assertion would have caught if it had not.*
- [x] 5.4 Add no schema step and rewrite no `chunks.char_start`; verify the
      argument against a migration step is recorded in `design.md`. *Recorded:
      additive-statement ladder, `ltrim`'s explicit character set, and a step
      running on open.*

## 6. The repair

- [x] 6.1 Add `MentionOffsetRepair` beside `IngestReport`.
- [x] 6.2 Add `IngestionService.repair_mention_offsets`; verify it holds one
      document's text and chunks at a time and makes one write per document.
      *One `get_document` and one `list_document_chunks` per document, one
      `recompute_mention_offsets` per document.*
- [x] 6.3 Verify it searches for the stored text inside the span the offsets
      name and never across the whole document. *`text[chunk.char_start :
      chunk.char_end].find(chunk.text)`.*
- [x] 6.4 Verify an unlocatable chunk is counted and skipped rather than
      guessed at. *`within = max(within, 0)` in its place turns
      `test_the_repair_leaves_a_chunk_whose_text_is_not_at_its_offsets_alone`
      red.*

## 7. CLI

- [x] 7.1 Add the `repair mention-offsets` subcommand in `build_parser` and its
      branch in `main`; verify all four report fields reach the payload.
      *`test_repair_reports_a_corpus_that_needs_nothing` reads three of the four
      out of the JSON; the fourth, `chunks_examined`, is asserted through the
      service in `tests/test_mentions.py`.*
- [x] 7.2 Add nothing to REST or the agent surface; verify the last spec
      scenario needs no new test —
      `test_the_readonly_profile_advertises_exactly_its_tools`
      (`tests/test_mcp_surface.py`) already asserts the roster equals
      `READONLY_TOOLS` exactly. *No change to `server.py` or `interfaces/mcp.py`
      is in the diff.*

## 8. Repair guards

- [x] 8.1 Add `_stale_positions`, writing the positions a pre-fix ingest would
      have derived as SQL rather than by reverting the chunker; verify the
      stale state is asserted before the repair runs, so the repair proves
      something. *First version staled only the mention rows, which left every
      chunk's offsets tight and made the mutation of the correction term GREEN.
      It now writes the window starts to `chunks` as well — one state, not two —
      and `_stale_corpus` asserts at least one chunk's offsets no longer select
      its own text.*
- [x] 8.2 Add `test_the_repair_corrects_positions_an_earlier_ingest_recorded`;
      verify the exact report tuple, the corrected inventory, byte-identical
      chunk rows and extracted text, every mention field but `document_offset`
      unchanged, a non-empty vector search, and a second run correcting nothing.
      *`(1, 2, 0, 1)`, `(1, 1)`, all four comparisons, and
      `mentions_corrected == 0` on the second pass.*
- [x] 8.3 Add
      `test_the_repair_leaves_a_chunk_whose_text_is_not_at_its_offsets_alone`;
      verify nothing was guessed by comparing the mention rows with the stale
      state. *`(chunks_examined, chunks_unlocatable) == (2, 2)`,
      `mentions_corrected == 0`, rows identical.*
- [x] 8.4 Add `test_repair_reports_a_corpus_that_needs_nothing` in
      `tests/test_cli.py`, exercising `cli.main` against the deterministic
      context.

## 9. Documentation

- [x] 9.1 Correct the root `CLAUDE.md` window pitfall, which now states
      something false, and add the bullet saying a mention's document position is
      derived and an older corpus's is stale.
- [x] 9.2 Add a `docs/handover.md` entry stating what was verified with
      synthetic data and that **no real corpus has been repaired**.
- [x] 9.3 Park in `docs/implementation-notes.md`: root `CLAUDE.md` points at
      `openspec/config.yaml`, which does not exist in this repository.

## 10. Gates and mutation proof

- [x] 10.1 `uv run pytest -q`, `openspec validate --all --strict`,
      `gitleaks detect --no-banner`. *721 passed, 3 skipped; 18/18; no leaks.*
- [x] 10.2 Mutation-prove each new guard with the uv-safe harness (a copied tree
      keeps importing the original worktree through the editable `.pth`, so
      every mutation reports GREEN); verify one unmutated control is GREEN and
      treat exit code 4 as a collection error rather than a red test. *All nine
      mutations RED, each with a GREEN control. Two of them run against the
      worktree instead of a copy — see 11.10 — with the original bytes restored
      and their sha256 re-checked. The harness also refuses an anchor that
      matches zero or more than one site.*
- [x] 10.3 Run the end-to-end repair demonstration against a disposable store on
      the deterministic embedder, and paste its output as evidence. *In
      `docs/handover.md`: `(1, 1)` after ingest, `(2, 1)` staled,
      `mentions_corrected=1`, `(1, 1)`, then `mentions_corrected=0`.*

## 11. What review found

- [x] 11.1 Reproduce the reported whitespace-only window before acting on it;
      verify with one variable changed and nothing else. *One document, two
      chunks, the recorded pair the only difference: pre-fix → no window;
      post-fix → `window=(15,85)` adding `'\n\n'`.*
- [x] 11.2 Refuse a widening that adds only whitespace, by comparing the text
      rather than the span; verify the change is a widening of the refusal and
      not the tightening this change refuses elsewhere. *The first guard in
      `_slice` still trims, so a pre-fix row's window is not withdrawn; the
      second now subsumes the old span test for rows of either convention.*
- [x] 11.3 Add `test_a_widening_that_adds_only_whitespace_is_not_a_window`;
      verify it asserts its own preconditions — that the section reaches past
      the matched passage, and that a paragraph break follows it — and that it
      goes red when the refusal compares spans again. *Both asserted; the sixth
      mutation is RED on exactly that test.*
- [x] 11.4 Repair `test_the_response_bound_drops_context_and_never_a_result`,
      which was counting windows that carried no context; verify it now asserts
      something was widened before the bound is applied. *Three of the four
      passages are results, so the gap gives one of them real room.*
- [x] 11.5 Open the `hybrid-search` delta its window requirement now needs;
      verify every published scenario of that requirement is reproduced by
      title. *Four reproduced, one added. `openspec validate --strict` passes.*
- [x] 11.6 Record what the other two reviewers established rather than only
      what they found. *Correctness: 3,000-input fuzz over the chunker gave
      `source[char_start:char_end] == text` for every chunk, `char_start` can
      now be equal to the previous chunk's but no reader assumes strict
      monotonicity, and `cursor.rowcount` after `executemany` summed the
      modified rows on Python 3.12.14 / SQLite 3.53.1. Silent-failure: the diff
      adds three SQL statements, all parameterised, of which one writes, and it
      names `mentions` and sets `document_offset` alone — no trigger can widen
      it, since the only trigger in the schema fires `AFTER DELETE ON chunks`.*
- [x] 11.7 Pin `chunks_examined` in the CLI guard; verify the field is needed
      rather than decorative. *Without it, a repair iterating `for chunk in []`
      leaves the whole suite green, and the `corpus` fixture holds no mention
      row, so `mentions_corrected == 0` is vacuous there. Both mutations are now
      RED.*
- [x] 11.8 Guard that the pass reaches expanded documents; verify the gap was
      real. *Adding `AND parent_id IS NULL` to `list_document_ids` was green
      across the suite while the pass skipped every archived document. A zip of
      one `.txt` now covers it, and that mutation is RED.*
- [x] 11.9 Make the "no position was guessed" assertion able to fail, and able
      to be reached; verify by mutation which assertion fires. *The pass now
      runs once before the text is replaced, so a clamped guess writes 358 where
      361 is stored; and the row comparison is placed before the counters,
      because pytest stops at the first failure. Under the clamp the row
      assertion is the one that fires, naming both values.*
- [x] 11.10 Establish why the CLI node cannot be mutated in a copied tree, and
      handle it without `git checkout`. *That node ingests the `corpus`
      fixture's `.md` files through docling; a copied venv re-initialises that
      native stack — 67 seconds and exit -11 after the test passed, against 2.9
      seconds at exit 0 in the worktree, which also runs all 721 tests in one
      process cleanly. Its two mutations are applied in place with the original
      bytes held in memory and their sha256 re-checked, since `git checkout`
      would discard the uncommitted work. The copy-based half now runs one
      pytest process per node, because nine store-opening tests in one
      copied-venv process crashed at shutdown while each alone was clean.*
- [x] 11.11 Assert the shared helper's coincidence rather than describing it,
      and replace the unfalsifiable vector check. *The two-document test now
      asserts both documents place the identifier at the same character —
      prefixing one file with a covering note makes it pass under the collapse
      it exists to catch. The vector assertion is a before-and-after comparison
      of `chunk_vectors`, which `_chunk_rows` cannot see.*
- [x] 11.12 Record the fidelity gaps rather than leaving them implicit.
      *`_stale_positions` leaves `chunks.char_end` tight, one character narrower
      than a real pre-fix row, which changes nothing the repair does — the
      search is inside that span either way; and the helper's asserted boundary
      is the overlap, which is the chunker's step-back only while
      `overlap <= max_chars // 2`. Both are now docstring clauses.*
