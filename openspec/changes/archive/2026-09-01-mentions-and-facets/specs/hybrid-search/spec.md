## ADDED Requirements

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
