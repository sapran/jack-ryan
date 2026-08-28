## ADDED Requirements

### Requirement: Reranking reorders the fused candidates and is never required

An instance MAY be configured with a reranker that scores each fused candidate
against the query and reorders them before the result is bounded to the caller's
limit. Reranking SHALL only reorder what fusion produced: it SHALL NOT introduce
a chunk neither retriever returned, and SHALL NOT reach outside the casefile.

The number of candidates a reranker sees SHALL be configurable and bounded,
independently of how many results the caller asked for. A reranker that sees only
as many candidates as the caller wants cannot improve anything — the ordering it
is given is already the answer.

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
- **THEN** results are returned in the fused order and the response reports that it was not reranked

#### Scenario: Reranking reorders only what fusion returned

- **WHEN** a search runs with a reranker configured
- **THEN** every returned chunk was returned by at least one retriever, and the response reports that it was reranked

#### Scenario: A reranker that cannot be built is fatal

- **WHEN** a profile names a reranker that cannot be constructed
- **THEN** the failure is raised naming the setting, rather than searches silently returning the fused order

#### Scenario: A reranker failing on one response degrades to the fused order

- **WHEN** the reranker raises while scoring a response
- **THEN** the search returns the fused ordering and the response reports that it was not reranked

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

Within one response, two results SHALL NOT return overlapping windows. A result
whose window would overlap one already returned SHALL be narrowed until it does
not, to its matched chunk if necessary. The same text arriving twice under two
identifiers costs the caller its budget twice and invites double-counting of one
passage as two pieces of evidence.

#### Scenario: A result's text extends beyond the matched chunk

- **WHEN** a search matches a chunk in the middle of a section that fits the budget
- **THEN** the returned text contains the chunk's text and extends beyond it, as one contiguous span of the document

#### Scenario: The window does not cross a heading boundary

- **WHEN** a matched chunk sits at the end of a section
- **THEN** the returned text stops at the section boundary rather than running into the next

#### Scenario: The matched chunk is still what is cited

- **WHEN** a citation is requested for a result whose text was widened
- **THEN** the citation names the matched chunk's span, and quotes the chunk

#### Scenario: Two results in one response do not repeat text

- **WHEN** two results match chunks close enough that their windows would overlap
- **THEN** the later result is narrowed so no text appears twice in the response

## MODIFIED Requirements

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

#### Scenario: Agreement outranks a single retriever

- **WHEN** one chunk is returned by both retrievers and another by only one, at the same rank
- **THEN** in the fused ordering the chunk both retrievers returned ranks higher

#### Scenario: Retriever scores are still never blended

- **WHEN** a ranking is produced, with or without a reranker
- **THEN** no keyword score and no vector distance has been combined into a blended score

### Requirement: A result carries what is needed to use and to verify it

Each result SHALL carry text taken from the document it came from, the document
itself, the position within that document of the text returned, and identifiers
that address both the matched chunk and the document for follow-up.

Where the text returned is wider than the matched chunk, the result SHALL carry
both spans: the span of the text it returned, and the span of the matched chunk
within it. A single span cannot describe both, and a result whose declared
position does not cover the text it carries cannot be verified by hand — which is
the only reason the position is there.

Result counts SHALL be bounded, and the total quantity of passage text in one
response SHALL be bounded. A bound on results alone stopped being sufficient when
each result grew wider than a chunk.

#### Scenario: A result resolves to its source

- **WHEN** a search returns a hit
- **THEN** it carries its text, its document, the span of the text returned, the span of the matched chunk, and identifiers for both chunk and document

#### Scenario: A response is bounded in text as well as in count

- **WHEN** a search's results would together carry more passage text than the response permits
- **THEN** the response stays within the bound, and says that it was narrowed
