## 1. The rule in the published specs

- [ ] 1.1 MODIFY `layered-configuration`'s three requirements, reproducing every published scenario title verbatim; verify mechanically rather than by eye, since a MODIFIED block omitting one is an archive-blocking error
- [ ] 1.2 Rewrite the enrich-settings paragraph so such a setting enters corpus identity by declaration *or* composition, and add the paragraph requiring an identity derived from shipped code to be composed; verify the argument is the derived-identity one and not the avoided reingest
- [ ] 1.3 Add the paragraph exempting an enrich setting that writes rows and moves no vector; verify the per-document summary is covered by it
- [ ] 1.4 Keep the scenario title *Every setting that changes what is embedded is in the contract* byte-identical and move the new truth into its body, with a sentence in the requirement text saying why the legacy title must stay; verify a retitle is understood as a deletion
- [ ] 1.5 Add the fatal-configuration rules for a quoted boolean and for folding with no summariser named, and the summariser's reachability rule mirroring the reranker's; verify each has a scenario
- [ ] 1.6 MODIFY the fingerprint requirement so identity covers anything that determined the vectors, and state that an absent component contributes nothing; verify the byte-identical guarantee has its own scenario
- [ ] 1.7 RENAME `chunking-and-embedding`'s *What is embedded for a chunk is exactly the chunk's text* and MODIFY it keyed on the new title; verify `FROM` is published, `TO` is not, and no MODIFIED or ADDED block names the `FROM` side
- [ ] 1.8 ADD to `chunking-and-embedding` the requirement that a failed producer of folded context fails the document; verify it states the departure from the reranker's precedent and that a short result is a failure
- [ ] 1.9 ADD to `storage-seam` the derived-text requirement; verify it states the per-row producer rule and the exclusion from the full-text index
- [ ] 1.10 ADD to `untrusted-content-boundary` the derived-text fencing requirement, and edit that capability's published `Purpose` in place; verify the Purpose edit is in the published file, since a delta cannot reach it

## 2. The generation seam

- [ ] 2.1 Create `src/jackryan/summarising/port.py` copying `reranking/port.py`'s shape — `typing.Protocol`, `...` bodies, a `name` annotation with its own docstring, `SummaryError(JackRyanError)` with a `code`, `SummariserUnavailable(ConfigError)`; verify implementations do not inherit the Protocol
- [ ] 2.2 Document on the port that `summarise_chunks` returns exactly one summary per input in input order, and that a short return is an error rather than a pad; verify the docstring says why padding is worse than failing
- [ ] 2.3 Create `src/jackryan/summarising/model.py` with `OpenAICompatSummariser`, the recipe constants and `RECIPE_FINGERPRINT`; verify `name` is `f"{model}/{RECIPE_FINGERPRINT}"` and that `DOCUMENT_PROMPT` is outside `_RECIPE` with a comment saying why
- [ ] 2.4 Split construction from connection as `CrossEncoderReranker` does: `__init__` stores configuration, `check()` builds the client and issues one minimal request raising `SummariserUnavailable` naming the setting; verify `jackryan status` builds no client
- [ ] 2.5 Summarise a document's chunks through a `ThreadPoolExecutor(max_workers=summary_concurrency)` over one pooled `httpx.Client`, reassembling in input order; verify the reassembly is by index and not by completion order
- [ ] 2.6 Create `summarising/__init__.py` with `build_summariser(config) -> SummariserPort | None` returning `None` on an empty `summary_model`, mirroring `build_reranker`; verify the empty case fetches nothing
- [ ] 2.7 Promote `httpx` from `[project.optional-dependencies] dev` to `dependencies` in `pyproject.toml`, with a comment giving connection pooling across roughly 36,000 calls as the reason; verify it is not listed in both

## 3. Profile settings and corpus identity

- [ ] 3.1 Add `summary_model`, `chunk_summaries`, `summary_concurrency` and `summary_timeout_seconds` to `Profile`, each with a docstring in the established style; verify `Contract`, `DEFAULT_CONTRACT`, `Contract.fingerprint` and `_build_contract` are untouched
- [ ] 3.2 Read the four keys in `_select_profile`, `summary_model` through `_interpolate` like `llm_url` and the others not; verify the unknown-key guard picks them up from `Profile.__dataclass_fields__` with no separate list to maintain
- [ ] 3.3 Add `_validated_bool` refusing a string, copying the guard shape `_validated_floor` and `_validated_positive` open with; verify a YAML-quoted `"false"` is fatal rather than truthy
- [ ] 3.4 Make `chunk_summaries: true` with an empty `summary_model` fatal, naming both settings; verify the message says what to do
- [ ] 3.5 Give `corpus_fingerprint` a defaulted third parameter appending `|summariser=` only when non-empty; verify every existing two-argument call site still works and the escaping applies to the new component
- [ ] 3.6 In `build_context`, build the summariser, compute `folding`, and pass the summariser's name into `corpus_fingerprint` only when folding is on; verify a per-document summary alone leaves identity untouched
- [ ] 3.7 Add `summariser` to `build_context`'s parameters beside `reranker`, and pass the summariser and the switch into `IngestionService`; verify the injection seam matches the reranker's
- [ ] 3.8 Add the four settings to `config.yaml.example` with the corpus-coupling warning on the switch; verify the example stays runnable with them commented out

## 4. Storage

- [ ] 4.1 Append the migration step to `_STEPS` adding `chunks.summary`, `documents.summary` and `documents.summary_by`, all `NOT NULL DEFAULT ''`; verify `SCHEMA_VERSION` recomputes itself and no test carries a literal version
- [ ] 4.2 Add `summary` to `Chunk` and `summary`/`summary_by` to `Document`, both defaulted so every existing construction site compiles; verify the columns are absent from `chunks_fts` and `_SIDECAR_TRIGGER` is untouched
- [ ] 4.3 Write `chunks.summary` in `replace_chunks`' existing INSERT and add both document columns to `upsert_document`'s INSERT and `DO UPDATE SET`; verify the overwrite-on-reingest comment gives the same reason `text_source` has
- [ ] 4.4 Add the three columns to the baseline schema so a fresh store and a migrated one agree; verify `test_the_ladder_and_the_baseline_agree` passes

## 5. The fold

- [ ] 5.1 In `_rebuild_chunks`, leave the summariser-absent and switch-off path byte-identical to today's; verify the embed input is still `[c.text for c in chunks]` and `chunks.summary` stays empty
- [ ] 5.2 With folding on, call `summarise_chunks(document.extracted_text, [c.text for c in chunks])`, rebuild each `Chunk` with its summary, and embed `f"{summary}\n\n{text}"`; verify line 382 still hands `replace_chunks` chunks whose `text` is untouched
- [ ] 5.3 Add `SummaryError` to the `except (ValidationError, ExtractionError)` tuple in `_ingest_work`, with `except ConfigError: raise` before it; verify the ordering holds by type rather than by call order, as `services/search.py` does
- [ ] 5.4 Compute the per-document summary after the chunk pass and persist it with a second `upsert_document`; verify `_rebuild_chunks` still owns chunking and the extract/persist flow is not reordered
- [ ] 5.5 Build the document summary from the chunk summaries when folding is on and from the chunk texts when it is not; verify a document with no chunks stores an empty summary rather than calling the endpoint

## 6. Surfaces

- [ ] 6.1 Add `derived_by: str = ""` to `provenance()`, emitted only when non-empty; verify the keyword-only signature is preserved
- [ ] 6.2 Return the document summary from MCP `case_read_document` as a separately fenced field with its own provenance carrying `derived_by` from the stored `summary_by`; verify it is not inside the document text's fence
- [ ] 6.3 Leave MCP `_render_document`, `listing_payload` and `search_payload` unchanged; verify the design records why, since the obvious placement is the one the listing's own docstring forbids
- [ ] 6.4 Add `summary` to REST `serialize_document` and `serialize_hit`, and to CLI `_render_document` and `_render_hit`; verify the CLI table stays readable with a summary present
- [ ] 6.5 Confirm `ANNOTATIONS`, `READONLY_TOOLS`, `INSTRUCTIONS` and `analyst/role.md` need no edit; verify no tool was added or removed

## 7. Verification

- [ ] 7.1 Assert `corpus_fingerprint(Contract(), "model")` equals the recorded identity of the real corpus byte for byte; verify the literal in the test is the string read from `store_meta` rather than one recomposed
- [ ] 7.2 Add the guard that recomputes `RECIPE_FINGERPRINT` from a modified recipe and asserts the name differs; verify this is what replaces a hand-bumped version
- [ ] 7.3 Extend the tripwire with both branches — folding off unchanged, folding on asserting every embedded text equals `f"{summary}\n\n{text}"` read back from the store; verify both vacuity guards survive and the failure message still instructs the reader
- [ ] 7.4 Watch the tripwire fail: fold with the endpoint stubbed and assert the store holds no chunks for a document whose summariser failed; verify the negative is asserted directly rather than inferred from a status
- [ ] 7.5 Make `summarise_chunks` return a short list temporarily and confirm `SummaryError` rather than a pad; verify the test names the finer-grained corruption
- [ ] 7.6 Add the config tests — a named-but-unreachable summariser fatal, an unnamed one not an error, `chunk_summaries: "false"` refused, `true` with no model fatal; verify the first two mirror the two published reranker scenarios
- [ ] 7.7 Extend `tests/test_mcp_fencing.py` with the derived-text case: a summary containing a literal fence marker ends up inside the real fence and `provenance` reports `derived_by`; verify the marker in the summary does not terminate the fence
- [ ] 7.8 Copy the real corpus to `/tmp` and open it: verify it migrates to schema 6, opens, and reports the identity string unchanged — copied first, because opening it migrates it and would write a 435 MB backup beside the original
- [ ] 7.9 Turn folding on against the same copy: verify startup is refused, the message names both identities, and the configured one carries `|summariser=`
- [ ] 7.10 Run the end-to-end check against a live OpenAI-compatible endpoint behind a module-local `JACKRYAN_LLM_TESTS=1` gate declared as `needs_models` is in `tests/test_quality_gate.py`; verify every chunk of the `sectioned_corpus` fixture carries a non-empty summary
- [ ] 7.11 Run `pytest -q` with `PYTHONPATH` pointed at the worktree's `src`; verify the suite is green and that the editable install has not resolved `jackryan` from the main checkout
- [ ] 7.12 Run `scripts/evaluate_retrieval.py`; verify the figures have not moved, since folding is off by default and a moved figure means something was folded that should not have been
- [ ] 7.13 Run `openspec validate --all --strict` and re-run the mechanical title audit; verify validate passing is not treated as proof the delta applies

## 8. Prose

- [ ] 8.1 Correct `docs/design.md` § 5 step 2 and `docs/handover.md`'s M3 table row: the switch is corpus-coupled but lives in the profile and enters identity by composition, not in the contract block; verify a grep across `docs/`, `CLAUDE.md` and `README.md` leaves no other place describing it as a contract value, relaxing the pattern across markdown emphasis so `**contract**` is not missed
- [ ] 8.2 Rewrite `CLAUDE.md`'s embed-input pitfall to say identity is composed rather than declared, and add the new-egress note; verify the pitfall still says the tripwire failing is a signal about identity rather than a signal to update the test
- [ ] 8.3 Record in `docs/handover.md` what this change ships, what it deliberately leaves — the retrieval measurement — and that mentions are next; verify the M3 table row is struck through rather than deleted, as the others are
