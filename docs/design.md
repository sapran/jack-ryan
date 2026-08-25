# Jack Ryan — Design Document & Implementation Plan

**Status:** v0.1 draft, for plan/spec review. High-level by intent; every section is an anchor for review, not a finished spec. Each milestone below becomes one or more OpenSpec changes in the new repo.

---

## 1. Mission

Jack Ryan is a self-hosted **investigation workbench**: a human analyst drops heterogeneous document dumps into casefiles and works them — search, facet, tag, annotate, pivot, report — side by side with an **agentic AI assistant** that has first-class MCP access to everything ingested. The assistant is a junior analyst, not a search box: it reads, pivots, tags, and drafts citation-backed briefs, with every action attributed and reviewable.

Named for Tom Clancy's CIA analyst — the desk officer who wins by actually reading the documents. The tool's job is to turn one analyst plus an AI into the person who read all of them.

**Lineage.** Aleph (OCCRP → OpenAleph) and Datashare (ICIJ) define the collaborative-analyst-platform genre. lib.ai defines our ingestion / summarization / retrieval / MCP machinery. aleph-mcp and datashare-mcp define our agent-safety and agent-epistemics conventions. acordia-agents defines the analyst *tradecraft* — how the AI assistant divides the work and reasons about evidence. Jack Ryan is a **new codebase** that borrows patterns from all of them and depends on none of them.

## 2. What we take from where

| Source | Adopted | Deliberately not adopted |
|---|---|---|
| **Aleph** | FollowTheMoney as the entity vocabulary (phased in); casefile scoping modeled on investigations; automatic *mention* extraction (NER + pattern IDs) feeding facets and later matching; the epistemic split between machine *hypotheses* (similar/xref scores) and recorded *human decisions* (profiles/judgments); network-of-entities as the eventual growth path | Postgres + Elasticsearch + RabbitMQ stack; the CSV/SQL mapping DSL (post-v1 candidate); dataset *publishing* — Jack Ryan is a workbench, not a data platform |
| **Datashare** | Local-first posture (runs on one machine, sensitive data never leaves); document-centric pragmatism; hierarchy-preserving extraction (container → member, email → attachment); the thin social layer (tags, stars/flags, recommend) as the collaboration primitive; batch search as a headline later feature | Java/ES stack; NER-pipeline plurality as a product identity; separate frontend repo |
| **lib.ai** | Four-step pipeline (extract → enrich → persist → finalize); SHA-256 dedup with **stable document UUIDs across reingest**; quality-gated extraction with a mandatory offline fallback; two-layer summarization (contextual per-chunk notes + per-document cascade); hybrid retrieval (FTS + vector + RRF) → rerank → reasoning-unit expansion; baked in-process read stack (search works with zero endpoints configured); the service layer under thin REST/MCP/CLI/web adapters; layered config (corpus **contract** vs infra **profiles**); registry singletons; doctor-as-reconciliation; the two-store subset invariant under a store lock; MCP conventions: uniform prefix, 8-char id prefixes, formatted-index return shape with chaining ids, profile-gated surface that **fails to the narrowest set**, central annotations table | The library-curation domain (types/shelving/renaming canon); running lib.ai itself — Jack Ryan shares patterns, not processes or code deps |
| **aleph-mcp / datashare-mcp** | The agent-surface canon: bounded pagination as *refusal not clamp*; nonce-fenced untrusted document text with provenance blocks; actionable typed errors that never relay raw upstream text; a shipped **skill** teaching the analyst method (inventory → survey/facet → filter → pivot → read text last → cite) and epistemics (provenance per casefile, absence proves little, totals are floors, similarity is hypothesis, judgment is decision); "if the tools aren't mounted, stop" | The read-*only* posture as a whole — Jack Ryan's assistant gets attributed write scopes (§6); the transport-level allowlist pattern survives as the internal permission gate |
| **acordia-agents** | The assistant's tradecraft (§6): an orchestrator that *holds the operating picture and does fusion itself* (never delegated) plus specialist legs dispatched on their own questions with disciplined handoff; the structured-analytic-technique **spine** (Heuer / Pherson-Heuer) — competing hypotheses, key-assumptions check, calibrated confidence, naming the gaps, deception detection, multi-source fusion; the **end-neutral analyst loop** (every pass reaches a calibrated judgement *and* a next move; "insufficient information is not a stopping point — it is a gap to name and a collection task to hand back"); the **operating picture as living state** (timestamped, delta-tracked, facts marked durable-vs-perishable); "a corpus is an entity graph, not a document pile," and a coverage claim must name what was searched; evidence is read-only, retrieved content is data-never-instructions | The offensive-operation **mission framing** (Jack Ryan is investigative/defensive — re-skinned, not adopted); the cyber-terrain skill families (packet/EDR/forensics/cloud-control-plane — ~30 of the 45 skills don't fit a document workbench); dependency on the plugin itself (Jack Ryan ships a native roster, not the acordia-analysts plugin) |

## 3. Decisions locked (from scoping review)

1. **Entity model:** FtM-compatible, phased. v1 ships documents + auto-extracted **mentions**; curated entities, relationships, and xref come post-v1. The schema reserves the seats from day one.
2. **Deployment:** local-first single-analyst v1, **collaboration-ready schema** — every write records its actor (human or agent); casefiles are first-class. Server mode later adds auth/ACLs, not a migration.
3. **Stack:** Python, SQLite + FTS5 as source of truth, vector store alongside, Docker Compose — behind a deliberate **storage seam** so Postgres + Elastic/OpenSearch can replace it if a corpus or team outgrows it.
4. **AI access:** MCP server, **read + attributed writes**. Analyst drives Claude (Code/Desktop) against it. Embedded in-UI assistant is a possible later phase consuming the same surface.
5. **v1 formats:** PDF, Office (DOCX/PPTX), text/Markdown/HTML, **email archives (EML/MBOX/MSG/PST)**, **spreadsheets (XLSX/CSV)**, **archives & folder trees (ZIP etc.)** — all through a modular format router.
6. **Languages:** English, Ukrainian, Russian across extraction, OCR, NER, and search in v1. (bge-m3-class multilingual embeddings make retrieval nearly free; OCR/NER need explicit packs.)
7. **Reporting:** citation-backed briefs as first-class casefile artifacts; exportable.
8. **Home:** new dedicated repo (`sapran/jack-ryan` or similar), OpenSpec-governed like the sibling projects.
9. **Analyst layer:** borrow ACORDIA's *doctrine*, ship a *native* roster. Jack Ryan defines its own thin orchestrator + a small set of investigative legs and a spine of structured-analytic-technique skills, re-skinned for investigation and shipping only the document-relevant families — no dependency on acordia-agents, and the cyber-terrain skills left out.
10. **Operating picture:** a first-class, agent-maintained casefile object (see §4) — current judgements with calibrated confidence, named gaps, hypotheses under test, facts marked durable-vs-perishable. The assistant's cross-session memory and the spine of its reports.

**Stated assumptions (correct me in review):**
- Scale target: casefiles of 10³–10⁵ documents, single machine. The seam covers growth beyond that; v1 does not chase millions.
- LLM/embedding infra follows lib.ai: OpenAI-compatible endpoints, comma-separated round-robin, local-model capable; corpus content goes only to explicitly configured endpoints, nothing outbound by default.
- The assistant is Claude via MCP; no other agent runtimes targeted in v1.

## 4. Domain model (high level)

- **Casefile** — the unit of scoping, provenance, and (later) access control. Every document, tag, note, report, and search belongs to exactly one casefile. Modeled on Aleph investigations / Datashare projects.
- **Document** — immutable original (content-hash addressed) + extracted text + metadata + detected language(s). **Hierarchy is first-class:** archive → members, mailbox → messages → attachments, folder trees preserved as paths. Stable UUID across reingest (lib.ai invariant).
- **Chunk** — retrieval unit with heading-path context and contextual summary, per lib.ai's embed-text pattern.
- **Mention** — machine-extracted reference in a document: person/org/location names (NER) and pattern identifiers (emails, phones, IBANs, card/passport-shaped ids). Faceted and pivotable. Mentions are *hypotheses*; they carry extractor + confidence provenance. FtM-typed so they can later be promoted to entities.
- **Entity** (post-v1) — curated FtM entity; **Judgment** — a recorded human (or human-confirmed) decision linking mentions/entities (same/not-same), Aleph's profile pattern.
- **Tag / Note / Flag** — the social layer, Datashare-style. Every one records `actor` (which human or which agent identity) and `origin` (manual / assistant / pipeline).
- **Report** — a first-class artifact: narrative body + structured **Citations**, each resolving to (document, chunk, span). Draft → reviewed lifecycle; author-attributed; exportable (Markdown/DOCX/PDF). Draws on the Operating Picture as its spine.
- **Operating Picture** — a per-casefile **living state** the assistant maintains (ACORDIA's idea; nothing in Aleph or Datashare has it): current **judgements** each with calibrated confidence and the hypothesis/leg that raised it, named **intelligence gaps** (answerable questions with a route and an owner), **hypotheses under test**, and **facts** marked durable-vs-perishable with a decay/re-verify flag. Everything timestamped, delta-tracked ("what changed since last read and what it implies"), and attributed (human vs agent). It is the assistant's cross-session memory and reconciles against new material on each analyst-loop pass. Write-scoped like tags/notes: agent-authored entries are provisional until a human confirms.
- **Actor** — human user or named agent identity. Exists in v1 with one human; makes "show me everything the agent did this session" a query, and makes server mode an authorization feature, not a data-model change.

## 5. Architecture

**One service, four adapters** (the lib.ai shape): a Python/FastAPI core owning all business logic in a service layer; REST, MCP (mounted in-process), CLI, and a separate thin web UI (talks HTTP only, ships as its own image, never imports core code) are adapters. Bounds/containment checks live in the service layer so every adapter inherits them.

**Stores.** SQLite (+FTS5) as source of truth; a vector store for embeddings — behind a `StorePort` seam (the one deliberate abstraction; open question: sqlite-vec could collapse the two stores into one). Embed-contract fingerprint checked at boot; two-store **subset invariant** (vectors ⊆ what rows justify) under a store lock; `doctor` reconciles.

**Ingestion.** Per-casefile inbox (watched directory + upload API) → threaded workers → four-step pipeline:
1. *Extract* — the **format router**: a plugin registry of Extractor implementations, each declaring `sniff()` (magic/MIME/extension) and `extract()` returning a normalized **DocumentGraph** (text blocks + structure + child documents + native metadata). Container extractors (ZIP, mailboxes, PST) recurse with depth/size/zip-bomb guards, emitting children through the same pipeline with `parent_id`. Remote extraction endpoint (docling-serve-class) optional; an in-process fallback is mandatory for every v1 format. Quality gate → OCR escalation (Tesseract, eng+ukr+rus).
2. *Enrich* — per-chunk contextual summaries; per-document summary cascade; NER + pattern extraction → mentions; metadata cascade (LLM-first, deterministic fallbacks, per-field provenance).
3. *Persist* — one lock hold; dedup by content hash; UUID reuse on reingest.
4. *Finalize* — originals archived content-addressed within the casefile; failure/retry ledger, crash recovery on boot, per-document time budget — all per lib.ai.

**Search.** Casefile-scoped always. Hybrid FTS+vector with RRF fusion → cross-encoder rerank (degrades to unranked, never blocks) → reasoning-unit expansion for agent consumption. Facets: doc type, language, date, path/container, mention, tag, actor. Baked read stack: search works offline with zero configured endpoints.

**MCP surface.** lib.ai conventions throughout: uniform tool prefix (open question: `case_*` vs `jr_*`); 8-char id prefixes; formatted-index + chaining-ids return shape; bounded reads with explicit truncation; typed error payloads; central annotations table; **profiles fail to the narrowest surface**. Three profiles: `readonly` (search/read/cite only — the aleph-mcp posture), `analyst` (default: reads + attributed writes per §6, including Operating Picture entries), `admin` (ingest/delete/doctor — intended for the human via CLI/REST, not normally advertised to the agent). All corpus-derived text nonce-fenced as untrusted, with provenance blocks.

## 6. The assistant as analyst — a native roster on ACORDIA doctrine

The assistant is not one generic MCP agent; it is a small **analyst roster** working the Jack Ryan MCP surface, with its tradecraft borrowed from ACORDIA and re-skinned from offensive-operation support to investigation. It ships as a native pack of Claude agents + skills in this repo (markdown, like acordia-agents), so it improves independently of the machine and does not couple Jack Ryan to that plugin.

**Roster (indicative — final legs are an open question):** an **orchestrator** that holds the casefile's Operating Picture and *does the fusion itself* — a picture assembled elsewhere and passed back "arrives stripped of the detail that made it a judgement" — plus a few investigative **legs** dispatched each on its own question with disciplined handoff (each dispatch carries objective, what's established, what must not be touched; each return states what was done, learned, confidence, and what was deliberately not done). Candidate legs, re-skinned for a document corpus: a **corpus leg** (survey/facet/pivot the corpus as an entity graph, coverage accounting), an **entity leg** (people/orgs/relationships, mention→entity reasoning), a **timeline/context leg** (chronology, pattern-of-life, non-textual context), and a **document-forensics leg** (provenance, authenticity, metadata, translation). Two to four legs, not ACORDIA's five.

**The spine** — carried by every analyst — is the transferable, domain-agnostic core of ACORDIA (Heuer / Pherson-Heuer structured analytic techniques): `hypothesis-testing`, `key-assumptions-check`, `calibrated-confidence`, `naming-the-gaps`, `deception-detection`, `reasoning-under-uncertainty`, `multi-source-fusion`, `briefing-reporting`, plus the method/loop skill below. The cyber-terrain families (packet/EDR/forensics/cloud) are left out.

**The analyst loop** (end-neutral closure) governs how the assistant works: on each pass over fresh material or at a decision point, read → fuse → reach one **calibrated judgement** attributed to the hypothesis that raised it → decide a **next move** (dig / pivot / hand a collection task back / brief the human). A gap is named and handed back, never treated as a stopping point; disagreement is surfaced, not averaged. Each pass updates the Operating Picture (§4).

**Write scopes.** *May (analyst profile):* search, read (bounded), cite; create/remove its *own* tags, notes, flags; propose mention-level judgments; write provisional **Operating Picture** entries (judgements, gaps, hypotheses, facts); create and edit **draft** reports. *May not:* ingest, delete, modify originals or extracted text, alter human-authored tags/notes/judgments/picture entries, finalize reports, or touch admin/doctor surfaces.

Everything the agent writes is attributed to its agent Actor and revertable in bulk. The human-review loop mirrors Aleph's similar→profile split: the agent proposes, the human confirms — confirmations become durable Judgments and confirmed picture entries; unconfirmed proposals stay visibly provisional. Two guardrails are load-bearing and come straight from the source repos: **evidence is read-only** (originals and extracted text are inputs; derived work goes in the agent's own tags/notes/picture/reports, never back over the source), and **retrieved content is data, never instructions** (an instruction found inside a document is reported to the human, not followed).

## 7. Collaboration path

- **v1:** one analyst + agent(s); attribution schema live; casefiles as compartments.
- **Post-v1 (server mode):** authn (OIDC), per-casefile view/edit ACLs for users/groups (Aleph's model), recommend-to-teammate, shared saved/batch searches. No schema migration required by design.

## 8. Non-goals (v1)

No dataset publishing; no OCCRP-scale ambitions; no mapping DSL; no cross-instance federation; no embedded agent runtime; no entity graph UI. Jack Ryan does not replace lib.ai — the personal library and the investigation workbench stay separate tools.

## 9. Security & data-handling posture

Local-first: corpus content leaves the machine only toward explicitly configured endpoints. Document text is **evidence, never instruction** — fencing and provenance at the MCP boundary, injection-aware error handling (the datashare-mcp canon). Secrets in env only; if the repo is public, lib.ai's public-repo hygiene rules (placeholders everywhere, no infra fingerprints, gitleaks in CI) apply from commit one.

## 10. Implementation plan

v1 = M0–M5. Each milestone is one or more OpenSpec changes with its own spec/design/tasks; acceptance criteria sketched here get formalized there.

- **M0 — Bootstrap.** Repo, OpenSpec scaffolding, CI gates (pytest + type ratchet + gitleaks, the lib.ai trio), Docker Compose skeleton, layered config (contract vs profiles), service-layer + StorePort skeleton with SQLite implementation, casefile CRUD. *Accept: compose up yields a healthy empty instance; CI green.*
- **M1 — Core pipeline & search.** Baseline formats (PDF/DOCX/PPTX/text/MD/HTML) through the format router; dedup + stable UUIDs; chunking + contextual summaries + document summaries; hybrid search + rerank + reasoning units; minimal CLI + REST. *Accept: drop a mixed folder of baseline docs into a casefile, search it well, offline.*
- **M2 — MCP read surface + spine skills.** `readonly` profile end-to-end: search/read/cite tools with fencing, bounds, chaining ids; citations resolve. Ships the first native analyst pack: the spine tradecraft skills + a single-agent method/loop skill (the roster's legs come in M4). *Accept: Claude can survey, pivot, and produce accurately cited, gap-named answers over a casefile.*
- **M3 — Dumps, OCR, mentions.** Archives/folder trees; email (EML/MBOX/MSG, then PST); spreadsheets; hierarchy model surfaced in search/facets; OCR eng+ukr+rus behind the quality gate; NER + pattern mentions as facets and pivots. *Accept: a realistic ZIP-of-mailboxes-and-scans dump ingests with hierarchy intact; mention facets work in all three languages.*
- **M4 — Attributed writes, operating picture, roster & reports.** `analyst` profile: agent tags/notes/flags with attribution and bulk revert; the **Operating Picture** object + its read/write tools and the end-neutral analyst loop over it; the **orchestrator + investigative legs** roster; report artifacts with resolvable citations, draft→reviewed lifecycle, MD/DOCX/PDF export. *Accept: the agent runs a loop that updates a calibrated, gap-named operating picture and drafts a brief whose every claim clicks through to a passage; "undo everything the agent did" works.*
- **M5 — Web UI.** Thin separate app: casefile browser, search + facets, document reader with mention/citation highlights, tag/note panels, an **operating-picture review view**, report review. *Accept: an analyst can run a small investigation without the CLI.*

**Post-v1 phases:** P6 entities (FtM store, mention→entity promotion, judgments) · P7 xref-lite (cross-casefile matching on mention fingerprints) + batch search · P8 server mode (auth, ACLs, recommend) · P9 embedded assistant (optional).

## 11. Open questions for review

1. MCP tool prefix and repo/product naming (`jack-ryan`, binary `jackryan`? tool prefix `case_*`?).
2. NER engine for EN/UK/RU: spaCy vs Stanza vs LLM-pass mention extraction reusing the enrichment call (cheapest to build, costliest per doc). Could be pluggable like extractors.
3. Vector store: Chroma (proven in lib.ai) vs sqlite-vec (one store, one backup, simpler subset invariant). Leaning sqlite-vec — but it's a contract-level decision, so decide before M1.
4. PST extraction: libpff/pypff vs readpst subprocess — licensing and robustness check needed before M3.
5. Reports: stored as DB rows with export renderers (recommended) vs markdown files on disk.
6. Repo visibility: **resolved — public** (lib.ai hygiene rules apply; gitleaks CI lands in M0).
7. Web UI stack (M5) — plain server-rendered vs SPA; can stay open until M4.
8. Analyst roster: how many legs (2–4) and their exact operating questions — corpus / entity / timeline-context / document-forensics is a starting cut, not settled. Firm up before M4.
9. Should Jack Ryan borrow ACORDIA's competency-grid *method* (a grid as single source of truth, skills traceable to grid rows, doctrine-provenance register) for its own analyst pack — the rigor that keeps the skill library from growing by invention — or ship a lighter skill set without that machinery? Decide before M4.
10. Operating Picture schema specifics: judgement/gap/hypothesis/fact as one polymorphic table vs separate tables; how decay/perishability is represented; whether confirmed picture entries are a distinct type from provisional ones or a status flag.
