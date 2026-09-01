# Implementation notes

Findings surfaced during work that were deliberately not fixed at the time, so
that a change stays the size it was scoped to be. Each line says what, where,
and why it was parked.

## Parked

- **A filename ending in a quote character defeats format routing entirely.**
  Five documents in the first real dump (1,922 files, Russian institutional
  material) are named `'…docx'` and `'…doc'` — the shell-style quotes are part
  of the filename, baked in by whatever exported them. `FormatRouter` keys on
  `Path.suffix`, which reads `.docx'`, so `Обновлён. Ответственные по БД.docx`
  and four siblings are refused as an unknown format rather than read as the
  DOCX they are. The refusal is honest and per-file, so nothing is lost
  silently, but a corpus assembled by an export tool can carry a whole class of
  these. Parked: the fix is content sniffing as a fallback when the suffix is
  unknown, which is a wider change than trimming punctuation, and trimming
  punctuation would be a guess about which characters are decoration.

- **A `.docx` can fail inside docling with a conversion error, and the message
  does not say what the document did wrong.** `Анкета для сверки персональных
  данных.docx` raises `could not extract … with docling: Conver…` where its
  three neighbours in the same dump raise the honest `produced no usable text`.
  One file in 1,599 supported ones, so it is rare rather than structural, and it
  is correctly reported as a failure rather than stored empty. Parked: worth a
  look only if a second instance appears, since one sample cannot tell a
  malformed document from an extractor bug.

- **Fifteen page-bearing PDFs escalated through the recognition ladder and still
  yielded nothing.** All from the first real dump, and the names say what they
  are: `Брыкин.pdf`, `Романенков.pdf`, `Сенникова.pdf`, `Абдуллаев.pdf` and
  similar — personal documents that were photographed rather than scanned.
  `Брыкин.pdf` carries zero font objects and five embedded images, so it is
  image-only, rung one had nothing to find, and `rapidocr` under `eslav`
  returned nothing usable from the photograph. Others in the set (`3-4
  курсы.pdf`, 36 font objects, no images) do carry text structure and still
  produced nothing, which is the more interesting half. The designed answer to
  the first half is rung three, and `vlm_model` is empty by default because it
  downloads weights and is much slower. Parked: this is the measurement that
  should decide whether rung three is worth recommending, and it needs the
  scanned-documents slice of M3 rather than a note.

- **`embed_url`, `llm_url` and `api_key` are read into `Profile` and consumed by
  nothing.** `grep` finds them only in `config.py`. They are reserved seams, and
  `config.yaml.example` describes the `remote` profile as though pointing them at
  an endpoint did something. Measured 2026-09-01 on a GB10 box: `bge-m3` over an
  OpenAI-compatible endpoint embeds a contract-sized chunk in **27 ms** against
  the local e5-large's ~96 ms implied by the 1502-document production ingest, at
  the same 1024 dimensions — so the seam is worth roughly 3.5x on the dominant
  ingest cost, and two boxes double it. Parked: it needs an `EmbedderPort`
  implementation plus the endpoint and remote model name entering corpus identity,
  and it forces one full reingest. Do not describe the `remote` profile as
  working until it is.

- **A third reranker exists that the rerank measurement never saw.**
  `bge-reranker-v2-m3` is multilingual and serves `/v1/rerank` on the GB10 boxes;
  probed 2026-09-01 it ranked a Russian query correctly (1.83 against -11.04 for
  an unrelated passage). The parked decision to ship reranking off was measured
  against the only two models `fastembed` registers, both of which took Ukrainian
  to zero. Retrieval settings write nothing and invalidate no store, so this is
  testable against `scripts/evaluate_retrieval.py` with no reingest — the
  cheapest open quality win in the project.

- **Offloading docling to a GPU server is not worth it for born-digital files and
  is actively harmful for scans as that server is configured.** Measured against
  `docling-serve` 1.26.0 (CUDA image, `DOCLING_DEVICE=cuda`): the async endpoint
  reaches 4.64 files/s on DOCX against ~5 files/s in-process, and the *sync*
  endpoint manages 0.48 files/s and does not scale — identical throughput at
  parallelism 1, 4 and 12. Worse, its OCR cannot read Cyrillic: the same scan
  returns byte-identical output with **zero** Cyrillic characters under
  `easyocr`, `tesserocr` and `rapidocr` after clearing both `/v1/clear/results`
  and `/v1/clear/converters`, so `ocr_engine` and `ocr_lang` are ignored, while
  local `rapidocr`+`eslav` reads the same file correctly. `docs/design.md` § 5
  offers "optional out-of-process offload for throughput"; the measurement says
  the throughput is not there and the quality would regress. Parked as a
  do-not-do until the server's model cache carries non-Latin OCR models.

- **A transport-level failure reaching Hugging Face kills an ingest instead of
  falling back.** `fastembed`'s `download_model`
  (`common/model_management.py:444`) catches only `EnvironmentError`,
  `RepositoryNotFoundError` and `ValueError` before trying `url_source`, the
  GCS tarball. `huggingface_hub` 1.29 talks `httpx`, which raises
  `httpx.ConnectError` and does no Happy Eyeballs — so on a host whose IPv6 is
  advertised but dead it takes the AAAA record, fails with `[Errno 65] No route
  to host`, and the working GCS mirror is never attempted. `ModelEmbedder._load`
  then reports `could not load embedding model`, which names the model and hides
  the network. Found priming the cache on the development Mac 2026-08-31, worked
  around by fetching the weights with `curl -4` straight into the cache layout;
  fastembed's own first attempt is `local_files_only=True`, so a populated cache
  needs no network at all. Parked: the honest fix is for the embedder to say
  which host it could not reach, and it belongs with the prefetch story rather
  than in a slice of its own.

- **A FastAPI test client and the agent surface's servers, built in one test
  module, abort the interpreter at teardown.** On macOS the suite reports every
  test passing and the process then exits 134 with
  `libc++abi: recursive_mutex lock failed` — a green summary and a failing exit
  code, which is the worst shape a CI failure can take. Bisected: deselecting
  either the module's REST tests or its MCP tests makes it clean, and each half
  is used elsewhere in the suite without trouble. `tests/test_result_shape.py`
  therefore compares the REST shape through `serialize_hit` rather than over
  HTTP, and `tests/test_rest.py` covers the route. **That reduced it and did not
  remove it** — it was still seen once in six runs afterwards, so do not read the
  change as a fix.

  **CI is unaffected, and that was checked rather than assumed.** The suite was
  run three times inside the project's own image — Linux, the platform every
  workflow uses — and reported `422 passed, 2 skipped` with exit code 0 each
  time, with no abort. The message is libc++'s, which is macOS's C++ runtime;
  Linux uses libstdc++ and does not reproduce it. Parked: the cause is a native
  teardown race below Python — onnxruntime and torch are imported by every run
  through `docling` — and finding it properly means debugging something this
  project does not own. Worth knowing before writing another test module that
  mixes the two, and worth re-checking if the suite ever fails in CI with a green
  summary.

- **A window reaches at most three passages either side, whatever the budget
  says.** `WINDOW_MAX_CHUNKS_EITHER_SIDE` in `src/jackryan/services/search.py`
  caps how far a result may wander from what actually matched, and it is a
  constant rather than a setting. An operator who raises `window_max_chars` far
  above the chunk size therefore gets less than they asked for, silently. Found
  while building the window rule. Parked: the honest fix is to derive the reach
  from the budget and the chunk size together, which needs the contract in the
  search service, and that is a wider change than this slice.

- **The response character bound governs the context added, not the passages
  found.** `MAX_RESPONSE_CHARS` stops results being widened once the response is
  full, but the matched passages themselves are always returned — fifty results
  at the contract's chunk size still exceed it. That is deliberate, and it is
  written into the `hybrid-search` spec: dropping evidence to save characters is
  a worse failure than a long response. Recorded because the constant's name
  reads like a hard ceiling and is not one.

- **Reranking is built and no model is recommended — now measured three times.**
  Both cross-encoders the embedding library registers made retrieval measurably
  worse on the project's evaluation set, and both took Ukrainian to zero; the
  figures and the trace are in `docs/handover.md`. A third model,
  `BAAI/bge-reranker-v2-m3` — the multilingual flagship, which `fastembed` does
  not register — was measured on 2026-09-01 over an OpenAI-compatible
  `/v1/rerank` endpoint, with the port implemented in a throwaway script and
  `build_reranker` substituted for that process only. Same harness, same
  built-in query set, same embedder, control run reproducing the recorded
  baseline exactly. It reproduced the same failure: fused recall@1 **0.882 ->
  0.647** and MRR@10 **0.926 -> 0.778**, English improving **0.714 -> 0.857**
  while Russian fell **1.000 -> 0.600** and Ukrainian **1.000 -> 0.400**.
  English improving is the evidence the wiring worked, so this is the model and
  not the integration. Three of three cross-encoders now trade this corpus's
  languages for English. The seam is finished and the setting stays empty.
  Parked: the pattern is strong enough that the next attempt should be a
  multilingual reranker chosen on Slavic evaluation results rather than on
  reputation, and 17 queries over 15 synthetic documents is still too small to
  settle it either way.

- **Keyword ranking inside one casefile depends on what the other casefiles
  hold.** `search_keyword` in `src/jackryan/storage/sqlite.py` filters rows by
  `c.casefile_id`, but orders them by `bm25(chunks_fts)`, and FTS5 computes bm25
  over the whole index — every casefile in the store. Adding a second casefile
  therefore changes the term statistics and can reorder results inside the first,
  as measured while building the evaluation harness: the same corpus in a second
  casefile scored differently on every keyword metric. No content crosses the
  boundary — the compartment holds for what is returned — but the *order* of a
  casefile's own results is influenced by material it cannot see, which is a
  weak side channel as well as a reproducibility problem. Found while writing
  `scripts/evaluate_retrieval.py`. Parked: the remedies (a per-casefile FTS
  index, or ranking by a statistic computed within the compartment) are a change
  to the storage seam and to what `hybrid-search` guarantees, not a line in a
  retrieval-quality slice.

- **Originals are never archived, though `docs/design.md` § 5 says they are.**
  The Finalize step of the ingestion pipeline is documented as "originals
  archived content-addressed within the casefile". Nothing in
  `src/jackryan/services/ingestion.py` does that: a file ingested from disk is
  read at the analyst's own path and never copied, and a document expanded out
  of a container is written to a `mkdtemp` workspace that is `rmtree`'d in a
  `finally`. The consequence reaches further than the missing feature — every
  document that says "reingest" as its remedy, including the corpus-identity
  refusal and the schema-migration floor, assumes the operator still holds the
  originals, which is precisely what the design said the workbench would hold
  for them. Found while designing the migration ladder, where "reingest is the
  migration path" was one of the three candidate approaches and was weakened by
  exactly this. Parked: archiving originals is a capability with its own storage
  and identity questions, not a line in a migration change.

- **A reingest does not reproduce a document's identifiers, and nothing records
  where a casefile was ingested from.** Both surfaced while judging migration
  approaches. Recording an ingest root would make "reingest" an actionable
  instruction rather than a hopeful one, and deriving document identifiers from
  content plus containment path would let a rebuild reproduce the citations an
  analyst has already written down. Together they are the natural next change
  after this one, and both alter what identity means, so they belong in a change
  with its own delta spec rather than grafted onto this one.

- **`read_as: text-layer` is the strongest provenance the surface offers, and
  nothing checks the page it claims to come from.** Rung one reads the PDF's
  content stream. Text an adversary rendered invisibly — white on white, behind
  an image, at zero size — is in that stream, is never displayed, and reaches
  the agent labelled as having come off the page: the value that says "trust
  this more than OCR". Found by review of the `extraction-quality-gate` change.
  Parked: detecting it means rendering the page and comparing it with the
  stream, which is a different capability from the escalation ladder and would
  need its own evidence about false positives. Worth doing before this workbench
  is pointed at documents supplied by an opposing party.

- **The escalation floor is a whole-document average.** `chars_per_page` divides
  total recovered characters by page count, so whether page 40 gets recognised
  depends on how much text sits on pages 1-39 — and whoever supplies the
  document chooses that. A hundred-page report with one scanned insert clears
  the floor comfortably and the insert is never read. Parked: `design.md` names
  per-page rung selection as a non-goal for this change, and doing it properly
  means the rung becomes a property of the page rather than the document, which
  changes what `text_source` means. Real, and the reason to revisit it is a
  corpus where it bites.

- **The vision rung runs on an unpinned `transformers`, and it produces corpus
  text.** Observed during the same image build: the container resolved
  `transformers 5.16.1` where the development venv holds 5.8.1. It reaches the
  project only transitively, through `docling-slim[models-vlm-inline]`, so
  nothing pins it — yet when `vlm_model` is set it is the library that reads the
  page, and what it returns becomes the chunks. That is the same class of gap
  `fastembed` and `docling` are pinned exactly to close. Lower severity than the
  `fastembed` case for the same reason `docling` is kept out of the fingerprint:
  a change here produces visibly different *text*, not invisibly incomparable
  *vectors*. Parked: pinning a transitive dependency of a pinned package is
  worth doing deliberately, alongside the decision about whether the image
  should carry the vision stack at all.

- **The container pulls the whole NVIDIA CUDA stack onto arm64, where nothing
  can use it.** Observed building the image on Apple silicon: `torch` 427 MB,
  `nvidia_cudnn_cu13` 444 MB, `nvidia_cusparselt_cu13` 221 MB, plus
  `cuda_toolkit` — none of which an arm64 Linux container without an NVIDIA GPU
  will ever execute. It comes from the `docling==2.122.0` pin, which resolves to
  `docling-slim` with the `models-vlm-inline` extra. Pre-existing, not introduced
  by the quality gate — that change touched no dependency — but it is gigabytes
  of dead weight in an image whose whole promise is "one container, runs
  locally", and it is worth knowing before anyone measures the image and blames
  the model prefetch. Parked: fixing it means choosing narrower `docling-slim`
  extras or a CPU-only torch index, which changes what the vision rung can do
  and so belongs with a decision about whether the image should carry it at all.

- **Every ingest now prints RapidOCR's own log lines and a progress bar.**
  Verifying the recognition engine at the start of a run builds it, and the
  library logs at INFO and draws a `Loading weights:` bar straight to the
  terminal — including for a run that contains no page-bearing document at all.
  Observed on `jackryan ingest <casefile> <folder-of-markdown>`. Cosmetic, not a
  correctness problem, and the verification it comes from is deliberate. Parked
  because the fix is to decide a logging policy for third-party libraries at the
  CLI adapter, and this repository has none to slot into; muting loggers wholesale
  is how real warnings get lost, so it deserves its own change rather than a line
  smuggled into this one.

- **Nothing bounds how long an ingest may spend, and recognition makes that
  matter.** `ExpansionBudget` bounds nesting depth, descendant count and
  extracted bytes — not time. `docs/design.md` § 5 names "a per-document time
  budget" as part of the Finalize step; no such thing exists in
  `src/jackryan/`. Recognition raises the cost of a page from milliseconds to
  seconds, and the `extraction-quality-gate` change makes image files ingestable
  for the first time, so an archive of five hundred small photographs sits well
  inside the byte ceiling and costs roughly a quarter-hour of CPU. Not
  introduced by that change — the shipped extractor already ran recognition on
  every PDF by docling's default, and the change makes born-digital PDFs
  *cheaper* — but it widens the input surface that reaches it. Parked: a time or
  work budget is its own design (per document? per run? what happens to what was
  already stored when it expires?) and belongs with the retry ledger, not inside
  a change about extraction quality. docling's own `document_timeout` pipeline
  option is the likely lever.

- **Naming drift: the store still calls corpus identity `contract`.**
  `initialize(contract_fingerprint=...)`, the `store_meta` key, the refusal text
  and the `"contract"` field in `/health` and `jackryan status` all say
  *contract*, while the specs and docs say *corpus identity* and the value now
  includes a profile setting. An operator comparing a refusal against `/health`
  sees a key named `contract` holding something wider. Parked because renaming
  the `store_meta` key needs a migration or a documented legacy name, and the
  JSON field is a published surface — both bigger than the change that exposed
  it.

- **`scripts/verify_model_paths.py` — `check_real_embedder` bypasses the
  application's model-cache resolution.** It constructs `ModelEmbedder` directly
  with `cache_dir=<tempdir>/models`, instead of going through `build_embedder`,
  which honours `JACKRYAN_MODEL_CACHE`. The Dockerfile sets that variable and
  prefetches the weights into it. So in an image built with
  `--build-arg PREFETCH_MODELS=true` and run offline — the second run mode the
  script's own docstring recommends — this one check tries to download into an
  empty cache and records FAIL, directly beside the script's message that "a
  failure here is a real finding, not a flaky environment". The other two
  embedder loads go through `build_context` and are unaffected. It also means a
  full run fetches the model into three separate temp caches and deletes them.
  Parked: found by review of PR #11 on 2026-08-26; it is a defect in a
  verification script carried by that PR, not in the archive the PR is for, and
  it cannot produce a false PASS. Fix by building the embedder from a `Config`
  through `build_embedder`, and letting the cache outlive the temp workspace.

- **`check_real_embedder`'s own width comparison is dead code.** `ModelEmbedder`
  already raises `EmbeddingError` on a width mismatch, so the script's
  `if width != contract.embed_dimensions` branch is unreachable. This is
  cosmetic, not a hole: a mismatch is still caught and still fails the run with
  an accurate message, verified by forcing one. Noted so nobody "fixes" the
  guard by weakening the one in `ModelEmbedder`.

- **A LibreOffice conversion is a lossy round trip and nothing records that it
  happened, beyond `documents.extractor`.** A `.doc` is read as whatever
  LibreOffice's DOCX writer made of it, which is not necessarily what Word 97
  would have shown. `text_source` says `native` — truthfully, since no
  recognition ran — so an analyst weighing a converted quotation has only the
  `legacy-office+` prefix to tell them a converter stood between the file and
  the text. Parked: a fourth `text_source` value would be the honest fix, but
  that vocabulary is published in `extraction-quality-gate` and consumed by the
  MCP payloads, so widening it is its own change with its own spec delta.

- **Legacy template and show suffixes are not registered.** `.dot`, `.xlt`,
  `.pot` and `.pps` convert through exactly the same path and would each be one
  line in `LEGACY_SUFFIXES` and `_TARGET`. None appears in the dump this change
  was written against, so none could be demonstrated, and a suffix nobody can
  check is a claim nobody can check. Parked deliberately: add them when a dump
  contains one, not before.

- **`accepts()` is suffix-based, so a legacy file with no suffix at all is still
  invisible.** The container sniff runs inside `extract`, after the router has
  already selected on `Path.suffix`. A file named `Договор` with OLE2 bytes is
  dropped by the directory-walk pre-filter exactly as it was before this change.
  This is the same root cause as the parked apostrophe-filename finding above:
  content sniffing as a fallback when the suffix is unknown. Parked with it,
  because they want one fix, not two.

- **LibreOffice parses untrusted documents as root in the container.** The image
  now carries `libreoffice-writer libreoffice-calc libreoffice-impress` — a
  large, historically CVE-rich parser for OLE2, BIFF and RTF — and hands it files
  from an untrusted dump. Neither the `Dockerfile` nor `docker-compose.yml` sets
  `USER`, so it runs as root with the default seccomp profile, full network
  access, and `/data` — the whole corpus and the SQLite store — writable.
  `--headless` is a UI switch and suppresses dialogs; it restricts no file,
  network or process access, so it is not a mitigation. Parked, and stated
  plainly rather than fixed: this widens an existing exposure rather than opening
  a new one, because docling and the OCR stack already parse untrusted PDFs as
  root in the same image. Excluding the JRE and the desktop integration via
  `--no-install-recommends` is a real reduction. The fix is a non-root user for
  the image, which touches the volume permissions and the compose file and is its
  own change.

- **A converted file is read by the delegate with no ceiling of its own beyond a
  flat byte limit.** `MAX_CONVERTED_BYTES` refuses a conversion that writes more
  than 512 MB, which closes the unbounded case, but the number is the same as
  `MAX_FILE_BYTES` by intent rather than by measurement — nothing has established
  what expansion ratio real legacy files actually produce. Parked: the honest
  version measures the ratio across a corpus and sets the ceiling from it, which
  needs a corpus this project does not yet have.

- **The retrieval harness treats an absent baseline key as a mismatch for
  `corpus` only, and five other load-bearing keys are still skipped.**
  `conditions_match` in `scripts/evaluate_retrieval.py` compares eight keys and
  skips any the baseline does not record. `embed-input-is-corpus-coupled` closed
  that fail-open for `corpus`. Of the rest, `embedder` and `chunk_max_chars` are
  genuinely subsumed by corpus identity, and `window_max_chars` is genuinely
  readability-only — `measure()` scores `hit.chunk.text` and never reads the
  window — but `reranker`, `query_set`, `queries`, `documents` and `limit` all
  move the recorded figures and are all still skipped when absent. `reranker` is
  the sharpest: it is a query-time profile setting, so it is outside corpus
  identity by design, and this project's own measurement is that both available
  rerankers made retrieval worse and took Ukrainian to zero. Parked: making them
  required is one line, but it decides that every operator baseline recorded
  before the change becomes incomparable until re-recorded, which is a call
  about the harness's contract rather than a defect in this one.

- **An incomparable run exits 0, so a stricter comparability check can convert a
  detected regression into a green run.** `scripts/evaluate_retrieval.py` prints
  "Not compared against the baseline" and returns 0, while the adjacent
  no-metrics case returns 1 with an explicit comment that it must not pass by
  default because it is the one thing that can see retrieval regress. Same class
  of defect, opposite exit code. It matters now because
  `embed-input-is-corpus-coupled` made an absent `corpus` key route every such
  run down that branch: an operator holding a pre-change baseline had a regressed
  run return 1 and now gets 0 until they re-record. The repository's own baseline
  is annotated and pinned by a test, so the shipped gate cannot enter that state
  silently. Parked: whether "cannot be compared" should be an error or a report
  is the harness's contract, and changing it belongs with the decision, not
  inside a change that only added a key.
- **`CLAUDE.md` points at an `openspec/config.yaml` that does not exist.** Line
  50 reads "Config at `openspec/config.yaml`", and `openspec/` holds only
  `changes/` and `specs/`. The file is auto-loaded into every session in this
  repo, so the wrong path is read before anything else and a future session can
  spend time looking for a file that was never there. Nothing depends on it —
  the OpenSpec CLI finds its root without one — so the cost is confusion rather
  than breakage. Parked: found while writing `embed-input-is-corpus-coupled`,
  which had no business editing that line.

- **`test_a_timeout_kills_the_whole_converter_tree_not_just_the_launcher` is
  flaky, roughly one run in four.** Found while running the suite for the
  `mentions-and-facets` change and parked, not fixed: that change touches
  neither the test nor the legacy-office converter, and the flake reproduces on
  `origin/develop` at the same rate, so it is pre-existing rather than a
  regression. It fails as `FileNotFoundError: … /grandchild.pid` — the test
  reads the grandchild's pid file before the grandchild has written it, so the
  race is in the test's own setup rather than in the process-tree kill it is
  checking. The fix is to wait for the file with a bounded poll instead of
  assuming it is there. It matters because the assertion it guards is a real
  one: a converter timeout must kill the whole tree, and a test that fails at
  random teaches the reader to re-run rather than to look.

## Fixed

- **~~The store has no migration path.~~** Fixed by
  `corpus-identity-and-schema-migration` on 2026-08-28. The baseline is frozen
  at schema version 4 and an ordered ladder of additive steps carries a store
  forward, with `text_source` as the first rung so a brand-new store climbs the
  same step an old one does — a runner exercised only by a fixture rots between
  the day it is written and the day it is needed. A backup is taken through
  SQLite's own backup API first, and three mechanical tests enforce the
  additive rule, the frozen baseline and the FTS trigger's column list.

- **~~Corpus identity is an unescaped `|`-joined string.~~** Fixed by the same
  change: each component escapes backslash, pipe and control characters, and
  deliberately not `=`, since `embed_library` contains `==`. Every reachable
  identity is byte-identical afterwards, so no store was invalidated. The parked
  note overstated the reach — no collision is constructible through a config
  file, because only `embed_model` is free text; what was reachable was a
  deceptive identity naming an embedder the instance was not running.

- **~~The embedder's width is never checked against the contract's.~~** Compared
  now at the composition root before the store is constructed. Read the guard
  narrowly: `build_embedder` builds both implementations from the contract, so
  configuration cannot make them disagree. It covers the seam where an embedder
  is supplied directly, and becomes the guard it reads like the day one learns
  its width from the model it loaded.

- **~~`text_source` reaches the agent but not the human.~~** Now on the CLI, both
  REST document endpoints and `case_list_documents`, under the same key and
  vocabulary the agent sees, with an unrecognised value collapsing to
  `unrecorded` on all four alike.

- **~~The contract fingerprint does not cover the embedding library version.~~**
  Fixed by the `contract-covers-embedding-library` change on 2026-08-26: the
  contract declares `embed_library`, the fingerprint covers it, and a declared
  version that is not the installed one is fatal at both configuration load and
  embedder construction. See `docs/handover.md` for the decisions.

- **~~`scripts/verify_model_paths.py` — the end-to-end check is weaker than its
  comment claims.~~** Fixed in #10 on 2026-08-26, and resolved the other way
  round from what the note proposed: rather than strengthening the check to a
  paraphrase with no shared content word, the comment was corrected to say what
  the check actually establishes — that the vector leg ran and returned, with
  retrieval quality explicitly out of scope. The defect was that the comment
  lied, and it no longer does.

- **~~The fingerprint did not record which embedder built the vectors.~~** Fixed
  by the `corpus-identity-covers-the-embedder` change on 2026-08-26. Of the two
  candidate fixes recorded here, the second was taken: corpus identity is
  composed at the composition root from the contract plus the embedder actually
  constructed, rather than adding an `embedder` field to the contract. An
  `embedder` contract field would have put an infrastructure selection in the
  corpus-coupled layer *and* duplicated a setting that already exists in the
  profile — two copies that can disagree, which is the shape of the bug being
  closed. The noted downside of the chosen fix was dealt with rather than
  accepted: `/health` and `jackryan status` now report the enforced identity, so
  the value an operator sees is the value that refused them.
