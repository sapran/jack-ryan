## Context

`case_mentions` reports how many documents carry an identifier. Nothing can list them. The
only identifier-filtered read is `case_search`, bounded by a result limit (capped at 50 on
the agent surface, no paging) and by the candidate depth its two legs are asked for.

## Goals / Non-Goals

**Goals.** A bounded, deterministic, paged enumeration of every document carrying one
normalised identifier, whose entries can be read and cited without a ranked search, and
whose counts reconcile with the inventory it follows from.

**Non-goals.** Changing ranked search's behaviour, paging it, or raising its depth. An
unbounded "give me every carrier" call. Repairing stale mention offsets in existing corpora.

## Decisions

### The enumeration is a separate path, not a mode of search

Search answers "which passages best match this", bounded by depth and limit; this answers
"which documents carry this", bounded only by how many pages the caller reads. Paging search
by raising the depth was the obvious alternative and is unusable: reciprocal rank fusion ties
routinely, so two requests at different depths do not agree about which candidate sits at a
given position, and pages cut from that ordering repeat and omit entries silently.

It also embeds nothing. It is a question about what was extracted, not about similarity, so
it runs against an instance with no embedding endpoint reachable.

### One predicate, two queries

The enumeration and the search filter ask the same question of the same three `mentions`
columns. `mention_predicate` in `storage/retrieval.py` is the single definition; the search
filter splices it into its chunk-id subquery, and `sqlite.py` imports it by name for the
aggregate query. Two spellings of one predicate drift silently — a filter honouring a named
kind beside an enumeration that forgot to would disagree about what carries an identifier,
and neither would error. This is the arrangement `legacy_office` already has with
`sniffing`'s magic numbers, for the same reason.

`mention_facets` deliberately does not use it: its predicate omits `normalised`, which it
groups by rather than filters on, so it is a different question about the same table.

### The query lives in `sqlite.py`, the predicate in `retrieval.py`

The enumeration is a paged document listing and must hydrate `Document` rows through
`_row_to_document`, which is in `sqlite.py`; `retrieval.py` cannot import from `sqlite.py`.
So the query goes beside `list_document_page`, whose count-and-page-under-one-predicate
shape, narrow-then-widen join, repeated outer `ORDER BY` and offset flooring it copies.

The page is chosen on a query touching only `mentions` and the two small `documents` columns
it orders by, then widened. Ordering `SELECT d.*` directly puts `extracted_text` through the
sorter, which is the whole cost this page exists to avoid.

### Occurrences are counted by position, never by row

`COUNT(DISTINCT m.document_offset)`, the way `mention_facets` counts. Chunks overlap by the
contract's overlap, so an occurrence near a boundary is extracted into two rows; a row count
is wrong by exactly that overlap, invisibly. Counted this way, the entries' counts sum to the
facet's `mentions` and the entry count equals its `documents` — two figures the same instance
reports about one identifier, which is the only check either number gets.

### The ordering ends in the document id, deliberately

`mentions DESC, containment_path, created_at, id`. The count leads so the most heavily
carrying document is reached first; `id` is unique, so the order is total and a page boundary
cannot land inside a tie. This is deliberately unlike the fused-ranking rule forbidding a tie
broken by an identifier: that rule exists so two stores built from the same documents rank
alike, and document ids differ between stores. Here the requirement is only that one
unchanged store pages consistently, and `id` is reached only where two documents are equal on
the count, the containment path and the creation time.

### Each entry carries a passage identifier

The earliest occurrence's position, then the lowest chunk ordinal — the two chunks sharing an
overlap hold the same occurrence, and the earlier chunk is the one a reader reaches first.
One statement for the whole page rather than a correlated subquery per row, which would
re-seek every mention of the identifier in the casefile once per row.

This is what makes the enumeration evidence rather than a list. The passage stays the unit
that is cited, as everywhere else.

### An empty identifier is refused; an unknown kind is refused; an absent one is not

`_parsed_mention` returns no filter for an empty value, which is right for a search and wrong
here — the store would match `normalised = ''` and the empty result would read as "this
casefile carries no such identifier". An unknown kind is refused naming the kinds, per the
existing rule. A well-formed identifier no document carries is an empty page whose message
says the inventory records only what the extractors found.

### No schema change

`idx_mentions_pivot(casefile_id, normalised)` serves the seek and
`idx_mentions_facet(casefile_id, kind, normalised)` serves it with a kind. `SCHEMA_VERSION`
stays 8; no corpus is refused or migrated.

## Risks / Trade-offs

- **A corpus ingested before the chunk-offset fix** holds stale `mentions.document_offset`
  values, so its per-carrier counts and the inventory's mention counts inherit the same known
  overcount. The carrier set and `total_matching` stay correct — those come from
  `COUNT(DISTINCT document_id)`. Mitigation is the existing `jackryan repair
  mention-offsets`, deliberately not invoked by this change.
- **A total counted under a different predicate than the page** would keep `truncated` true
  past the last entry, so a caller following `continue_from` would never terminate. Both are
  composed from the same predicate string and binds, and the new test file's sweep loop is
  bounded so that failure reddens rather than hangs.
- **Four surfaces to keep in step.** Mitigated by one service method behind all of them and a
  cross-surface test comparing all four against a hand-counted expectation rather than
  against each other.
