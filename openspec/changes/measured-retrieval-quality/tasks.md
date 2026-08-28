## 1. The measurement, before anything it would measure

- [x] 1.1 Write the synthetic evaluation set as module constants in
      `scripts/evaluate_retrieval.py` — invented documents in the existing harbour
      register, in English, Ukrainian and Russian, with at least two distractor
      documents that answer nothing; verify a test asserts every judgement names a
      document present in the set and every language is represented.
- [x] 1.2 Include at least one query per language whose wording shares no content
      word with the passage that answers it; verify a test asserts, for those
      queries, that the query's tokens and the answering phrase's tokens are
      disjoint.
- [x] 1.3 Key each judgement to `(filename, phrase)` rather than to a chunk id;
      verify a test ingests the same corpus twice and asserts the judgements
      resolve identically both times.
- [x] 1.4 Implement `recall@k` and `mrr@k` as pure functions over a ranked list and
      a judgement; verify unit tests cover a hit at rank 1, a hit at rank k, a miss,
      and an empty ranking.
- [x] 1.5 Build the corpus in a temp workspace and rank through
      `context.search.search`, with the keyword and vector legs read separately from
      `context.store` for attribution; verify a test asserts the harness computes no
      ordering of its own — the fused ranking it scores is the service's.
- [x] 1.6 Report a metric table naming the embedder, the reranker or its absence,
      and the query set; verify a test asserts a report produced with the
      deterministic embedder is marked as measuring the mechanism, not quality.
- [x] 1.7 Add `--record`, `--baseline`, `--corpus`, `--queries`, `--keep` and
      `--reranker`, following `scripts/verify_model_paths.py`'s argument and
      exit-code conventions; verify `--help` runs with no model download and a test
      asserts an ordinary run leaves the baseline file unmodified.
- [x] 1.8 Compare against the tracked baseline and exit non-zero below it, naming
      each metric that fell and by how much; verify a test feeds figures below a
      fixture baseline and asserts a non-zero exit naming the fallen metrics.
- [x] 1.9 Run the harness with the real embedder and with the deterministic one,
      and commit the real-embedder figures as the baseline; verify the two runs
      report different figures, which is what proves the measurement can move.
- [x] 1.10 Break a tied fused score by properties of the corpus — the passage's
      ordinal and its text — rather than by any identifier; verify a test
      constructs a tie whose chunk and document ids are both in the opposite
      order to the passages, and asserts the passages decide.
      *Amended: not in the original plan, and corrected once. The first
      measurement was not reproducible — the same corpus, reingested, moved one
      query from rank 3 to rank 2 and shifted fused MRR by 0.014. Exact ties in
      reciprocal rank fusion were being broken by `chunk_id`, minted afresh on
      every reingest. Breaking them by the document and the ordinal fixed the
      reingest case but not the real one: two runs of the harness still
      disagreed, because each builds a new store and a document's id is fresh
      there too. Ties are now broken by the ordinal and the passage text, both
      properties of the corpus. Two consecutive runs then reported identical
      figures where they had differed by 0.058 recall@1. A measurement that
      cannot be reproduced cannot detect a regression, so this is a precondition
      of the phase rather than a neighbouring improvement.*

## 2. Section-window expansion

- [x] 2.1 Add a window rule to the service layer that takes a document's extracted
      text and a matched chunk's offsets and returns one contiguous span; verify
      tests assert the span contains the chunk's text, is a slice of
      `extracted_text`, and never repeats overlap.
- [x] 2.2 Bound the window by `window_max_chars`, by the document's edge, and by a
      heading boundary where `heading_path` is non-empty; verify tests cover a
      mid-section match, a match at a section boundary, and a document with no
      headings at all.
- [x] 2.3 Carry both spans on `SearchHit` — the span returned and the matched
      chunk's span — leaving `chunk` and its identifiers unchanged; verify a test
      asserts the returned span contains the chunk span and that `char_start` /
      `char_end` of the chunk still round-trip through `extracted_text`.
- [x] 2.4 Narrow any result whose window would overlap one already returned in the
      same response, to its chunk if necessary; verify a test with two matches in
      one section asserts no text appears twice across the response.
- [x] 2.5 Apply a response-level character budget across all results and mark the
      response when it narrowed anything; verify a test asserts a response of wide
      windows stays within the bound and reports that it was narrowed.
- [x] 2.6 Move `case_get_passage` onto the same window rule, with provenance
      describing the span it actually returns and separately naming the matched
      chunk; verify a test asserts the payload's declared span covers all text
      returned, which it does not today.
- [x] 2.7 Re-run the harness with widening on and with it off; verify the figures
      are identical, which is what shows a window changes what is read and not
      what is ranked.
      *Amended: the task expected windows to move the numbers. They cannot, and
      should not: a judgement is scored against the passage the retriever chose,
      not against how much text was returned around it. Scoring the window
      instead would let a result count as relevant because the answer happened to
      fall inside the context, which measures the budget rather than the
      retrieval. Measured both ways: fused recall@1 0.882, MRR 0.926, identical.*

## 3. Reranking

- [x] 3.1 Add `src/jackryan/reranking/` with a `RerankerPort`, a fastembed
      `TextCrossEncoder` implementation and `build_reranker`, mirroring
      `src/jackryan/embedding/`; verify a test with a stub reranker asserts the port
      is called with the query and the candidates' chunk texts.
- [x] 3.2 Add the `reranker_model`, `rerank_depth` and `window_max_chars` profile
      keys with validation in the shape of `_validated_ocr_engine`; verify tests
      assert an unknown key is fatal, an empty `reranker_model` means off, and a
      non-positive `rerank_depth` is refused.
- [x] 3.3 Wire the reranker into `SearchService` at the composition root; verify a
      test asserts an instance with no reranker configured returns the fused order
      and reports that it was not reranked.
- [x] 3.4 Deepen retrieval to `max(limit * 5, rerank_depth)` and move the `[:limit]`
      slice after the rerank stage; verify a test asserts the reranker is offered
      more candidates than the caller's limit, and that every returned chunk was
      returned by at least one retriever.
- [x] 3.5 Score candidates on chunk text, before windows are computed; verify a
      test asserts the text handed to the reranker is the chunk's, not a widened
      window — the library truncates the pair silently and a score for a fragment
      nobody chose is worse than no score.
- [x] 3.6 Add `rerank_score` beside `score` and a per-response statement of which
      stage ordered the results; verify a test asserts the fusion score is unchanged
      by reranking and both values are present.
- [x] 3.7 Make a named reranker that cannot be constructed fatal, naming the
      setting; verify a test asserts a profile naming a nonexistent reranker raises
      rather than searching in fused order.
- [x] 3.8 Make a reranker that raises while scoring degrade to the fused order with
      the response marked not reranked; verify a test with a reranker that raises
      asserts the search succeeds, the order is the fused one, and the response says
      so.
- [x] 3.9 Run the harness with a reranker named and record the result in
      `docs/handover.md` with the model, its licence and the measured deltas; verify
      the per-language figures are reported separately, since a gain in English says
      nothing about Ukrainian.
      *Both registered candidates were measured and both made retrieval worse.
      `Xenova/ms-marco-MiniLM-L-6-v2` (apache-2.0, English-only) took fused
      recall@1 from 0.882 to 0.176 and Ukrainian and Russian to 0.000.
      `jinaai/jina-reranker-v2-base-multilingual` (cc-by-nc-4.0) took it to 0.529,
      leaving English unchanged and Ukrainian at 0.000. Traced: for a Ukrainian
      query the cross-encoder ranks English passages above the Ukrainian passage
      that answers it. The wiring was checked before the conclusion — the model
      orders unambiguous pairs correctly in all three languages, the service
      returns descending rerank order, and recomputed scores match what it
      recorded. Rerank therefore ships off, as designed, and the gain the leg was
      meant to deliver does not yet exist to be had.*

## 4. The adapters

- [x] 4.1 Carry the returned span, the matched chunk's span, `rerank_score` and the
      rerank statement into the MCP search payload, and name both spans in
      provenance; verify tests assert the fence still wraps each body exactly once
      and `formatted` still has one line per result.
- [x] 4.2 Add the same fields to the REST and CLI JSON shapes, including `read_as`
      on a search hit, which both omit today while the agent surface carries it;
      verify tests assert every adapter reports the same spans for one hit.
- [x] 4.3 State in the tool description that a rerank score is comparable only
      within one response and is not a confidence; verify a test asserts the wording
      is present on the search tool.
- [x] 4.4 Confirm the MCP result ceiling still holds now that a result may be wider
      than a chunk; verify a test asserts an over-large limit is clamped and the
      response stays within the character budget.

## 5. Prove the tests can fail

- [x] 5.1 Reintroduce each of these defects in turn, watch the named test go red
      with the reported symptom, and restore: a window assembled by joining chunk
      texts; a window that ignores the heading boundary; overlapping windows in one
      response; a rerank score written over the fusion score; a construction failure
      that degrades instead of raising.
- [x] 5.2 Drop one judgement's answering document from the evaluation corpus and
      confirm the harness's recall falls and it exits non-zero against the baseline;
      restore, and record in the commit that the gate was seen to fail.

## 6. Documentation

- [ ] 6.1 Add the three profile keys to `config.yaml.example` with the comment
      explaining that they are profile, not contract, and that no reranker is named
      by default; verify a test asserts the example file loads.
- [ ] 6.2 Add the reranker prefetch line to the `Dockerfile` under the existing
      `PREFETCH_MODELS` build arg, taking effect only when a model is named; verify
      the default build is unchanged in size.
- [ ] 6.3 Record in `docs/handover.md` what the measurement settles and what it does
      not, with the baseline figures, the machine and the date, in the shape of the
      existing verification tables.
- [ ] 6.4 Update `CLAUDE.md` — retrieval quality is now measured; the reranker's
      two failure modes; that retrieval settings are profile and leave no residue;
      and that a rerank score is not a confidence.
- [ ] 6.5 Park anything found and not fixed in `docs/implementation-notes.md`, one
      line each: what, where, why parked.
