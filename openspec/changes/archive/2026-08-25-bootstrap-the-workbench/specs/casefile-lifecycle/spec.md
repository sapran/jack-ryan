## ADDED Requirements

### Requirement: A casefile is the unit of scoping

A casefile SHALL carry a stable identifier, a unique slug, a title, an optional
description, and creation and update timestamps. Every document, tag, note, and
report added in later milestones SHALL belong to exactly one casefile.

The identifier SHALL be stable for the life of the casefile, so that references
held elsewhere stay valid across renames.

#### Scenario: A created casefile carries the required fields

- **WHEN** a casefile is created with a title
- **THEN** it has an id, a slug, the title, timestamps, and an 8-character short id derived from the id

### Requirement: Slugs are predictable handles

A slug SHALL consist of lowercase alphanumerics separated by single hyphens.
When no slug is supplied it SHALL be derived from the title. A supplied slug
that differs only in case SHALL be normalised rather than rejected, because
such input has exactly one sensible interpretation; a slug that is malformed in
any other way SHALL be rejected.

A slug SHALL be unique within an instance, and a duplicate SHALL be reported as
a conflict.

#### Scenario: A slug is derived from the title

- **WHEN** a casefile is created with the title `Port Authority Contracts 2021` and no slug
- **THEN** its slug is `port-authority-contracts-2021`

#### Scenario: Mixed case is normalised

- **WHEN** a casefile is created with the slug `MixedCase`
- **THEN** its slug is `mixedcase`

#### Scenario: A malformed slug is rejected

- **WHEN** a slug contains spaces, underscores, doubled hyphens, or leading or trailing hyphens
- **THEN** creation fails with a validation error

#### Scenario: A duplicate slug is a conflict

- **WHEN** a casefile is created with a slug already in use
- **THEN** creation fails with a conflict error

### Requirement: A reference resolves by id, short id, or slug, and never guesses

Reference resolution SHALL accept a full identifier, an identifier prefix of at
least 8 characters, or a slug, tried in that order. Exact identifier and slug
lookups SHALL be tried before prefix matching, so a slug shaped like a prefix
still resolves to the casefile it names.

A prefix matching more than one casefile SHALL raise an ambiguity error naming
the count and some of the matches. It SHALL NOT return the first match:
returning the wrong casefile with no signal is worse than an error the caller
can act on.

#### Scenario: All three reference forms resolve

- **WHEN** a casefile is looked up by its full id, its 8-character short id, or its slug
- **THEN** the same casefile is returned in each case

#### Scenario: An ambiguous prefix is refused

- **WHEN** an identifier prefix matches more than one casefile
- **THEN** resolution fails with an ambiguity error rather than returning a match

#### Scenario: An unknown reference is not found

- **WHEN** a reference matches no casefile
- **THEN** resolution fails with a not-found error

### Requirement: Updates preserve creation time and listing is newest first

An update SHALL change only the fields supplied, SHALL preserve `created_at`,
and SHALL advance `updated_at`. Listing SHALL return casefiles newest first.

#### Scenario: A partial update leaves other fields intact

- **WHEN** a casefile's title is updated
- **THEN** its slug and description are unchanged, `created_at` is unchanged, and `updated_at` has advanced
