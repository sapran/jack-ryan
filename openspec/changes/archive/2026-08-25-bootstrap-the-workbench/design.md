## Context

M0 has one job: turn a design document into a running instance without
prejudging M1. The design decisions were settled in review (`docs/design.md`
§3); this document records how they are realised in code, and where the
implementation deliberately stops short of the target system.

## Decisions

### The service layer is the only place rules live

REST and CLI both call `CasefileService`. Neither validates, neither resolves
references, neither decides what a slug may contain. This is enforced by
construction rather than by convention: the adapters have no validation code
to drift, and the same test asserting a rule at the service layer covers both
surfaces.

The cost is that an adapter cannot cheaply special-case anything. That is the
intent — a rule enforced in one adapter is a second, divergent definition of
the domain, and the MCP surface arriving in M2 has no request-validation layer
of its own to fall back on.

### The CLI calls services directly, not HTTP

A CLI that is an HTTP client cannot run against a stopped instance, and M0's
whole value is being able to poke at the thing locally. `jackryan status`
opens the store directly. The trade is that the CLI must run where the data
is; for a local-first single-analyst tool that is already true.

### Reference resolution lives in one method, and refuses to guess

`CasefileService.resolve` accepts a full id, an 8-character id prefix, or a
slug, tried in that order. An ambiguous prefix raises rather than returning
the first match: handing back the wrong casefile with no signal is worse than
an error the caller can act on. Exact-id and slug lookups are tried before
prefix matching so a slug that happens to look like a hex prefix still
resolves to the casefile it names.

### The store records its contract on first boot

`store_meta` holds `schema_version` and `contract_fingerprint`. The first
`initialize()` writes them; every later one compares and refuses to continue
on a mismatch. Without this, changing `chunk_size` after ingestion would
silently append incompatible chunks to an existing corpus, and nothing would
record that two different rule sets produced it.

This guard exists in M0, before any corpus does, precisely because it cannot
be added retroactively with any authority.

### Locking is `threading`, not `asyncio`

The server is async but ingestion will run in a thread pool from M1, so the
store's guard has to hold for worker threads. An asyncio lock would not, and
discovering that after ingestion exists means debugging interleaved writes.

### One SQLite file, no second store

Text and vectors in one transactional store means they cannot drift apart —
there is no subset invariant to maintain and no reconciliation to write
between them. `StorePort` remains as the seam for a later heavier engine, but
it is the only abstraction M0 introduces; everything else is concrete.

## Risks / Trade-offs

- **The contract declares unused values.** Accepted deliberately (see the
  proposal's *Still deferred*): the guard must predate the corpus.
- **`StorePort` has one implementation.** A seam with a single implementation
  is speculative generality unless it is cheap, and this one is: a Protocol
  with no runtime cost that keeps SQL out of the service layer.
- **Casefile deletion is unguarded.** There is nothing to cascade to yet. When
  documents exist, deletion needs a confirmation gate — noted for M1 rather
  than half-built now.

### Two requirements were narrowed at publication

The spec rules forbid specifying a mechanism the repository does not have. Two
drafted requirements asserted mechanisms belonging to later milestones — text
and vectors sharing one store, and every document and tag belonging to a
casefile — so at publication each was narrowed to what is true today, with the
forward commitment moved to a `docs/design.md` reference. The commitments are
unchanged; they are simply not yet normative.

## Migration Plan

None. First change in the repository; there is nothing to migrate from.

## Open Questions

- Whether `jackryan status` should degrade gracefully when the store is
  unreadable, rather than raising. Left as-is: a store that will not open is
  exactly the condition an operator needs reported loudly.
