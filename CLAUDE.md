# CLAUDE.md

Guidance for Claude Code when working in **Jack Ryan**.

Human-facing design and the staged plan: `docs/design.md`. Read it before
proposing anything — it carries the nine design principles, the ten locked
decisions, and which milestone each capability belongs to.

**`docs/handover.md` records what is verified and what is not.** Read it before
trusting that anything here has been run: every test uses a stand-in embedder and
none opens a PDF, so the model-dependent paths are covered by two scripts and
nothing else — `scripts/verify_model_paths.py`, which passed 6/6 on 2026-08-26,
and `scripts/evaluate_retrieval.py`, which measures retrieval quality against a
recorded baseline. The handover says exactly what each does and does not settle.
What is known but deliberately unfixed lives in `docs/implementation-notes.md`.

## What this is

A self-hosted investigation workbench. An analyst drops document dumps into
casefiles and works them beside an agentic AI assistant that reaches the corpus
over MCP. Runs local-first: one container, one SQLite file.

**Delivery is prototype-first.** The prototype is M0–M2 and proves one loop:
ingest documents, then have the assistant work the corpus over MCP and answer
with resolvable citations. Depth (OCR, hard formats, retrieval quality,
summaries, mentions) is M3. Analysis (attributed writes, the operating picture,
the roster split, reports) is M4. Everything else is beyond.

Current state: **M3, third slice.** What is archived and what is published is in
`openspec/`; the staged plan is in `docs/design.md`.

Recognition was already running before slice 2 and had never been configured: a
Ukrainian scan ingested as nine characters of punctuation, which passed the
empty-document guard. It is now deliberate — engine and language named in the
profile, `auto` refused, a three-rung escalation ladder, and `text_source`
recorded per document and shown to the agent.

**Retrieval quality is now measured.** `scripts/evaluate_retrieval.py` reports
recall and reciprocal rank over a fixed trilingual query set and fails against a
tracked baseline in `docs/retrieval-baseline.json`. A result's text is now a
window around the matched passage, and a rerank stage exists — but it ships
disabled, because both rerankers the embedding library offers made retrieval
measurably worse on that set and took Ukrainian to zero. The figures and the
trace are in `docs/handover.md`; read them before naming a reranker.

## Rules

### OpenSpec governs every substantive change

Explore → propose → apply → sync/archive. Config at `openspec/config.yaml`,
active proposals in `openspec/changes/<slug>/`, published specs in
`openspec/specs/<capability>/spec.md`. Do not plan substantive code changes
without a corresponding OpenSpec change.

A proposal that pulls deferred work forward must say why the prototype cannot
be proven without it.

### Public-repo safety

This repository is **public**. Every tracked file and commit message is
world-readable and permanent.

- **No secrets in tracked files, ever.** Real values live only in the
  gitignored `.env` and `config.yaml`. The tracked templates carry placeholders
  only.
- **No infrastructure fingerprints.** No real hostnames, private IPs, tailnet
  names, or personal paths (`/Users/<name>`, `/home/<name>`) — in code, docs,
  examples, commit messages, or sample output. Scrub before committing.
- **No real corpus contents.** No actual document titles, filenames, document
  ids, or case material. Test fixtures use synthetic data only.
- **Before committing, grep for leaks:** `sk-`, `hf_`, `AKIA`, `ghp_`,
  `-----BEGIN`, `.ts.net`, `/Users/`, `/home/`.

### Business logic belongs in the service layer

`src/jackryan/services/` owns every rule. REST (`server.py`), CLI (`cli.py`),
and later MCP are **thin adapters** that translate and nothing more. A rule
enforced in an adapter is a second, divergent definition of the domain — and
the MCP surface has no request-validation layer of its own to fall back on.

Adapters translate typed errors from `errors.py`; the service layer never
raises adapter-specific exceptions.

Three conventions a directory listing does not show: `app.py` is the
composition root and the only place wiring happens, `storage/port.py`
(`StorePort`) is the one deliberate abstraction, and `config.py` is where the
corpus `contract` divides from the infra `profiles` — the distinction
everything below about corpus identity turns on.

### Evidence is immutable

Originals and extracted text are read-only inputs. Derived work — tags, notes,
judgements, the operating picture, reports — lives beside the evidence and
never overwrites it. This holds for code as much as for the assistant.

### Corpus identity is guarded, not assumed

The `contract:` block (chunk size, overlap, embedder family, dimensions, and the
embedding library version) is corpus-coupled. Changing any value changes the
fingerprint, and the store refuses to open a corpus built under a different one.
Never weaken that guard to make a test pass — it is the only thing standing
between a config typo and a silently corrupted corpus.

**Corpus identity is the contract plus `profiles.<name>.embedder`, not the
contract alone.** That one profile field is the exception to profiles being safe
to change: it selects which implementation produces the vectors. It is composed
into the recorded identity at the composition root rather than copied into the
contract, because two copies of one setting can disagree. Treating identity as a
contract-only property is what let a deterministic corpus open under a
real-model configuration — real vectors compared against hash vectors of the
same width, which nothing downstream can detect.

## Pitfalls

- **Schema changes go through the `_STEPS` ladder, never `_SCHEMA`** — the
  rules, and why each matters, are in `src/jackryan/storage/CLAUDE.md`.
- **`Context.store` is the port, and no adapter may touch it.** `storage-seam`
  says no adapter reaches a store directly; the agent surface did, at
  `casefile_statistics`, because `CasefileService` had no `statistics` and
  nothing forced one to exist — `case_casefile_overview` has no REST or CLI
  counterpart. Declaring the field as `StorePort` states the rule but enforces
  nothing, since no type checker runs here (and several tests reach
  `context.store._db`, which one would flag). What enforces it is
  `test_no_adapter_reaches_the_store`, which **parses** every module under
  `interfaces/` and reports any `<expr>.store`. Matching the string
  `context.store` instead would be defeated by binding it to a name first, and
  would trip on a comment. If a port method needs a caller, write the service
  method — that gap is how the reach happened.
- **A port method returning a bare `dict` is returning a row.** The port speaks
  in domain objects, and `casefile_statistics` was the one exception until it
  became `CasefileStatistics`. The names are the payload's, deliberately not the
  SQL's: the query aliases those columns `ingested` and `expanded`, and a field
  named after the alias yields a payload with silently different keys that every
  value-by-value assertion still passes. `tests/test_mcp_surface.py` asserts the
  overview's key set exactly, for that reason.
- **Corpus identity escapes `\`, `|` and control characters — never `=`.**
  `embed_library` legitimately contains `==`. Escaping `=` would change the
  default identity and refuse every existing store.
- **A tie in the fused ranking is broken by the corpus, never by an
  identifier.** Reciprocal rank fusion ties routinely, and chunk ids are minted
  afresh on every reingest while document ids differ between two stores built
  from the same documents. Ordering by either makes an unchanged corpus rank
  differently between runs — which it did, by 0.058 recall@1, until ties were
  broken by the passage's ordinal and text. An identifier decides only between
  two passages identical in both, where the order does not matter. Nothing else
  can be reproduced if this is not.
- **A search filter goes inside the retrievers' SQL, never over their results.**
  Both legs are asked for `depth = limit * 5` candidates, so filtering what they
  return discards every matching passage that ranked below that depth
  unfiltered. The caller is then handed nothing while the store holds exactly
  what they asked for — and an empty result reads as "this casefile does not
  mention that account", which is the most damaging wrong answer this tool can
  give. The casefile constraint is inside both legs for the same reason and its
  comment makes the same argument; put any new predicate beside it. Filtering
  there also keeps it before fusion, so reranking still only reorders what
  fusion produced, and keeps it out of the scoring path entirely — a filter that
  touched the score would be a third retriever wearing a filter's name.
- **An unknown facet kind is an error naming the kinds, never an empty result.**
  `--mention passport:123` must refuse. An empty list tells the analyst the
  casefile contains no such identifier, which is a different claim and a false
  one. Same reasoning as refusing text that is punctuation alone rather than
  treating it as empty.
- **A mention extractor earns its place by precision, not coverage.** The IBAN
  extractor validates mod-97 rather than matching a shape; the
  registration-number extractor requires a `ЄДРПОУ`/`ИНН`/`ІПН` keyword before
  the digits. A bare eight-digit regex returns every date and page number in the
  corpus, and a facet dominated by false matches costs an analyst more than an
  absent one — they scroll past it once and never open it again. If an extractor
  cannot meet that bar, drop it rather than loosen it. Digits are `[0-9]`, never
  `\d`, which in Python also matches Arabic-Indic digits and would put two
  incomparable spellings of one digit into a normalised form that exists to be
  compared.
- **Retrieval settings are profile and leave no residue.** `reranker_model`,
  `rerank_depth` and `window_max_chars` are read at query time and write nothing
  — no vector, no chunk, no stored text — so no store is ever refused for them.
  This is a stronger claim than the one extraction settings get, and it is why
  they are not in corpus identity.
- **A setting that changes what is embedded without changing the stored text
  enters corpus identity — by composition, not necessarily in the contract.**
  Per-chunk contextual summaries are the shipped case: the fold puts the summary
  in front of the chunk before embedding, so the vectors mean something different
  while staying the declared width, and a corpus holding both kinds is
  undetectable. The qualifier is what separates this from the extraction bullet
  below — extraction settings change the embedder's input too, but they do it by
  changing the extracted text, which leaves the difference legible and
  per-document `text_source` records which rung produced it. A fold leaves the
  stored chunk identical and the vector different.
  **`chunk_summaries` and `summary_model` live in the profile**, and
  `corpus_fingerprint` appends a `|summariser=` component when and only when the
  fold is on. That is composition, exactly as `embedder` is composed, and the
  reason is the same one the spec gives for not duplicating the embedder into the
  contract: the summariser's identity is its model plus a hash of the shipped
  prompt, truncation limit and sampling parameters, so an operator could not write
  it down and a declared copy could disagree with the code. Because the component
  is omitted when empty, an instance with the fold off produces the identity
  string a corpus recorded before summaries existed — which is what let the real
  435 MB corpus survive this change.
  `tests/test_embedding.py` asserts both branches: with the fold off the embedder
  gets the chunk's own text, heading path included but not folded in; with it on
  every embedded text is the stored summary joined to the stored text. A fold
  appearing in the first branch is a defect, and the signal is that the fold must
  enter corpus identity — never to update the test.
- **The recipe is hashed, so nobody has to remember to bump a version.** Editing
  `SUMMARY_PROMPT`, `SUMMARY_DOCUMENT_CHARS`, `SUMMARY_MAX_TOKENS`,
  `SUMMARY_TEMPERATURE` or `SUMMARY_ENABLE_THINKING` moves `RECIPE_FINGERPRINT`
  and therefore corpus identity. `DOCUMENT_PROMPT` is deliberately outside the
  recipe because the per-document summary is stored and never embedded; if a
  later change embeds it anywhere, that prompt moves inside the recipe in the
  same change.
- **A summariser failure fails the document; it never degrades.** This is
  deliberately the opposite of the reranker's transient policy below. A reranker
  only reorders, so serving the fused order is honest. A document embedded bare
  inside a folded corpus is silently incomparable with every other document and
  nothing downstream can detect it, so `SummaryError` fails that one document and
  stores nothing for it. A short return from the summariser is a failure too,
  never a pad. `SummariserUnavailable` is a `ConfigError` and stays fatal for the
  whole run, and the split holds by type — `except ConfigError: raise` before the
  per-document handler — so reordering the clauses cannot convert one into the
  other.
- **Summaries are the first thing that sends corpus text off the instance.**
  `llm_url` was a declared setting reading nothing until M3. It is opt-in
  (`summary_model` empty by default) and the read stack still runs with zero
  configured endpoints, but a casefile is evidence and this is a change in the
  tool's posture rather than a performance knob. A model's summary is untrusted
  text: it is fenced, marked `derived_by`, and deliberately absent from
  `chunks_fts` so it cannot answer a keyword search as though the document
  contained it.
- **A reranker has two failure modes and they are deliberately different.** One
  that is named but cannot be built stops the search, naming the setting: an
  instance quietly serving the fused order has hidden a misconfiguration. One
  that fails while scoring a response leaves the fused order and reports
  `rerank-unavailable`, because refusing to answer would make retrieval quality
  a condition of retrieval.
- **A rerank score is not a confidence.** It is an uncalibrated logit,
  comparable only within one response — never between queries or between models.
  It never replaces the fusion score, which stays what fusion computed.
- **The reranker is given the matched passage, never the widened window.** The
  library truncates the query-and-passage pair at the model's own limit with no
  override, so a window would be cut inside it and the score would describe a
  fragment nobody chose.
- **A window is a slice of `extracted_text`, never joined chunk texts.** Chunks
  overlap by configuration, so joining them repeats the overlap, and a chunk's
  stored text is stripped while its offsets are not. The slice is what a person
  reading those offsets sees, which is what makes a citation checkable by hand.
- **Widening what is read never widens what is cited.** The matched passage
  stays the unit that identifiers address and `case_cite` quotes. A payload that
  returns more than it declares cannot be followed back, which is why provenance
  names both spans.
- **Test fixtures with single-passage documents cannot exercise a window.** Three
  window tests passed while proving nothing for exactly that reason. Use the
  `sectioned_corpus` fixture where widening matters, and assert that something
  actually widened.
- **Never remove the `cli` service from `docker-compose.yml`.** It exists with
  `replicas: 0` on purpose, for `docker compose run --rm cli ...`. A refactor
  that "cleans it up" breaks the CLI workflow.
- **Locks are `threading`, not `asyncio`.** The server is async but ingestion
  runs in a thread pool from M1; an asyncio lock would not hold across worker
  threads.
- **CI runs three gates and no more**: pytest, gitleaks, and a Docker build.
  There is no linter or formatter gate — a green PR means those three passed.
- **The CLI calls services directly, not HTTP.** That is deliberate, so it
  works against a stopped instance.
- **Never let the deterministic embedder become a fallback.** It produces
  vectors with no meaning. It is selected only by `embedder: deterministic`, and
  a real embedder that fails to load must stop ingestion rather than degrade to
  it — silently storing meaningless vectors is unrecoverable without a reingest.
- **Fencing is a convention, not a sandbox.** Corpus text returned to an agent
  is nonce-fenced and marked untrusted, and a model that ignores it is not
  prevented from anything. The controls that do not depend on the model are the
  read-only profile and the service layer's authority. Never describe the fence
  as enforcement.
- **Tool names are a contract.** Saved prompts and the shipped analyst pack name
  the `case_*` tools; renaming one breaks them.
- **A decorator on a tool must carry `functools.wraps`, must be `async def`, and
  must go *below* `@server.tool(...)`.** `returns_error_payload` translates every
  tool's typed failures in one place, which `service-adapter-boundary` requires —
  but the SDK reads a tool two ways and only one of them unwraps.
  `inspect.signature(fn, eval_str=True)` follows `__wrapped__`, so the advertised
  input schema survives `wraps`; without it a tool advertises the wrapper's own
  two parameters, `args` and `kwargs`, both required, and every call fails for
  missing arguments. (The degraded schema is *not* empty, and the structured
  output schema is unaffected either way — the wrapper has its own return
  annotation. Both were measured; both are the opposite of the obvious guess.)
  `inspect.iscoroutinefunction` does *not* follow `__wrapped__`, so a synchronous
  wrapper is registered as a plain function, run in a worker thread, and hands
  back an un-awaited coroutine.
  The ordering is the quiet one: applied *above* `@server.tool`, the SDK
  registers the undecorated function, so the translation still reads correctly
  and never runs. On a tool nothing calls, that leaves the whole suite green —
  which is why `test_every_tool_inherits_the_one_translation` inspects what was
  registered rather than trusting the call sites, and why the advertised
  parameters and `required` lists are asserted separately.
- **The tool translation covers the whole tool, deliberately.** A tool builds its
  payload after the calls it awaited and may reach the service layer again while
  doing so — `case_get_passage` asks for its window there. `mcp-tool-surface`
  says a tool SHALL NOT raise, so the translation wraps the function rather than
  its opening calls. Keep the catch at `JackRyanError`: an agent *branches* on a
  returned value, so widening to `Exception` would dress a crash as an ordinary
  answer and the agent would carry on as though it had one.
- **Docling PDF extraction needs models on first use.** Markdown, HTML, DOCX and
  PPTX parse offline. Build the image with `--build-arg PREFETCH_MODELS=true`
  for a container that is offline from its first run.
- **Never set `ocr_engine: auto`, and never re-admit it.** docling's `auto`
  picks the engine by host operating system, forwards only `mode` to what it
  picked — dropping the configured language — and, finding no engine, logs a
  warning and yields the pages unchanged. It is refused at configuration load.
  Extracted text becomes the corpus, so an engine chosen by the host makes the
  corpus a property of the machine that ingested it.
- **A recognition engine that cannot be built stops the ingest.** It never falls
  back to another engine and never falls back to reading pages without
  recognition: a scan read without recognition is an empty document, which looks
  ingested. The check runs once at the start of an ingest run — not at process
  start, which would charge every `jackryan status` seconds and a model download.
- **Constructing a `DocumentConverter` verifies nothing.** It builds its
  pipelines lazily, so one made with a nonsense recognition language returns
  quite happily and fails on the first scan. `check_engine` calls
  `initialize_pipeline`, which builds the model. Do not "simplify" it back.
- **`text_source` is a disclosure, not a guarantee.** It says which rung produced
  a document's text so an analyst can weigh an OCR'd quotation differently. It
  does not make that text correct — recognition renders a word as a plausible
  different word, and nothing downstream detects it.
- **Extraction settings are profile, not contract, and that is a deliberate
  trade.** Changing the recognition engine or language does not invalidate a
  corpus, so nothing refuses a corpus built under different settings. The
  per-document `text_source` is what makes a later re-extraction targetable, and
  it is the whole compensation for that gap.
- **A container extractor never routes what it holds.** It yields entries and
  stops; the pipeline routes them. That is what makes a format supported inside
  an archive exactly when it is supported outside one.
- **Container entries are yielded one at a time, never returned together.** All
  at once puts a whole archive in memory before the expansion budget can refuse
  any of it — which makes the byte ceiling unreachable in the case it exists for.
- **`containment_path` is display; `identity_path` is identity.** A folder walk
  records a path but keeps content-only identity, so two copies in one folder
  are one document. An expansion's path *is* part of its identity, so the same
  attachment on two messages is two documents — which message carried it is
  itself evidence.
- **A descendant never outlives its container.** `documents.parent_id` carries
  `ON DELETE CASCADE`, verified to recurse through nesting and to fire the chunk
  trigger at every level. Never replace it with code that has to remember.
- **A legacy Office format is converted, then delegated — never read directly.**
  `.doc` and `.rtf` become `.docx`, `.xls` becomes `.xlsx`, `.ppt` becomes
  `.pptx`, and the file is handed to the extractor that already owns that
  suffix. docling *would* read all three legacy formats if they were added to
  `MARKUP_SUFFIXES`, and that is the trap: its spreadsheet backend renders a
  workbook differently from `SpreadsheetExtractor`, so the corpus would hold two
  renderings of the same kind of document. That failure is invisible — it shows
  up as retrieval quality, never as an error.
- **The media type stored for a converted document is the legacy one.** A `.doc`
  is `application/msword`, not the DOCX type it was read as. The conversion is
  how the text was obtained; it is not what the evidence is. Which path ran is
  recoverable from `documents.extractor`, which reads `legacy-office+<delegate>`
  or `legacy-office-passthrough+<delegate>` and has no third value.
- **A passthrough file is copied under its true suffix before delegating.** A
  delegate keys its media type off `path.suffix`, so handing `SpreadsheetExtractor`
  an OOXML file still named `.xls` raises `KeyError` — which is not an
  `ExtractionError`, so it would abort the whole run instead of failing one
  document. Never "simplify" the copy away.
- **Content routing is a fallback, and it lives at `extractor_for` — never at
  `extract` alone.** A file the registry cannot name by suffix is identified by
  its bytes and routed to that format's extractor. The seam matters more than
  the feature: `services/ingestion.py:217` skips any file whose `extractor_for`
  is `None` *before* `extract` is called, so a fallback taught only to `extract`
  is inert on every folder walk — which is the only case it exists for. That is
  also why there is one resolution behind both, rather than a second predicate
  answering "can this be read": two answers to that question can disagree, and
  the disagreeing one wins at the pre-filter. `tests/test_content_routing.py`
  pins it with a mutation that restores the suffix-only pre-filter.
- **"Decodes as text" is not a signature, and admitting one would be the whole
  mistake.** Only a positive signature routes: OOXML by the part it carries,
  OLE2 by its stream names, and the unambiguous magic numbers. A text fallback
  would sweep the `.bat`, `.ics` and `.p7s` files of a real dump into the corpus
  as documents, which is the same failure as storing text that carries no
  letters or digits — it looks ingested and is worth less than a refusal. Every
  suffix the sniffer can return must be one a shipped extractor declares, and a
  test derives that from the live registry rather than a literal list.
- **A content-routed file is copied under the resolved suffix before the
  delegate sees it** — the same reason the legacy passthrough copies, one bullet
  up, and the same `KeyError`-ends-the-run consequence if it is simplified away.
  Its lineage is `content-routed+<delegate>`, which nests:
  `content-routed+legacy-office+docling` is a real and correct value. The
  filename stays what is on disk, quotes included, and the media type stays the
  delegate's — reading a file as something other than its name is a disclosure,
  not a correction of the evidence.
- **LibreOffice is reported, never required at startup.** Unlike the recognition
  engine, an absent converter fails only the documents that need it, so
  `jackryan status` and `GET /health` both carry `legacy_office`. Both read one
  `converter_status()`: two agreeing definitions is one definition too many.

## Commands

```bash
# Setup
uv venv --python 3.12 && uv pip install -e ".[dev]"

# Tests — the same gate CI runs
pytest -q

# Retrieval quality against the tracked baseline (needs model weights)
python scripts/evaluate_retrieval.py

# Run the API
uvicorn jackryan.server:create_app --factory --reload --port 8500

# CLI
jackryan status
jackryan casefile create "Some Investigation" --description "..."
jackryan casefile list
jackryan casefile show <id|short-id|slug>
jackryan ingest <casefile> <file-or-folder>
jackryan search <casefile> "a question"
jackryan document list <casefile> [--expanded]
jackryan serve-mcp                      # the agent surface over stdio

# Docker
docker compose up -d --build
docker compose run --rm cli casefile list
```
