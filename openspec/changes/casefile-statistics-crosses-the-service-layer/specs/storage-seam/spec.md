## MODIFIED Requirements

### Requirement: All persistence goes through the storage port

`StorePort` SHALL be the single persistence boundary. It SHALL speak in domain
objects rather than rows, and SHALL contain no validation — rules belong in the
service layer so that every adapter inherits them.

The service layer SHALL NOT contain SQL, and no adapter SHALL reach a store
directly.

Both halves SHALL be checkable rather than left to review. An adapter that holds
a store is not distinguishable by reading one call site — it looks like any other
delegation — and the composition root's own type declaration is what makes it
possible: a `Context` exposing the concrete store rather than the port permits
the reach without even a type error. The port therefore SHALL be what the
composition root declares, and the absence of such a reach SHALL be asserted.

A port method returning an untyped mapping SHALL be treated as a row rather than
a domain object. The field names then live in strings at every call site, where
a rename is silent and a typo surfaces as a lookup failure at whichever surface
happens to read it first.

#### Scenario: The service layer holds no SQL

- **WHEN** the service layer is inspected
- **THEN** it calls only port methods, and contains no SQL statements

#### Scenario: No adapter reaches a store

- **WHEN** the adapter modules are inspected
- **THEN** none of them accesses a store, whether directly or through a name bound to one

#### Scenario: The port hands back domain objects

- **WHEN** a port method reports counts or sizes describing stored data
- **THEN** it returns a typed domain object whose fields are named, rather than a mapping keyed by strings
