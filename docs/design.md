# Jack Ryan — Design Document & Implementation Plan

**Status:** v0.1 draft, for plan/spec review. High-level by intent; every section is an anchor for review, not a finished spec. Each milestone below becomes one or more OpenSpec changes.

---

## 1. Mission

Jack Ryan is a self-hosted **investigation workbench**. A human analyst drops heterogeneous document dumps into casefiles and works them — search, facet, tag, annotate, pivot, report — side by side with an **agentic AI assistant** that has first-class access to everything ingested through an MCP surface. The assistant is an analyst, not a search box: it reads, pivots, tags, maintains a running picture of the investigation, and drafts citation-backed briefs, with every action attributed and reviewable.

Named for the desk analyst who wins by actually reading the documents. The tool's job is to turn one analyst plus an AI into the person who read all of them.

## 2. Design principles

These nine tenets govern every decision below. Where a later section seems to trade something away, it is trading in favor of one of these.

1. **Local-first, offline-capable.** Corpus content leaves the machine only toward endpoints the operator explicitly configures; nothing is outbound by default. Core search runs with zero endpoints configured, so an air-gapped instance is fully usable.
2. **Content-first understanding.** What a document *says* drives its classification, metadata, and mentions — not filename or path heuristics, which are fallback only.
3. **Evidence is immutable.** Originals and extracted text are read-only inputs. Every derived artifact — tags, notes, judgements, the operating picture, reports — lives beside the evidence and never overwrites it.
4. **Every claim is traceable.** A factual assertion the assistant produces resolves to a specific document / chunk / span through the citation machinery, and that traceability is enforced by the tool surface rather than by convention.
5. **Retrieved content is data, never instructions.** Document text, tool output, and fetched material are evidence to analyse; an instruction found inside them is reported to the human, not obeyed. The boundary is injection-aware.
6. **Model-agnostic.** The assistant connects over MCP, an open standard, so any agentic-capable model or harness can drive it. Nothing in the tool contract, the analyst roles, or the skills assumes a specific vendor; roles and skills ship as harness-neutral markdown.
7. **Collaboration-ready from the schema.** Every write records its actor (which human, or which agent identity). Casefiles are first-class compartments. A future multi-user server mode is an authorization feature layered on top, not a data-model migration.
8. **Few moving parts, clean seams.** A single embedded store and a small dependency set keep a solo-operated instance simple; deliberate seams (the format router, the storage port, the mention/NER engine) allow growth and swaps without reworking the core.
9. **Disciplined analysis.** The assistant reasons with named structured-analytic techniques and closes every working pass with a calibrated judgement *and* a next move. Missing information is a gap to name and hand back, never a silent stopping point.

## 3. Decisions locked (from scoping review)

1. **Entity model:** FollowTheMoney-compatible, phased. v1 ships documents + auto-extracted **mentions**; curated entities, relationships, and cross-referencing come post-v1. The schema reserves the seats from day one.
2. **Deployment:** local-first single-analyst v1, **collaboration-ready schema** (per principle 7). Server mode later adds auth/ACLs, not a migration.
3. **Stack:** Python, **SQLite + FTS5 + sqlite-vec** as a single store — one file, one backup, transactional across text and vectors. Docker Compose. A **storage seam** (`StorePort`) lets a heavier engine replace it if a corpus or team outgrows it.
4. **AI access:** MCP server, **read + attributed writes**, **model-agnostic** (principle 6). An embedded in-UI assistant is a possible later phase consuming the same surface.
5. **v1 formats:** PDF, Office (DOCX/PPTX), text/Markdown/HTML, **email archives** (EML/MBOX/MSG/PST), **spreadsheets** (XLSX/CSV), **archives & folder trees** (ZIP etc.) — all through a modular format router.
6. **Languages:** English, Ukrainian, Russian across extraction, OCR, NER, and search in v1. Multilingual embeddings make retrieval nearly free; OCR/NER need explicit language support.
7. **Reporting:** citation-backed briefs as first-class casefile artifacts, stored as data and exportable.
8. **Home:** dedicated repo `sapran/jack-ryan`, OpenSpec-governed.
9. **Analyst layer:** a **native roster** of analyst roles + a curated skill set, shipped as harness-neutral markdown in this repo — no dependency on any external agent pack.
10. **Operating picture:** a first-class, agent-maintained casefile object (§4) — the assistant's cross-session memory and the spine of its reports.

**Stated assumptions (correct me in review):**
- Scale target: casefiles of 10³–10⁵ documents on a single machine; v1 does not chase millions (the storage seam covers growth beyond that).
- LLM/embedding infra: OpenAI-compatible endpoints, round-robin, local-model capable; corpus content goes only to explicitly configured endpoints.
- The assistant connects via MCP from whatever agentic harness the analyst uses.

**Delivery strategy: prototype-first.** The build is staged behind a lean prototype that proves the core loop (§10). Everything in §4–§6 describes the target system; nothing below is cancelled, only sequenced. Anything that does not serve the fastest path to a working demo is deferred — the deferral list and the milestone each item returns in are in §10.

## 4. Domain model (high level)

- **Casefile** — the unit of scoping, provenance, and (later) access control. Every document, tag, note, report, and search belongs to exactly one casefile.
- **Document** — immutable original (content-hash addressed) + extracted text + metadata + detected language(s). **Hierarchy is first-class:** archive → members, mailbox → messages → attachments, folder trees preserved as paths. A document's UUID survives reingest, so tags and bookmarks stay valid.
- **Chunk** — retrieval unit carrying heading-path context and a contextual summary.
- **Mention** — machine-extracted reference in a document: person/org/location names (NER — classical models with uk+ru+en coverage, plus regex pattern-extractors for emails/phones/IBANs/id-shaped strings; an optional LLM mention pass is a config switch, behind a plugin seam). Faceted and pivotable. Mentions are *hypotheses*; they carry extractor + confidence provenance, and are FtM-typed so they can later be promoted to entities.
- **Entity & Judgment** *(post-v1)* — a curated FtM entity; a Judgment is a recorded human (or human-confirmed) decision linking mentions/entities (same / not-same).
- **Tag / Note / Flag** — the annotation and social layer. Each records its `actor` (which human or agent) and `origin` (manual / assistant / pipeline).
- **Report** — a first-class artifact stored as **DB rows** (narrative + structured **Citations**, each resolving to document/chunk/span), not files: queryable ("which reports cite this document?"), citation-integrity enforceable, lifecycle-tracked. Draft → reviewed; author-attributed; Markdown/DOCX/PDF are renderings on demand. Draws on the Operating Picture as its spine.
- **Operating Picture** — a per-casefile **living state** the assistant maintains. One polymorphic **picture-entry** table with a `type` of **judgement / gap / hypothesis / fact**, each carrying confidence, provenance (the hypothesis that raised it), a `status` of `provisional | confirmed`, and — for perishable facts — a re-verify horizon. Everything timestamped, delta-tracked ("what changed since last read and what it implies"), and attributed. It is the assistant's cross-session memory and reconciles against new material on each working pass. **Append-only and never auto-mutated:** a perishable fact past its horizon is flagged *stale — re-verify* in the picture and in any report that leans on it, never silently dropped; a human or agent decides to re-confirm or retire it. Agent-authored entries are `provisional` until a human confirms.
- **Actor** — a human user or a named agent identity. Present in v1 with one human; makes "show me everything the agent did this session" a query, and makes server mode an authorization feature rather than a data-model change.

## 5. Architecture

**One service, thin adapters.** A Python/FastAPI core owns all business logic in a service layer. **v1 adapters are REST, MCP (mounted in-process), and CLI.** A web UI is a post-v1 adapter that talks HTTP only; the service boundary is built so it, and later a multi-user server mode, bolt on without reworking the core. Bounds and containment checks live in the service layer so every adapter inherits them.

**Store.** SQLite with FTS5 (keyword) and sqlite-vec (vectors) — one file, one backup, transactional writes across text and vectors, so text and its embeddings can never drift out of sync. The `StorePort` seam is the one deliberate abstraction, reserved for a later heavier-engine swap. An embedding-contract fingerprint is checked at boot; a reconciliation tool ("doctor") repairs store ↔ originals-on-disk drift.

**Ingestion.** Per-casefile inbox (watched directory + upload API) → threaded workers → a four-step pipeline:
1. *Extract* — the **format router**: a plugin registry of Extractors, each declaring `sniff()` (magic/MIME/extension) and `extract()` returning a normalized **DocumentGraph** (text blocks + structure + child documents + native metadata). Container extractors (ZIP, mailboxes, PST) recurse with depth/size/zip-bomb guards, emitting children through the same pipeline with a `parent_id`. **Docling is the default extraction engine** (in-process, with optional out-of-process offload for throughput) — extraction quality is the product, not an add-on. A quality gate escalates: standard pipeline → conventional OCR configured for eng+ukr+rus (EasyOCR default; engine pluggable, because Cyrillic support needs explicit language configuration) → **VLM pipeline** where it wins (complex layouts, Latin-script scans). A lightweight offline extractor survives only as an emergency fallback, never the normal path. *(The prototype ships born-digital baseline formats only; OCR, the VLM path, container/mailbox recursion, and the UK/RU extraction spike are deferred to M3 — see §10.)*
2. *Enrich* — per-chunk contextual summaries (LLM; the dominant ingest cost, since a large dump is millions of LLM calls, so this is a config switch, **off in the prototype** for fast/cheap ingest and enabled later for retrieval quality); a per-document summary cascade; NER + pattern extraction → mentions; a metadata cascade (LLM-first, deterministic fallbacks, per-field provenance). *(The whole enrich layer beyond chunk+embed — summaries, mentions/NER, metadata — is deferred to M3; the prototype extracts, chunks, and embeds.)*
3. *Persist* — one lock hold; dedup by content hash; UUID reuse on reingest.
4. *Finalize* — originals archived content-addressed within the casefile; a failure/retry ledger with backoff; crash recovery on boot; a per-document time budget.

**Search.** Casefile-scoped always. Hybrid keyword + vector retrieval fused by reciprocal-rank fusion → cross-encoder rerank (degrades to unranked, never blocks) → expansion of a matched chunk to a coherent section-sized window for the agent to read. Facets: doc type, language, date, path/container, mention, tag, actor. The read stack runs offline with zero configured endpoints. *(The prototype ships fusion only; rerank and section-window expansion are deferred to M3, and mention/tag/actor facets arrive with the features that populate them.)*

**MCP surface.** A uniform **`case_*`** tool prefix (the CLI/binary is `jackryan`); 8-char id prefixes; a return shape that separates a formatted index from the result bodies and carries chaining ids for follow-up calls; bounded reads with explicit truncation; typed error payloads; a central table stamping each tool's read/write/destructive mode. **Profiles fail to the narrowest surface:** `readonly` (search/read/cite only), `analyst` (default: reads + attributed writes per §6, including operating-picture entries), `admin` (ingest/delete/doctor — for the human via CLI/REST, not normally advertised to the agent). All corpus-derived text is fenced as untrusted, with provenance blocks (principle 5).

## 6. The assistant as analyst

The assistant is not one generic agent; it is a small **analyst roster** working the Jack Ryan MCP surface, shipped as a native pack of **harness-neutral role definitions + skills** in this repo, so any agentic-capable model can be initialized with the roles. It improves independently of the machine and couples Jack Ryan to no vendor.

**Skill authorship policy.** The skill set is a *curated, provided* asset, not a growing one: an initial reasonable set written by the maintainers and JR developers (AI-assisted drafting is fine; agents do not autonomously author or extend skills). Adding a skill is structurally easy, but continuously growing the library is not the project's point — Jack Ryan is a workbench for an analyst who uses AI and can initialize agents with the provided roles. The one non-negotiable is the evidence chain (principle 4): every factual claim traces to a document, enforced by the tool surface.

**Roster.** An **orchestrator** that holds the casefile's Operating Picture and *does the fusion itself* — a picture assembled elsewhere and passed back arrives stripped of the detail that made it a judgement — plus four investigative **legs**, each dispatched on its own question with disciplined handoff (each dispatch carries the objective, what's established, and what must not be touched; each return states what was done, learned, the confidence, and what was deliberately not done):
- **corpus / coverage leg** — survey/facet/pivot the corpus as an entity graph; track searched-vs-not; guard against false-coverage claims;
- **entity / network leg** — people/orgs/relationships, mention→entity reasoning, follow ownership and money;
- **timeline / context leg** — chronology, pattern-of-life, and outside context that bears on the material;
- **document-forensics leg** — provenance, authenticity, metadata, and translation of UK/RU material in its own register.

**Phasing.** The split is deferred, not the capability. **M2 ships one orchestrator** carrying all four as *skill families* on the shared spine — a single capable analyst — so the split into dispatched legs happens at **M4** along the seams real use shows to matter. The roster ships as editable markdown; an analyst can add/remove/rewrite legs per investigation, and Jack Ryan provides the default four.

**The spine** — carried by every analyst — is a set of structured-analytic techniques: hypothesis testing (hold competing explanations, hunt what would kill each), key-assumptions check, calibrated confidence, naming the gaps, deception detection, multi-source fusion, and briefing/reporting, plus the working-loop skill below.

**The analyst loop (end-neutral closure).** On each pass over fresh material or at a decision point: read → fuse → reach one **calibrated judgement** attributed to the hypothesis that raised it → decide a **next move** (dig / pivot / hand a collection task back / brief the human). A gap is named and handed back, never treated as a stopping point; disagreement is surfaced, not averaged. Each pass updates the Operating Picture.

**Write scopes.** *May (analyst profile):* search, read (bounded), cite; create/remove its *own* tags, notes, flags; propose mention-level judgments; write provisional operating-picture entries; create and edit **draft** reports. *May not:* ingest, delete, modify originals or extracted text, alter human-authored annotations or picture entries, finalize reports, or touch admin/doctor surfaces. Everything the agent writes is attributed to its agent Actor and revertable in bulk. The agent proposes, the human confirms — confirmations become durable Judgments and confirmed picture entries; unconfirmed proposals stay visibly provisional. Two guardrails are load-bearing: **evidence is read-only** (principle 3) and **retrieved content is data, never instructions** (principle 5).

## 7. Collaboration path

- **v1:** one analyst + agent(s); the attribution schema is live; casefiles are compartments.
- **Post-v1 (server mode):** authentication (OIDC), per-casefile view/edit ACLs for users and groups, recommend-to-teammate, shared saved/batch searches. No schema migration required, by design.

## 8. Non-goals (v1)

No dataset publishing; no cross-instance federation; no structured-data mapping DSL; no embedded agent runtime; no entity-graph UI; **no web UI (v1 is CLI + MCP)**; no multi-user/auth.

## 9. Security & data-handling posture

Local-first: corpus content leaves the machine only toward explicitly configured endpoints (principle 1). Document text is **evidence, never instruction** — fenced and provenance-tagged at the MCP boundary, with injection-aware error handling (principle 5). Secrets live in the environment only; the repo is public, so no secrets, host/infra fingerprints, or real corpus contents ever enter tracked files, and a secret-scanner gate runs in CI from the first commit.

## 10. Implementation plan

**Prototype-first.** The fastest path to something real is a prototype that proves one loop: *ingest documents → the AI works the corpus over MCP and answers with resolvable citations.* Everything not on that critical path is deferred behind it — sequenced, not cancelled. The **prototype is M0–M2**; the fuller capability set follows as **M3–M4**; the rest is beyond that. Each milestone becomes one or more OpenSpec changes.

### The prototype (M0–M2)

- **M0 — Bootstrap.** Repo, OpenSpec scaffolding, CI gates (tests + a type-diagnostic ratchet + a secret scanner), Docker Compose skeleton, layered config (a universal corpus **contract** vs swappable infra **profiles**), service-layer + `StorePort` skeleton with the SQLite implementation, casefile CRUD. *Accept: compose up yields a healthy empty instance; CI green.*
- **M1 — Ingest & search, lean.** Born-digital baseline formats only (PDF/DOCX/PPTX/text/MD/HTML — no OCR, no VLM, no container recursion); dedup + stable UUIDs; chunk + embed; hybrid keyword+vector search with RRF fusion (no rerank, no section-window expansion); **per-chunk summarization off** so ingest is fast and cheap; CLI + REST. *Accept: drop a folder of born-digital docs into a casefile and get good hybrid search, offline, at seconds-per-doc.*
- **M2 — MCP read surface + one analyst.** `readonly` profile: `case_*` search/read/cite tools with untrusted-text fencing, bounds, chaining ids; citations resolve. Ships one analyst role on the structured-analytic spine (no leg split). *Accept: an MCP-connected agent, verified with at least two model vendors, surveys, pivots, and answers with accurate citations over a casefile — the prototype demo.*

That is the whole prototype: three milestones, no writes, no mentions, no OCR, no operating picture, no reports, no UI.

### Deferred behind the prototype (returns in the milestone shown)

- **Extraction quality** — OCR (eng+ukr+rus), the VLM escalation path, and the UK/RU extraction spike → **M3**.
- **The hard formats** — email (EML/MBOX/MSG), spreadsheets, archives & folder-tree recursion; **PST last** → **M3**.
- **Retrieval quality** — cross-encoder rerank and section-window expansion → **M3**.
- **Summarization layer** — per-chunk contextual summaries and per-document summaries → **M3**.
- **Mentions / NER** — classical NER + pattern identifiers as facets and pivots → **M3**.
- **Attributed writes** — agent tags/notes/flags with attribution and bulk revert → **M4**.
- **The Operating Picture** — the four-type picture object, its tools, and the end-neutral loop. *The differentiator: deferred, not diminished.* → **M4**.
- **The analyst roster** — splitting the single agent into orchestrator + four legs → **M4**.
- **Reports** — DB-row reports with citations and export (MD first; DOCX/PDF later) → **M4**.
- **Reconciliation** — the doctor tool for store ↔ disk drift → **M4**.
- **Web UI, entities, cross-referencing, server mode, embedded assistant** → beyond M4.

### Beyond the prototype

- **M3 — Depth: quality, formats, mentions.** OCR + VLM behind the quality gate; the UK/RU extraction spike; email/spreadsheet/archive extractors (PST last); rerank + section-window expansion; the summarization layer; NER + pattern mentions as facets. *Accept: a realistic mixed dump ingests with hierarchy and mentions across all three languages, retrieval quality high.*
- **M4 — Analysis: writes, picture, roster, reports.** `analyst` profile with attributed writes + bulk revert; the **Operating Picture** (one polymorphic entry table, four types, provisional/confirmed, flag-stale-never-delete) + its tools and the end-neutral loop; the orchestrator + four legs split; DB-row reports with resolvable citations, draft→reviewed lifecycle, and MD/DOCX/PDF export. *Accept: the agent runs a loop that maintains a calibrated, gap-named picture and drafts a fully cited brief; "undo everything the agent did" works.*
- **Further phases:** P5 web UI · P6 entities (curated FtM entities, mention→entity promotion, judgments) · P7 cross-referencing + batch search · P8 server mode (auth, ACLs, recommend) · P9 embedded assistant. The service/storage seam means these add on without reworking the core.

## 11. Open questions for review

**Resolved in review** (kept for the record): license **AGPL-3.0-or-later** — copyleft with the network clause, so a hosted derivative must publish its changes; it also keeps a future dual-licensing option open, which a permissive license would close permanently; naming (`case_*` tools, `jackryan` binary); NER (classical uk+ru+en models + regex identifier extractors as the offline baseline, optional LLM pass behind a plugin seam); single-store sqlite-vec; reports as DB rows + renderers; public repo; roster of orchestrator + four legs, shipped single in M2 and split at M4, as editable markdown; a curated maintainer-authored skill set (no autonomous authoring), with evidence-chain traceability as the enforced invariant; the operating-picture schema (one polymorphic table, four types, provisional/confirmed, flag-stale-never-delete); web UI deferred out of v1.

**Still open** (each has a decide-by milestone; none blocks review):
- **PST extraction library** (by M3): a dedicated parsing library vs a subprocess tool — licensing and robustness check.
- **Extraction spike specifics** (M1): docling OCR engine choice/config for eng+ukr+rus, where the VLM pipeline earns its cost, and what the offline-fallback floor guarantees.
