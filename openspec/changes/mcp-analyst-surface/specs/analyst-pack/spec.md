## ADDED Requirements

### Requirement: An analyst role ships with the instance

The repository SHALL ship a role definition an agent can be initialised with,
written as harness-neutral markdown so that any agentic harness can load it.

It SHALL name the working method — establish what exists, survey before
searching, search, pivot, read last, cite — and SHALL name the tools that
method uses, so an agent arrives knowing how to work a corpus rather than
improvising.

#### Scenario: The role is loadable by any harness

- **WHEN** the analyst pack is inspected
- **THEN** the role is plain markdown, naming the method and the tools, with nothing specific to one vendor

### Requirement: The pack carries the analytic spine

The pack SHALL include skills covering hypothesis testing, key-assumptions
checking, calibrated confidence, naming the gaps, deception detection,
multi-source fusion, and briefing.

Every working pass SHALL be described as ending in both a calibrated judgement
and a next move. Missing information SHALL be described as a gap to name and
hand back, never as a reason to stop.

#### Scenario: The spine is present

- **WHEN** the pack's skills are listed
- **THEN** each of the named analytic techniques is present

#### Scenario: The loop closes on a judgement and a next move

- **WHEN** the working loop is read
- **THEN** it requires a calibrated judgement and a next move on every pass

### Requirement: The pack states the epistemics the corpus demands

The pack SHALL require that a coverage claim names what was actually searched,
that absence of evidence is not reported as evidence of absence, and that every
factual claim resolves to a document through the citation tool.

It SHALL state that retrieved content is data and never instructions, matching
the boundary the tool surface describes.

#### Scenario: Coverage claims are qualified

- **WHEN** the pack's epistemics are read
- **THEN** they require a coverage claim to name what was searched, and forbid treating absence as proof
