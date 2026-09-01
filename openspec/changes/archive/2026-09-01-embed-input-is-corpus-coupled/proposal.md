## Why

`docs/design.md` § 5 step 2 puts per-chunk contextual summaries in the Enrich stage and calls the
setting that turns them on "a config switch". Contextual retrieval works by folding the summary into
the text that gets embedded. Nothing in the corpus contract covers that, so enabling it would append
vectors built from one kind of input to a corpus of vectors built from another — both the declared
width, both well-formed, corpus identity unchanged, and no error anywhere.

That is precisely the failure `corpus_fingerprint` exists to catch, and it would walk straight past
it. Three things are missing today and each is a separate hole:

1. **No normative rule.** `openspec/specs/layered-configuration/spec.md` classifies extraction
   settings (profile) and retrieval settings (profile) with reasons, and names the embedder as the one
   profile-layer exception. It never says where a setting that changes the *text handed to the
   embedder* belongs. It also asserts the contract's coverage claim in one direction only — "every
   declared value is one the pipeline reads" — never the converse.
2. **No tripwire in code.** `src/jackryan/services/ingestion.py:381` is the single line that decides
   what gets embedded: `[c.text for c in chunks]`. Nothing asserts that. `heading_path` is already
   computed and stored and deliberately not embedded, so there are two future foldings-in, not one,
   and both are one keystroke.
3. **The instrument that would report the harm is blind too.** `scripts/evaluate_retrieval.py`
   establishes comparability against the tracked baseline over a hand-enumerated key list
   (`embedder`, `reranker`, `query_set`, `chunk_max_chars`, `window_max_chars`, `limit`, `queries`,
   `documents`) — not over corpus identity. The M3 case for turning summaries on will be argued with
   this harness, and it would print "comparable" while measuring two different corpora.

**This pulls no deferred work forward.** It adds no enrich capability, no contract field and no
behaviour. It records a classification rule and two guards for a change that stays deferred to M3.
The reason it cannot wait is that this guard cannot be added retroactively: once a corpus holds
vectors built from chunk text beside vectors built from summary-prefixed text, nothing can separate
them, and the only remedy is a reingest nobody knows is needed. The guard has to exist before the
feature, or it protects nothing.

## What Changes

**Current behaviour.** Ingestion embeds each chunk's own text and nothing else, which is correct — but
it is correct by accident of how the line is written, not by any stated rule. No spec says a setting
that changes embed input is corpus-coupled. No test fails if a heading path or a summary is folded in.
The retrieval harness compares a run to the baseline over a list of settings that does not include
corpus identity, and silently skips any key the baseline does not record.

**Desired behaviour.**

- **A setting that changes the bytes handed to the embedder is a contract setting**, together with the
  identity of whatever produces those bytes. Stated in `layered-configuration` beside the two
  classifications already there, on the reasoning already accepted for the embedding library version.
- **The contract's coverage claim holds in both directions.** Every declared value is read by the
  pipeline, *and* every setting that determines a stored vector is declared there.
- **What is embedded for a chunk is exactly that chunk's text**, stated as a requirement in
  `chunking-and-embedding` and asserted by a test that records what ingestion hands the embedder. The
  heading path is recorded and not embedded, and that stays true by assertion rather than by habit.
- **Comparability is established over corpus identity**, not over a chosen list of settings. A
  baseline that states no corpus identity is reported as not comparable rather than compared on the
  settings it does state — a key absent from the baseline is silently skipped by a check that only
  compares what is present, which turns the guard into a fail-open.
- **The prose a future session reads says it too**: `CLAUDE.md`'s pitfall list, and the two places in
  `docs/design.md` that describe the summaries switch as infrastructure.

**Deliberately not in scope.** No contract field is added for the summaries switch. A boolean alone
would leave the same hole one level down — a different summarising model writes different summaries,
so the switch is not sufficient without the summariser's identity — and a declared value nothing reads
would break the invariant `tests/test_config.py:137` enforces mechanically. The field belongs with the
feature; the rule that governs it belongs here.

## Impact

- Affected specs: `layered-configuration` (MODIFIED), `chunking-and-embedding` (ADDED),
  `retrieval-evaluation` (MODIFIED)
- Affected code: `scripts/evaluate_retrieval.py`, `tests/test_embedding.py`,
  `tests/test_evaluate_retrieval.py`, `docs/retrieval-baseline.json`
- Affected prose: `CLAUDE.md`, `docs/design.md`, `docs/handover.md`
- No production source file changes behaviour. `src/jackryan/services/ingestion.py` is read, not
  edited: the change asserts what it already does.
