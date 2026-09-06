## 1. The rule in the published specs

- [x] 1.1 Grep `openspec/specs/` for "window", "widen", "surrounding" and
      "passage"; verify every hit states observable behaviour and none names a
      function, method or module, so the falsification in `## Impact` rests on a
      reading rather than an assumption. *26 hits across `hybrid-search`,
      `mcp-tool-surface`, `untrusted-content-boundary`, `mcp-surface-profiles`
      and `document-ingestion`; every one is phrased over what a result carries
      or what a payload declares. A second grep for `\.py`, `passage_window`,
      `_widen`, `_slice`, `_section_bounds`, `SearchService` and `Windower`
      across all seventeen specs returns **zero** — no published spec names any
      Python file, function or class.*
- [x] 1.2 Read `hybrid-search` 95–121 and 188–239 in full and list what a caller
      may observe: the window's text, both spans, `narrowed`, the response
      bound; verify this change alters none of them. *None altered. The 19
      existing window tests assert exactly those observables and pass with only
      their import lines changed.*
- [x] 1.3 Write `.openspec.yaml` with `schema: spec-driven`, `created:`,
      `skip_specs: true` and the falsification argument as a comment; verify
      `openspec validate --all --strict` accepts the delta-free change, which it
      refuses without valid metadata. *18 passed, 0 failed — 17 specs and this
      change.*

## 2. The new module

- [x] 2.1 Create `src/jackryan/services/windowing.py` with the module docstring
      naming what it owns and what it deliberately does not reach; verify it
      imports only `Chunk`, `Document`, `SearchHit` and `Window` from
      `storage.port` and nothing else from `storage`. *Those four and nothing
      else. The docstring states the reranker rule that spans the two modules,
      because a reader of either alone cannot see it.*
- [x] 2.2 Move `DEFAULT_WINDOW_MAX_CHARS`, `MAX_RESPONSE_CHARS` and
      `WINDOW_MAX_CHUNKS_EITHER_SIDE` with their comments; verify all three are
      gone from `search.py` and that `search.py` imports only
      `DEFAULT_WINDOW_MAX_CHARS`, for its constructor default. *Confirmed by
      `hasattr(search, "MAX_RESPONSE_CHARS")` returning `False` at runtime, not
      by reading the import line.*
- [x] 2.3 Move `_HEADING_LINE`, `_section_bounds`, `_clip_to_headings`, `_widen`,
      `_keep_clear` and `_avoid` verbatim; verify each body and docstring is
      byte-identical to what left `search.py`. *Diffed with `difflib` against the
      pre-change file: **125 lines, identical**, no diff hunks. Checked before
      the originals were deleted.*
- [x] 2.4 Move `_slice` as a module function, dropping the `self` it never read;
      verify the body is otherwise unchanged. *Only the signature and the
      docstring's indentation changed; every statement is as it was.*
- [x] 2.5 Declare `Neighbours` as a `Callable[[str, int, int], list[Chunk]]`
      alias with a comment naming its three arguments; verify the comment names
      them in the order `get_document_chunks_around` takes them. *Document id,
      ordinal, radius — the port's order, checked against
      `storage/port.py:366-368`. (First written as `:335-337`, which is
      `find_documents_by_id_prefix`; caught in review. The order was right, the
      citation was not.)*
- [x] 2.6 Add `Windower.__init__(self, neighbours, budget)`; verify it stores the
      budget through `int()` exactly as `SearchService` did, so a string budget
      from configuration behaves as before. *`int(budget)`, and `SearchService`
      passes its already-`int()`ed value, so the conversion happens once and
      cannot disagree.*
- [x] 2.7 Move `_window_for` in as `Windower.around`, with `self._store.get_...`
      becoming `self._neighbours(...)`; verify the call passes
      `WINDOW_MAX_CHUNKS_EITHER_SIDE` as the radius, unchanged. *It does. Watched
      failing with the call replaced by `neighbours = []`: 7 of the 10 new tests
      red, three on their own guard messages.*
- [x] 2.8 Move `passage_window`'s body in as `Windower.for_passage`; verify it
      still discards the second element of `around`'s pair, since a window asked
      for on its own is never narrowed by another result. *Discarded, and the
      docstring now says why rather than leaving `_` unexplained.*
- [x] 2.9 Move `_widened` in as `Windower.for_results`; verify it reads
      `MAX_RESPONSE_CHARS` as a module global rather than capturing it, so the
      existing monkeypatch keeps working against the new module. *It does —
      `test_a_response_that_hits_its_bound_narrows_and_says_so` passes with the
      patch repointed, and the new
      `test_the_response_bound_drops_context_and_never_a_result` patches the same
      global directly.*

## 3. The search service delegates

- [x] 3.1 Build `self._windows` in `SearchService.__init__` from
      `store.get_document_chunks_around` and `window_max_chars`; verify
      `self._window_max_chars` is still set, because `tests/test_app.py:162,170`
      reads it. *Still set; `test_the_composition_root_wires_the_profile_s_retrieval_settings`
      passes untouched.*
- [x] 3.2 Reduce `passage_window` to one delegation and delete `_window_for`,
      `_slice` and `_widened` from `search.py`; verify `search()`'s last line
      calls `self._windows.for_results(hits)`. *Both done; Pyright flagged the
      missing attribute at the call site before the suite ran, which is how the
      second edit was found.*
- [x] 3.3 Grep `search.py` for every moved name; verify none remains, and that
      `re` is still imported only if something else in the file needs it. *`re`
      had exactly one user, `_HEADING_LINE`, and `replace` exactly one,
      `_widened` — both imports removed. `Window` stays: `passage_window`'s
      return annotation still needs it. 671 lines to 423.*

## 4. The tests that move

- [x] 4.1 Re-point `tests/test_section_windows.py`'s imports of
      `_section_bounds`, `_widen`, `_avoid` and `MAX_RESPONSE_CHARS` at
      `jackryan.services.windowing`; verify no assertion changes. *One import
      line and two call sites; every assertion in the file is untouched.*
- [x] 4.2 Re-point the `monkeypatch.setattr` at `:211` at the windowing module;
      verify the test still fails when the patch is removed, which is what shows
      the patch reaches the code that reads it. *See 7.3 — and the result
      corrected a claim this plan made.*
- [x] 4.3 Re-point the two direct `context.search._window_for(...)` calls at
      `context.search._windows.around(...)`; verify both still compare a
      with-blocked window against an alone window. *Both do; no shim was left on
      `SearchService`, so a missed re-point would be an `AttributeError`.*
- [x] 4.4 Re-point `tests/test_result_shape.py:179`; verify `search.py` does not
      re-export `MAX_RESPONSE_CHARS`, so a missed re-point is an `ImportError`.
      *Confirmed at runtime, not by reading the import line.*

## 5. The test that could not be written before

- [x] 5.1 Add `tests/test_windowing.py` driving `Windower` with a neighbours
      function over a hand-written list of chunks; verify it constructs no store,
      no context and no casefile. *None of the three. Ten tests in 0.07 seconds
      against four paragraphs declared in the module.*
- [x] 5.2 Assert a window is wider than the passage that matched; verify the
      assertion names the widths, so a failure says which one was wrong. *It
      prints both and says "the rule returned the passage back".*
- [x] 5.3 Assert the window's text equals the document's own text over the
      declared span; verify it is compared against `extracted_text`, never
      against joined chunk texts. *Compared against
      `document.extracted_text[window.char_start : window.char_end]`.*
- [x] 5.4 Assert a heading between the passage and the budget's reach stops the
      window; verify the same input without the heading does widen past that
      point, so the test proves the heading did it. *Two documents identical but
      for one line beginning `##`; both halves asserted, and the control carries
      the message that the other assertion proves nothing without it. Watched
      failing with the forward heading clip removed: the new test and the
      existing `test_a_window_never_runs_past_a_heading_it_would_cross` both red.*
- [x] 5.5 Assert a blocked span narrows the result and sets the flag; verify the
      same call without the block returns a wider window and an unset flag.
      *Both compared in one test. Watched failing with `around` forced to return
      `False`: the new test and
      `test_a_result_clipped_by_another_result_says_it_was_narrowed` both red.*
- [x] 5.6 Assert `for_results` returns the matched passages unchanged in
      identity and order once the response bound is reached; verify nothing is
      dropped, which is what `hybrid-search` requires. *Same chunk ids in the
      same order at a 120-character bound as at 60,000. **The first version of
      this assertion was wrong** — it claimed every narrowed result falls back to
      its passage text, which is false for results narrowed by a neighbour rather
      than by the bound. It went red at once and was replaced by the claim that
      actually holds: every result still carries its passage.*
- [x] 5.7 Assert a neighbours function returning `[]` yields no window; verify it
      fails when `around` is fed neighbours instead, so the test cannot pass on a
      corpus it did not use. *Both halves in one test: `lambda *_: []` gives
      `None`, and the same passage with neighbours gives a window.*

## 6. Documentation

- [x] 6.1 Re-point the `WINDOW_MAX_CHUNKS_EITHER_SIDE` entry in
      `docs/implementation-notes.md`; verify the finding's text is otherwise
      untouched and still says it is parked. *Path only; the finding and its
      recorded fix are unchanged.*
- [x] 6.2 Re-point the `MAX_RESPONSE_CHARS` and `_slice` entries in the same
      file; verify `_slice`'s line number is corrected to its new home rather
      than deleted. *`services/search.py:613` became `services/windowing.py:171`.
      Three further citations that stayed in `search.py` were also corrected,
      because the file lost 256 lines and every line number after 275 had
      shifted: `:534` to `:400`, `:505` to `:366` (twice), `:384` to `:245`. Each
      new number was found by grepping for the code the note describes, not by
      arithmetic — the old numbers were already a few lines stale.*
- [x] 6.3 Add a `docs/handover.md` note saying what this change verified and what
      it did not; verify it states that no window behaviour was re-measured
      because none changed. *It does, and it records the corrected claim from 7.3
      rather than the claim the plan made.*

## 7. Verification

- [x] 7.1 Run `pytest -q`; verify 697 passed and 3 skipped, plus the new module's
      tests — a *lower* count means a test was lost in the move. *707 passed, 3
      skipped: 697 unchanged plus 10 new. 710 after the review round below added
      three more.*
- [x] 7.2 Run `git diff --stat`; verify the lines leaving `search.py` and
      arriving in `windowing.py` match in quantity, since a pure move that does
      not balance is not a pure move. *258 out of `search.py`, 10 back in;
      `windowing.py` is 301, of which 238 are the moved members and the rest is
      the module docstring, the imports, the `Neighbours` alias and the class
      scaffolding. The stronger evidence is 2.3's byte-identity diff, not this
      arithmetic.*
- [x] 7.3 Re-export `MAX_RESPONSE_CHARS` from `search.py` and revert
      `tests/test_section_windows.py:211` to patch `search_module`; verify the
      bound test fails, and record **which** assertion catches it — the
      `assert narrowed` guard reads as though it would, and does not. Undo both
      by inverse edit and confirm with `git status --porcelain`. ***The guard did
      not catch it.*** *It passed, and the test failed three assertions later on
      `all(h.text == h.chunk.text for h in narrowed)`, because `narrowed` is also
      set when a neighbouring result cuts a window back. So the re-export is
      caught only incidentally, by an assertion that holds because the 1,200-char
      bound dominates this fixture. `design.md` and `docs/handover.md` were
      corrected to say so; the guard's weakness is recorded in
      `docs/implementation-notes.md` and left unfixed. Both mutants reversed by
      inverse edit, never `git checkout`; `grep MUTANT` returns nothing and
      `git status --porcelain` shows the three expected modified files.*
- [x] 7.4 Feed `Windower` a neighbours function returning `[]`; verify the new
      widening assertions go red, then undo by inverse edit. *Done as a
      production mutation rather than a test one — `around` forced to
      `neighbours = []`: 7 of 10 red, including all three guard messages.*
- [x] 7.5 Run `openspec validate --all --strict`; verify 18 items pass — 17 specs
      and this change. *18 passed, 0 failed.*
- [x] 7.6 Grep the diff for `sk-`, `hf_`, `AKIA`, `ghp_`, `-----BEGIN`,
      `.ts.net`, `/Users/`, `/home/`; verify nothing matches. *Nothing but this
      line and the one above it, which are the patterns themselves.*

## 8. What review found, and what was done about it

- [x] 8.1 Remove the second copy of the window budget; verify by the mutation
      that previously survived, not by inspection. *`SearchService._window_max_chars`
      was a field beside `Windower._budget` and was read by nothing in `src/`.
      Two reviewers found it independently; the silent-failure review measured
      it: building the `Windower` with a hardcoded `DEFAULT_WINDOW_MAX_CHARS`, or
      with the setting doubled, **each passed all 707 tests**, because
      `tests/test_app.py:170` asserted on the copy. It is now a property reading
      `Windower.budget`. Both mutations re-run and now fail that test —
      `assert 3000 == 1234` and `assert 2468 == 1234`.*
- [x] 8.2 Replace the new bound test's guard with one the bound alone can
      satisfy; verify with the bound disabled. *`assert any(hit.narrowed ...)`
      was the same weak guard this change had just parked as a finding about the
      older test — `narrowed` is set by the neighbour path too. It now counts how
      many results carry a window with and without the bound. With the bound
      raised to `10**12` it fails first, and by name: "as many results were
      widened at a 120-character bound as at 60,000".*
- [x] 8.3 Cover the backward half of `_clip_to_headings`; verify it was
      uncovered before and is caught now. *It was uncovered anywhere in the
      repository — a window could reach back across a heading and pull the
      section above into a fenced, cited result. New test with a positive
      control; watched failing with `matches = []`: "the window reached back
      across a heading into the section above".*
- [x] 8.4 Cover `for_results`' `kept is None` branch; verify it is reachable at
      all before writing the test. *Traced first: it needs an earlier result to
      have returned text inside the later one's own passage, which needs two
      overlapping passages — as a real chunker produces — plus an unmatched
      neighbour so the later one has room to widen. Built exactly that; watched
      failing with the flag forced to `False`: "a result that gave up its window
      entirely did not say so".*
- [x] 8.5 Cover `around`'s budget guard by a property rather than a
      restatement; verify the observable alone does not distinguish it. *It does
      not — deleting the early return leaves `_widen` and `_slice` producing the
      same `None`. What the guard actually buys is not asking the store, so the
      test counts lookups: none at a budget of 1, exactly one at 4000. Watched
      failing with the guard neutered to `budget < 0`.*
- [x] 8.6 Record what review found that is not being fixed; verify each entry
      says why. *Two in `docs/implementation-notes.md`:
      `test_widening_is_switched_off_by_a_budget_at_the_chunk_size` passes at any
      budget because its fixture leaves nothing to widen into, and the store
      lookup is captured at construction so swapping the store on a live service
      is silently ignored. The second is the half of the copy hazard that stayed
      inert; the budget half was live and was fixed.*
- [x] 8.7 Confirm no reviewer left a mutant; verify by diff rather than by a
      green suite. *One of the three reviewers died mid-mutation, with "M4 is a
      surviving mutant" as its last output. `git status --porcelain` and
      `git diff HEAD` were both **empty** — only mtimes had moved — and the suite
      was re-run green afterwards. Checking the diff first is the rule here: a
      green suite after an adversarial review proves nothing.*
