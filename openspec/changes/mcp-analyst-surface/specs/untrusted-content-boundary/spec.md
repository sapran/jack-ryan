## ADDED Requirements

### Requirement: Corpus text crosses into an agent's context fenced and attributed

Any corpus-derived text a tool returns SHALL be delimited by a marker generated
per response, and SHALL carry a provenance block naming the casefile, the
document, and the position it came from.

The marker SHALL be generated per response rather than fixed, because document
text and document metadata are attacker-controlled in the deployments this tool
exists for, and a fixed marker can be reproduced inside a document.

#### Scenario: Returned corpus text is fenced and attributed

- **WHEN** a tool returns text taken from a document
- **THEN** the text is delimited by a per-response marker and accompanied by provenance naming its casefile, document, and position

#### Scenario: Two responses do not share a marker

- **WHEN** two responses containing corpus text are produced
- **THEN** their markers differ

#### Scenario: Document text cannot forge the fence

- **WHEN** a document contains text imitating a fence marker
- **THEN** the marker used for that response is still unique to it, and the imitation does not terminate the fence

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
