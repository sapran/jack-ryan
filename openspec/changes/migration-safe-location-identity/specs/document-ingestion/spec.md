## ADDED Requirements

### Requirement: A carried-forward location is spelled as a live one is

A location carried forward from an older schema SHALL be spelled by the same
join that spells a location recorded live. Reingesting evidence that has not
changed SHALL therefore record no further location for it and SHALL NOT report a
discovery, whether the record it is compared against was written by this build
or carried across from an older one.

Two spellings of one path SHALL be one location, and the earliest time either
was observed SHALL be the time the surviving location reports. That timestamp is
what the wholeness of the record is judged against, so keeping the later of the
two would present an old record as a young one.

Where an older representation spelled a path in a way no normalisation can
reverse — a source root of `/`, whose concatenation with a name is already its
own normal form — the carry-forward SHALL derive the location from the
representation that still says what was meant, rather than from the spelling
that lost it.

The representations a carry-forward reads from SHALL be preserved, not replaced.
They are the record as it was kept, and they are what makes a carry-forward's
own correctness checkable afterwards.

#### Scenario: A migrated archive entry is one location after reingest

- **WHEN** a store recorded before locations were keyed on the path alone holds an entry whose path was spelled with a redundant component, and the unchanged container is ingested again
- **THEN** one location is recorded for that entry, the run reports it as already known, and the record does not announce a discovery

#### Scenario: Two spellings of one place already recorded collapse

- **WHEN** a carried-forward store holds the same place under two spellings
- **THEN** one location is reported, and it carries the earlier of the two observation times

#### Scenario: A location observed under the filesystem root survives the carry-forward

- **WHEN** a store recorded a location whose ingested root was the filesystem root itself
- **THEN** the carried-forward location is the path a live observation of that file would record

#### Scenario: Two genuinely different places both survive the carry-forward

- **WHEN** a carried-forward store holds one document observed at two paths that differ
- **THEN** both locations are kept, because the paths they were observed at differ
