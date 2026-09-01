## MODIFIED Requirements

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

Comparability SHALL be established over corpus identity, not over a chosen list
of settings. A baseline records the figures one corpus produced, and two corpora
built from different text handed to the embedder are not comparable however well
the named settings agree. A recorded baseline that does not state the corpus
identity it was measured over SHALL be reported as not comparable rather than
compared on the settings it does state: a key absent from the baseline is
silently skipped by any check that only compares what is present, which turns
the guard into a fail-open.

Recording a new baseline SHALL be a deliberate act, not something a run performs
because the numbers changed.

#### Scenario: A run below the baseline reports failure

- **WHEN** a measurement produces figures below the recorded baseline
- **THEN** it reports failure, naming each metric that fell and by how much

#### Scenario: A baseline is not overwritten by an ordinary run

- **WHEN** a measurement runs and produces different figures
- **THEN** the recorded baseline is unchanged unless recording was explicitly asked for

#### Scenario: A baseline that does not state its corpus is not compared

- **WHEN** a recorded baseline states no corpus identity
- **THEN** the run reports it as not comparable, naming the identity the run measured over

### Requirement: A retrieval-quality claim names what it was measured on

Any reported retrieval figure SHALL name the conditions that produced it: the
corpus identity it was measured over, the embedder actually used, whether a
reranker was in the path and which one, and the query set it ran against.

A figure produced with the deterministic stand-in embedder SHALL be marked as
measuring the retrieval mechanism rather than retrieval quality. Those vectors
carry no meaning; the fused ordering they produce is real and worth regression
testing, but a quality claim drawn from them would be false.

A measurement SHALL be run with the stand-in embedder as well as the real one, so
that a difference between them demonstrates the measurement responds to retrieval
quality at all. A measurement that cannot move cannot report a regression.

#### Scenario: The report names its conditions

- **WHEN** figures are reported
- **THEN** they name the corpus identity measured over, the embedder used, the reranker used or its absence, and the query set

#### Scenario: The stand-in embedder is marked as not a quality claim

- **WHEN** the measurement runs with the deterministic embedder
- **THEN** the figures are marked as measuring the mechanism rather than retrieval quality

#### Scenario: The measurement is shown to respond to what it measures

- **WHEN** the measurement is run with the real embedder and with the stand-in
- **THEN** the reported figures differ
