# retrieval-evaluation Specification

## Purpose

Defines how retrieval quality is measured in this project: a fixed query set with
recorded judgements, named metrics computed through the service layer, a baseline
a later change must beat, and the rule that a quality claim names the conditions
it was measured under.

## Requirements

### Requirement: Retrieval quality is measured against a fixed query set with recorded judgements

The project SHALL carry a repeatable measurement of retrieval quality: a fixed
set of queries, each with a recorded judgement naming which document — and where
in it — answers the query, run against a corpus the measurement itself builds.

The metrics SHALL be named and defined where they are reported, and SHALL include
recall at a stated cut-off and mean reciprocal rank. A single number without its
cut-off is not a measurement anyone can reproduce or argue with.

The measurement SHALL report the two retrievers separately as well as fused, so a
later change can be attributed rather than assumed. A gain that comes entirely
from the keyword leg is a different fact about the system than the same gain from
the vector leg, and only separate figures distinguish them.

Judgements SHALL be recorded against identifiers that survive a reingest. Chunk
identifiers are minted afresh every time a document is rebuilt, so a judgement
pinned to one measures nothing the second time it is run.

The query set SHALL include queries whose wording does not share content words
with the passage that answers them. A query that repeats the target's words is
answered by keyword search alone and says nothing about semantic retrieval.

#### Scenario: The measurement reports named metrics

- **WHEN** the measurement is run
- **THEN** it reports recall at a stated cut-off and mean reciprocal rank, for the keyword leg, the vector leg, and the fused ranking

#### Scenario: Judgements survive a rebuild of the corpus

- **WHEN** the same corpus is ingested twice and the measurement is run on each
- **THEN** the judgements resolve both times and the reported figures are the same

#### Scenario: The set contains a query that shares no words with its answer

- **WHEN** the query set is inspected
- **THEN** at least one query is answered by a passage with which it shares no content word

### Requirement: Retrieval is measured through the service layer, not around it

The measurement SHALL obtain its rankings from the same search entry point every
adapter uses. It SHALL NOT reimplement fusion, ranking or bounding in order to
score them.

A measurement with its own copy of the ranking rules measures that copy. This
project already forbids a second definition of a domain rule outside the service
layer; a harness is not an exception, and a harness that drifts from the shipped
ranking reports a number for software nobody runs.

The casefile compartment SHALL hold during measurement: the harness SHALL NOT
read across casefiles to score a result.

#### Scenario: The harness ranks through the shipped search

- **WHEN** the measurement produces a ranking
- **THEN** that ranking came from the service layer's search, with no fusion or ordering computed by the harness

### Requirement: The evaluation corpus is synthetic and covers the working languages

The corpus the measurement builds SHALL be synthetic material authored for this
purpose, and SHALL NOT contain real case material, real document titles or real
filenames. It SHALL be written into a temporary workspace at run time rather than
committed as document files. This repository is public and permanent.

The set SHALL include documents that answer no query, so that recall is not
trivially satisfied by a corpus in which everything is relevant.

The set SHALL cover the three working languages — English, Ukrainian and Russian
— because the shipped embedder is multilingual and a figure measured only in
English says nothing about the corpus this workbench exists to hold.

An operator SHALL be able to run the measurement against their own query set and
corpus without modifying the harness, so that a real instance can be measured on
material that may never be committed.

#### Scenario: The measurement leaves no corpus behind

- **WHEN** the measurement finishes
- **THEN** the corpus and store it built have been removed, and nothing committable was written

#### Scenario: Every working language is represented

- **WHEN** the shipped query set is inspected
- **THEN** it contains queries and answering documents in English, in Ukrainian and in Russian

#### Scenario: An operator can measure their own material

- **WHEN** an operator supplies their own corpus and judgements
- **THEN** the measurement runs against them and reports the same metrics

### Requirement: A measurement is comparable against a recorded baseline

The project SHALL record a baseline: the figures a known configuration produced,
with the date and the conditions they were produced under. A measurement SHALL be
comparable against that baseline, and SHALL report which metrics moved and by how
much.

A measurement that falls below the recorded baseline SHALL report failure rather
than printing numbers a reader must interpret. Retrieval degrades silently — every
search still returns ten results — so the regression has to announce itself.

A comparison MAY allow a stated tolerance, and the tolerance SHALL be recorded
where the figures are. Kernels differ between machines and a tie broken the other
way moves one query, so a gate that fires on arithmetic noise is one a reader
learns to ignore — but a tolerance nobody has written down is indistinguishable
from a gate that does not work.

Recording a new baseline SHALL be a deliberate act, not something a run performs
because the numbers changed.

#### Scenario: A run below the baseline reports failure

- **WHEN** a measurement produces figures below the recorded baseline
- **THEN** it reports failure, naming each metric that fell and by how much

#### Scenario: A baseline is not overwritten by an ordinary run

- **WHEN** a measurement runs and produces different figures
- **THEN** the recorded baseline is unchanged unless recording was explicitly asked for

### Requirement: A retrieval-quality claim names what it was measured on

Any reported retrieval figure SHALL name the conditions that produced it: the
embedder actually used, whether a reranker was in the path and which one, and the
query set it ran against.

A figure produced with the deterministic stand-in embedder SHALL be marked as
measuring the retrieval mechanism rather than retrieval quality. Those vectors
carry no meaning; the fused ordering they produce is real and worth regression
testing, but a quality claim drawn from them would be false.

A measurement SHALL be run with the stand-in embedder as well as the real one, so
that a difference between them demonstrates the measurement responds to retrieval
quality at all. A measurement that cannot move cannot report a regression.

#### Scenario: The report names its conditions

- **WHEN** figures are reported
- **THEN** they name the embedder used, the reranker used or its absence, and the query set

#### Scenario: The stand-in embedder is marked as not a quality claim

- **WHEN** the measurement runs with the deterministic embedder
- **THEN** the figures are marked as measuring the mechanism rather than retrieval quality

#### Scenario: The measurement is shown to respond to what it measures

- **WHEN** the measurement is run with the real embedder and with the stand-in
- **THEN** the reported figures differ
