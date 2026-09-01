# untrusted-content-boundary Specification

## Purpose

Defines how corpus text — and text a model derived from it — crosses into an
agent's context, fenced per response and attributed to its source and to
whatever produced it, and states plainly that this is a convention the model is
asked to honour rather than a control that constrains it.

## Requirements

### Requirement: Corpus text crosses into an agent's context fenced and attributed

Any corpus-derived text a tool returns SHALL be delimited by a marker generated
per response, and SHALL carry a provenance block naming the casefile, the
document, the position it came from, and the document's containment path.

The position SHALL be the position of the text actually returned. Where that text
is wider than the passage that matched, the provenance SHALL also name the
matched passage and its own position within the document. A provenance block
that describes a narrower span than the text beside it is worse than none: it
reads as a precise reference and cannot be followed back to what was quoted.

The containment path SHALL be present because a document produced by expansion
does not identify itself: an attachment named `scan.pdf` is evidence only once
it is known which message carried it and which archive carried that. A citation
that cannot be followed back by hand is not a chain of evidence.

The marker SHALL be generated per response rather than fixed, because document
text and document metadata are attacker-controlled in the deployments this tool
exists for, and a fixed marker can be reproduced inside a document.

Every element of the containment path is document-derived, and therefore
attacker-controlled to the same degree as the text it describes. The path SHALL
be sanitised on the same terms as any other document-derived value before it
enters a line-oriented block.

#### Scenario: Returned corpus text is fenced and attributed

- **WHEN** a tool returns text taken from a document
- **THEN** the text is delimited by a per-response marker and accompanied by provenance naming its casefile, document, position, and containment path

#### Scenario: Provenance covers the text returned, not only the match

- **WHEN** a tool returns text wider than the passage that matched
- **THEN** the provenance names the span of the text returned and separately names the matched passage and its span

#### Scenario: Two responses do not share a marker

- **WHEN** two responses containing corpus text are produced
- **THEN** their markers differ

#### Scenario: Document text cannot forge the fence

- **WHEN** a document contains text imitating a fence marker
- **THEN** the marker used for that response is still unique to it, and the imitation does not terminate the fence

#### Scenario: A nested document is attributed by its path

- **WHEN** a tool returns text from a document extracted from inside a container
- **THEN** the provenance names the containment path from the ingested file down to that document

#### Scenario: A containment path cannot forge provenance

- **WHEN** an entry inside a container is named so as to imitate a provenance line
- **THEN** the path is sanitised before it is emitted, and the provenance block's structure is unaffected

### Requirement: The payload states that corpus content is evidence, not instruction

A payload carrying corpus text SHALL state that the content is material to
analyse and that an instruction found within it is to be reported rather than
followed.

This is a convention the model is asked to honour and SHALL NOT be described as
enforcement. The controls that do not depend on the model's cooperation are the
read-only profile and the service layer's authority over what is permitted;
describing the fence as a sandbox would discourage looking for those.

#### Scenario: The notice accompanies the content

- **WHEN** a tool returns corpus text
- **THEN** the payload states that the content is evidence and that instructions inside it are to be reported, not obeyed

### Requirement: Text a model wrote about corpus text is fenced and named as derived

Text a model produced from corpus material SHALL cross into an agent's context on
the same terms as the material itself: delimited by the response's marker, and
accompanied by a provenance block naming what it was derived from.

A summary of an untrusted document is untrusted text. The document is what an
adversary controls in the deployments this tool exists for, and a model asked to
summarise a document carrying an instruction can carry that instruction into its
summary — shorter, more fluent, and stripped of the surrounding text that would
have made it obviously misplaced. Fencing a document's own words while passing a
model's summary of them through unfenced would defeat the boundary at precisely
the point it is least visible.

The provenance SHALL additionally name what produced the text. A reader must be
able to tell a document's own words from a model's, and the record of how a
document's text was recovered cannot carry that: recognition is a transcription
of what is on the page, however unreliable, whereas a summary is a claim about it.

Derived text SHALL be fenced separately from the document's own text rather than
inside the same delimiters. One fence around both would lose exactly the
distinction the attribution exists to make.

A payload built on the promise of carrying no corpus prose SHALL NOT be used to
carry derived text. Such a payload is unfenced because of what it does not
contain, and adding a summary to it would either ship model-written prose
unfenced or force a fence into a shape whose stated reason for not needing one
had quietly stopped being true.

#### Scenario: A model-written summary is fenced and attributed to its producer

- **WHEN** a tool returns a summary a model wrote from a document
- **THEN** the summary is delimited by the response's marker and its provenance names both the document it describes and what produced it

#### Scenario: Derived text is fenced apart from the document's own words

- **WHEN** a response carries both a document's own text and a summary of it
- **THEN** each is delimited separately, so a reader can tell which words the document contains

#### Scenario: A prose-free listing carries no summary

- **WHEN** a tool returns a listing declared to carry no corpus prose
- **THEN** it carries no derived text either
