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

A port method returning a value without its field names SHALL be treated as a
row rather than a domain object. One reason covers every shape this takes, and it
is the whole reason: a value offered without its field names is a value a caller
can misread, and a rename or a reordering of it is silent.

An untyped mapping is one such shape. The field names then live in strings at
every call site, where a rename is silent and a typo surfaces as a lookup failure
at whichever surface happens to read it first.

An unnamed tuple is the other, and SHALL be refused on the same ground rather
than tolerated as merely terse. It carries no field names at all, so each caller
supplies its own: a value that means one thing where it is returned acquires its
name only where it is unpacked, and two call sites are free to name it
differently. Reordering two fields of the same type then changes what every
caller reads while changing nothing a caller could be asked to update, and no
lookup fails to mark the moment it happened.

This SHALL be checkable too, rather than left to review, for the reason the two
halves above are: the port's own declared return types SHALL be asserted to name
their fields, so that the next method to return a nameless pair is refused when
it is written rather than when a caller misreads it.

#### Scenario: The service layer holds no SQL

- **WHEN** the service layer is inspected
- **THEN** it calls only port methods, and contains no SQL statements

#### Scenario: No adapter reaches a store

- **WHEN** the adapter modules are inspected
- **THEN** none of them accesses a store, whether directly or through a name bound to one

#### Scenario: The port hands back domain objects

- **WHEN** a port method reports counts or sizes describing stored data
- **THEN** it returns a typed domain object whose fields are named, rather than a mapping keyed by strings

#### Scenario: The port hands back no unnamed tuple

- **WHEN** the port's declared return types are inspected
- **THEN** none of them is a tuple, so no value the port returns is named for the first time at a call site
