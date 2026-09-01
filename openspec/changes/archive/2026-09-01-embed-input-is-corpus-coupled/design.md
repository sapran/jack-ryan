## Context

See proposal.md § Why for motivation. Four properties of the code as it stands shape everything below.

**One line decides what is embedded.** `IngestionService._rebuild_chunks`
(`src/jackryan/services/ingestion.py:381`) is `self._embedder.embed_documents([c.text for c in
chunks])`, and it is the only caller of `embed_documents` on the ingest path. Everything this change
guards passes through that expression.

**The heading path is already there and already excluded.** `chunk_text` computes `piece.heading_path`
and `_rebuild_chunks` stores it on the `Chunk` (line 374) without embedding it. So the folding-in this
change forbids has two candidates today, not one, and both are a one-word edit.

**Corpus identity is composed, not declared.** `Contract.fingerprint()` (`config.py:92`) covers the
five contract values; `corpus_fingerprint` joins it with the embedder's name, at the composition root,
because two copies of one setting can disagree. `Context.corpus_fingerprint` (`app.py:30`) is a
required field holding exactly the string the store enforces — so the retrieval harness can read the
enforced identity rather than reconstructing it.

**Every contract value must be consumed.** `tests/test_config.py:137-152` asserts that `Contract`'s
dataclass fields and `DEFAULT_CONTRACT`'s keys have not drifted apart and that every field appears in
the fingerprint. That test is why the contract half of this hole is already closed mechanically — and
why adding a declared value nothing reads is not available as a move.

## Goals / Non-Goals

**Goals.** State where a setting that changes embed input belongs. Make the day someone folds context
in a day a test fails, naming the rule. Make the instrument that will be used to argue for the feature
refuse to compare across corpora.

**Non-Goals.** Building any part of the enrich stage. Adding the contract field for summaries. Moving
the recorded baseline figures.

## Decisions

### The rule is a test on embed input, not a named on/off switch

The obvious shape for this guard is a contract boolean — `contextual_summaries: true|false` — and it
is not sufficient. A summary is written by a model. A different model writes different summaries, so
two corpora can agree that summaries are on and still hold vectors built from different text. The
switch closes the hole one level up and reopens it one level down.

So the rule is stated as a property of the bytes handed to the embedder: any setting that changes them
is corpus-coupled, and that necessarily includes the identity of whatever produces them. When the
feature lands, the contract must carry both the switch and the summariser's identity — the same shape
already used for `embed_model` plus `embed_library`, where the model alone was not enough either.

This also gives the classification test a form that does not depend on pipeline stages. "Enrich
settings are contract" would be wrong as a blanket claim — a per-document summary or a NER pass writes
rows beside the evidence and touches no vector. The test is not which stage a setting belongs to, but
whether it changes what the embedder is given.

### No contract field is added now

Adding `contextual_summaries` today would declare a value the pipeline does not read, which
`tests/test_config.py:137-152` fails on by design, and it would fix a name and a vocabulary before the
feature that has to live with them exists. The invariant it would break is one of the better ones in
this project: the fingerprint covers exactly what determines corpus identity and nothing else. A
decorative field weakens it for everyone.

The contingency if that reading is ever challenged: the field would have to arrive with the
summariser's identity in the same commit, since a switch without it is the hole described above.

### The tripwire records what the embedder is given, and recomputes the expectation independently

The test wires a `_RecordingEmbedder` subclassing `DeterministicEmbedder` through `build_context`,
which is the seam `tests/conftest.py` itself uses. Subclassing keeps `name = "deterministic"`, so
corpus identity is unchanged and the fresh `tmp_path` store is not refused.

The expectation is recomputed with `chunk_text` from each document's `extracted_text` rather than read
back from the store. Chunking is deterministic by spec (`chunking-and-embedding`, *Chunking is
reproducible*), so this is a legitimate independent expectation — and reading the stored chunk texts
would compare the pipeline against itself, passing on any transformation applied before both the store
write and the embed call.

Comparison is of **sorted multisets**, not positional. Ingestion runs in a thread pool from M1, so the
order of per-document `embed_documents` calls is not guaranteed. The multiset still fails on any
prefix, suffix or substitution of any text, which is the whole assertion. The strengthening a future
reader might want — pairing texts with their document — is not available: the port takes only texts,
and giving the recording embedder more than the port carries would be testing something the pipeline
does not do.

Two vacuity guards ride along, because both failure modes are silent: the recorded list must be
non-empty, so a pipeline that embedded nothing cannot pass; and at least one recomputed piece must
carry a non-empty `heading_path`, so a corpus that cannot exercise the heading-path case cannot claim
to. The second is why the fixture is `sectioned_corpus` rather than `corpus` — the pitfall recorded at
`CLAUDE.md:154` is exactly this, three window tests that passed while proving nothing.

### Comparability is corpus identity, and an absent key is a mismatch

`conditions_match` compares `if key in recorded`. That is right for a key added for readability — an
older baseline that does not record `window_max_chars` should not be rejected for it. It is fail-open
for a key that decides comparability: a baseline recorded before corpus identity was carried would
compare clean against a run over an entirely different corpus, which is the exact scenario this change
exists to prevent.

So `REQUIRED_CONDITIONS` names the keys whose *absence* is itself a mismatch, and `corpus` is the only
member. `chunk_max_chars` stays in the compared list even though corpus identity subsumes it: it is
readable to an operator at a glance where a 130-character identity string is not, and removing it
would change the recorded baseline's shape for no gain.

`corpus` is printed on its own line rather than inside the comma-joined `Conditions:` line for the
same length reason.

### The shipped baseline is annotated, not re-measured

`docs/retrieval-baseline.json` gains a `corpus` condition stating the identity those figures were
produced under. It is not re-measured, and no metric moves.

The identity is derivable rather than guessed, and every step is checkable: the file records
`"embedder": "model"` and `"chunk_max_chars": 2000`, which is the default; it was recorded 2026-08-28,
after the `embed_library=fastembed==0.8.0` pin landed on 2026-08-26; `DEFAULT_CONTRACT` has not moved
since, which `git log --since=2026-08-28 -S...` confirms as empty for both `embed_model` and
`chunk_overlap_chars`; and `tests/test_config.py:436-439` pins that exact string as today's default
identity.

Re-recording instead would reset the quality bar to whatever today's run produces.
`openspec/specs/retrieval-evaluation/spec.md` requires that recording a baseline be a deliberate act —
adding a metadata field is not a reason to move figures. A test asserts the shipped baseline states a
non-empty corpus, so a later `--record` or hand edit cannot quietly restore the fail-open.

## Risks / Trade-offs

**The tripwire pins present behaviour, and present behaviour is what M3 intends to change.** That is
the point rather than a cost, but it must be legible: the test failing is the signal to add the
contract value, not to update the test. The requirement text and the `CLAUDE.md` bullet both say so in
those words, because a future session reads one of them and not the other.

**A stricter harness is a louder harness.** Any run whose corpus identity differs from the baseline's
now reports "not compared" where it previously compared on settings alone. This is the intended
behaviour and it is fail-closed; the cost is that a deterministic-embedder run, which already differed
on `embedder`, now differs on two keys. The harness is not a CI gate — CI runs pytest, gitleaks and a
Docker build and nothing else — so no pipeline can break on it.
