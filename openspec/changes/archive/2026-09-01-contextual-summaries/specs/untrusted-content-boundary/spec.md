## ADDED Requirements

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
