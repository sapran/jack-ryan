# hybrid-search Specification

## Purpose

Defines retrieval: two retrievers over one store, fused by rank rather than by
blended score, always scoped to a single casefile.

## Requirements

### Requirement: Search combines keyword and semantic retrieval over one store

Search SHALL run two retrievers over the same store — keyword ranking over the
full-text index, and nearest-neighbour search over the vector index — and SHALL
combine their results into a single ranking.

Both SHALL be available with no endpoint configured, so an instance can search
its corpus offline.

#### Scenario: Both retrievers contribute to one ranking

- **WHEN** a search runs
- **THEN** results found by keyword and by vector similarity appear in one ranked list

### Requirement: Results are fused by rank, not by blended score

Fusion SHALL use reciprocal rank fusion, consuming only each retriever's
ordering. Scores SHALL NOT be normalised and blended: keyword scores and vector
distances are not comparable, and blending them would introduce a weighting to
tune per corpus.

In the fused ordering, a chunk returned by both retrievers SHALL rank above one
returned by only a single retriever at the same position.

These guarantees describe the fused candidate ordering. A reranker, where one is
configured, SHALL be a later stage that consumes that ordering and MAY reorder
it, including demoting a chunk both retrievers returned — that is what a
reranker is for. It SHALL NOT be implemented by blending retriever scores, which
remains forbidden; it scores the query against the passage text and nothing else.

When two candidates fuse to the same score, the tie SHALL be broken by
properties of the corpus itself rather than by any identifier. Exact ties are
ordinary rather than rare: a chunk ranked first by one retriever and second by
the other scores precisely what a chunk ranked second and first scores.

No identifier can break them honestly. A chunk's id is minted afresh by every
reingest, and a document's id differs between one store and another built from
the same documents — so an ordering that falls back to either ranks an unchanged
corpus differently after a rebuild, and ranks two stores holding identical
material differently from each other. A retrieval figure measured under one
cannot then be compared with a figure measured under the other, which is to say
it cannot be compared with anything.

Two candidates identical in both position and text are the one exception, and
only because there is nothing left to decide: whichever is returned first, the
caller is reading the same words at the same place. Their order MAY be settled by
any stable value.

#### Scenario: A tie is broken the same way in a store built afresh

- **WHEN** the same documents are ingested into two stores, giving every chunk and document new identifiers
- **THEN** two candidates that fuse to the same score are returned in the same order in both

#### Scenario: Agreement outranks a single retriever

- **WHEN** one chunk is returned by both retrievers and another by only one, at the same rank
- **THEN** in the fused ordering the chunk both retrievers returned ranks higher

#### Scenario: The same corpus ranks the same way after a rebuild

- **WHEN** two candidates fuse to the same score and the corpus is reingested, giving them new identifiers
- **THEN** they are returned in the same order as before

#### Scenario: Retriever scores are still never blended

- **WHEN** a ranking is produced, with or without a reranker
- **THEN** no keyword score and no vector distance has been combined into a blended score

### Requirement: Every search is scoped to one casefile

A search SHALL name exactly one casefile and SHALL return only that casefile's
chunks. There SHALL be no cross-casefile search, because a casefile is the
compartment.

#### Scenario: Another casefile's content is never returned

- **WHEN** two casefiles hold documents with the same words and one is searched
- **THEN** only that casefile's chunks are returned

### Requirement: A result carries what is needed to use and to verify it

Each result SHALL carry text taken from the document it came from, the document
itself, the position within that document of the text returned, and identifiers
that address both the matched chunk and the document for follow-up.

Where the text returned is wider than the matched chunk, the result SHALL carry
both spans: the span of the text it returned, and the span of the matched chunk
within it. A single span cannot describe both, and a result whose declared
position does not cover the text it carries cannot be verified by hand — which is
the only reason the position is there.

Result counts SHALL be bounded. Widening SHALL be bounded across the response as
a whole: once the text already returned has reached the response bound, later
results SHALL carry their matched chunk alone rather than a window.

A result SHALL NOT be withheld to meet that bound. The passages a caller asked
for are what the search found, and dropping evidence to save characters is a
worse failure than a long response — an analyst cannot miss what they were never
shown. The bound governs how much context is added, not how much is found.

A result narrowed for this reason SHALL say so, so that a short answer is
distinguishable from a passage that had no more context to give.

#### Scenario: A result resolves to its source

- **WHEN** a search returns a hit
- **THEN** it carries its text, its document, the span of the text returned, the span of the matched chunk, and identifiers for both chunk and document

#### Scenario: Widening stops when the response bound is reached

- **WHEN** the results of one search would together carry more widened text than the response permits
- **THEN** later results carry their matched chunk alone and report that they were narrowed, and no result is dropped

### Requirement: Reranking reorders the fused candidates and is never required

An instance MAY be configured with a reranker that scores each fused candidate
against the query and reorders them before the result is bounded to the caller's
limit. Reranking SHALL only reorder what fusion produced: it SHALL NOT introduce
a chunk neither retriever returned, and SHALL NOT reach outside the casefile.

The number of candidates a reranker sees SHALL be configurable, and SHALL be at
least the greater of that setting and the caller's limit. A reranker shown only as
many candidates as the caller wants cannot improve anything — the ordering it is
given is already the answer. One shown fewer than the caller asked for is worse
still: it would decide how many results come back, and reranking reorders what
was found rather than deciding what is found.

An instance that names no reranker SHALL search exactly as it did before,
including offline with no endpoint configured. Reranking SHALL NOT become a
condition of searching.

A reranker that is named but cannot be built SHALL be fatal, naming the setting
and what failed, before any search returns. A reranker that fails while scoring a
particular response SHALL leave the fused ordering in place and the search SHALL
succeed. The two are different failures: the first is a misconfiguration, and an
instance that quietly serves worse results than the operator configured has hidden
it; the second is transient, and refusing to answer would make retrieval quality a
condition of retrieval.

A response SHALL disclose whether its ordering was reranked, so that a degraded
response is distinguishable from a configured-off one and from a reranked one.

The score a reranker produces SHALL NOT replace the fusion score, and SHALL be
reported as its own value. It is an uncalibrated quantity comparable only within
one response — not a probability, not a confidence, and not comparable between
queries or between models. Presenting it in place of the fusion score would both
destroy the evidence that fusion ran and invite an analyst to read it as certainty.

#### Scenario: An instance with no reranker configured searches as before

- **WHEN** a search runs on an instance that names no reranker
- **THEN** results are returned in the fused order, and the response reports that the ordering is the fused one and that no reranker was configured

#### Scenario: Reranking returns everything fusion found

- **WHEN** a caller asks for more results than the configured rerank depth
- **THEN** it receives as many as fusion found, each of them scored by the reranker

#### Scenario: Reranking reorders only what fusion returned

- **WHEN** a search runs with a reranker configured
- **THEN** every returned chunk was returned by at least one retriever, and the response reports that it was reranked

#### Scenario: A reranker that cannot be built is fatal

- **WHEN** a profile names a reranker that cannot be constructed
- **THEN** the failure is raised naming the setting, rather than searches silently returning the fused order

#### Scenario: A reranker failing on one response degrades to the fused order

- **WHEN** the reranker raises while scoring a response
- **THEN** the search returns the fused ordering, and the response reports that a reranker was configured and did not run — which is a different report from the one an instance without a reranker gives

#### Scenario: The fusion score survives reranking

- **WHEN** a reranked result is returned
- **THEN** it carries both the fusion score and the rerank score as separate values

### Requirement: A result's text is a bounded window around the matched chunk

The text a result carries SHALL be a window that contains the matched chunk and
MAY extend beyond it, so that a passage arrives with the sentences that give it
meaning rather than cut at a chunk boundary.

The window SHALL be taken from the document's extracted text as one contiguous
span. It SHALL NOT be assembled by joining chunk texts: chunks overlap by
configuration, so joining them repeats text, and a chunk's stored text has been
stripped of the whitespace its offsets still describe.

The window SHALL be bounded by a character budget, SHALL NOT cross a document
boundary, and SHALL NOT extend past a heading boundary in a document that has
headings. Where a document has no headings — a scan, a plain text file — the
budget alone SHALL bound it.

The matched chunk SHALL remain the unit that is addressed and cited. Widening
what is read SHALL NOT widen what is quoted: identifiers, the passage tool and
the citation tool SHALL continue to resolve the chunk, and a citation's span
SHALL continue to be the chunk's span.

Widening SHALL NOT repeat text another result in the same response already
carries. A window that would reach into another result's span SHALL be pulled
back, and where it cannot be pulled back without cutting into the matched chunk
it SHALL be given up in favour of the chunk alone.

Two matched chunks may still share text with each other, and that is not this
stage's doing: chunks overlap by the width the contract declares, so two adjacent
passages returned as two results carry that overlap however narrow they are made.
What SHALL NOT happen is a widened window carrying a stretch of text another
result already carried, which costs the caller its budget twice and invites one
passage to be counted as two pieces of evidence.

#### Scenario: A result's text extends beyond the matched chunk

- **WHEN** a search matches a chunk in the middle of a section that fits the budget
- **THEN** the returned text contains the chunk's text and extends beyond it, as one contiguous span of the document

#### Scenario: The window does not cross a heading boundary

- **WHEN** a matched chunk sits at the end of a section
- **THEN** the returned text stops at the section boundary rather than running into the next

#### Scenario: The matched chunk is still what is cited

- **WHEN** a citation is requested for a result whose text was widened
- **THEN** the citation names the matched chunk's span, and quotes the chunk

#### Scenario: Widening does not repeat what another result carries

- **WHEN** two results match chunks close enough that widening one would reach into the other
- **THEN** the later result is narrowed, and no text beyond the overlap the contract gives adjacent chunks appears twice in the response

### Requirement: A search may be filtered to passages carrying a given identifier

A search SHALL accept an optional identifier to filter by, and SHALL then return
only passages in which that identifier was found. The filter SHALL accept either
a kind and a value together or a value alone, and a value alone SHALL match that
value under any kind.

The filter SHALL match the normalised form, so a caller pivots on an identifier
regardless of how the document wrote it.

**The filter SHALL be applied by the retrievers rather than to their results.**
Each retriever is asked for a bounded depth of candidates, so removing
non-matching candidates afterwards discards every matching passage that ranked
below that depth unfiltered — and the deeper the corpus, the more it discards. A
caller filtering by an identifier that appears in one passage of ten thousand
would receive nothing, while the store holds exactly what they asked for. This is
the same argument already accepted for the casefile constraint, which is applied
inside both retrievers for the same reason.

The filter SHALL NOT add a rank leg, SHALL NOT contribute to any score, and SHALL
NOT reorder what the retrievers return. It decides which passages are candidates;
fusion then ranks those candidates exactly as it ranks any others. A filter that
influenced the score would be a third retriever wearing a filter's name, and the
prohibition on blending scores would be circumvented rather than honoured.

Because the filter runs before fusion, it SHALL be transparent to reranking: a
reranker still reorders only what fusion produced, and still sees no passage
neither retriever returned.

An identifier kind the instance does not recognise SHALL be refused, naming the
kinds that exist. Returning an empty result would say "this casefile contains no
such identifier", which is a different claim and a false one.

#### Scenario: A filtered search returns a passage that ranks below the unfiltered depth

- **WHEN** a passage carrying the filtered identifier would rank below the candidate depth for the query without the filter
- **THEN** it is still returned, because the filter was applied by the retrievers rather than to their results

#### Scenario: A filter changes which passages are candidates and not how they rank

- **WHEN** the same query is run filtered and unfiltered
- **THEN** the passages present in both are ranked relative to each other identically, and every score is the reciprocal-rank sum of the ranks the retrievers reported, with no term contributed by the filter

#### Scenario: A value alone matches any kind

- **WHEN** a search is filtered by a value with no kind named
- **THEN** passages carrying that value under any kind are returned

#### Scenario: An unrecognised filter kind is refused

- **WHEN** a search is filtered by an identifier kind no extractor produces
- **THEN** it fails naming the kinds that exist, rather than returning no results
