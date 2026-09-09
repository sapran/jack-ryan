## ADDED Requirements

### Requirement: A document is stored together with where it was observed

Storing a document SHALL write, in the same transaction and through the same
port call, the record of the location its bytes were observed at.

This is the rule already stated for data derived from a chunk, applied to the
one other place where a second write decides whether the first is honest.
Whether a document's location record may be read as whole is answered from that
record itself, so a document committed without its first observation asserts a
history it does not have. A later observation from somewhere else then supplies
the only row the record holds, and the document reads as though that one place
were the whole story — which is a false finding about the evidence, not a
missing one.

The port SHALL NOT offer a way to store a document without saying where it was
observed. Not a second method called next, and not an optional parameter: for
the reason the chunk rule gives, a seam that can be used in the wrong order
eventually is, and an optional one is used without eventually.

A failure while writing SHALL leave neither the document nor its observation, so
a document without the record that describes it is not a reachable state.

#### Scenario: A document and its observation are one write

- **WHEN** a document is stored
- **THEN** the location it was observed at is written in the same transaction, through the same call

#### Scenario: A failed write leaves no document without its record

- **WHEN** storing a document together with its observation fails partway
- **THEN** neither the document nor the observation remains

#### Scenario: The port offers no way to store a document without its observation

- **WHEN** the port's document-storing calls are inspected
- **THEN** every one of them requires the observed location, with no default
