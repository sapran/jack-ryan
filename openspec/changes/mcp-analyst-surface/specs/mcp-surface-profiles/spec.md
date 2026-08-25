## ADDED Requirements

### Requirement: A profile decides which tools the surface advertises

The surface SHALL support named profiles — `readonly`, `analyst`, and `admin` —
each with an explicit allow-set of tool names. Tools outside the selected
profile SHALL NOT be advertised.

The allow-set SHALL be explicit rather than derived from a tool's properties, so
that a tool added later is hidden until it is admitted deliberately.

#### Scenario: Only the profile's tools are advertised

- **WHEN** the surface is built under a profile
- **THEN** exactly the tools in that profile's allow-set are advertised

#### Scenario: A new tool is hidden until admitted

- **WHEN** a tool is defined but named in no allow-set
- **THEN** no profile advertises it

### Requirement: An unrecognised profile yields the narrowest surface

A profile name that is not recognised SHALL resolve to the narrowest available
surface, never the widest. A configuration typo must cost tools rather than
grant them.

#### Scenario: An unknown profile name is narrowed, not widened

- **WHEN** the surface is built under an unrecognised profile name
- **THEN** it advertises the narrowest profile's tools

### Requirement: Every tool is stamped by its worst reachable mode

Each tool SHALL be annotated with whether it only reads, whether it may modify,
and whether it reaches beyond the instance — recorded in one table rather than
at each definition, so the whole surface is reviewable at once.

A tool absent from that table SHALL be a failure rather than silently taking a
default, since an unstamped tool would be advertised without its risk described.

#### Scenario: Read-only tools are stamped as such

- **WHEN** the advertised tools are inspected under the read-only profile
- **THEN** each is annotated as read-only

#### Scenario: An unstamped tool is a failure

- **WHEN** a tool exists that the annotations table does not name
- **THEN** building the surface fails rather than advertising it unstamped
