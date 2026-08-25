## Context

See proposal.md § Why for motivation.

Three properties of the code as it stands shape everything below.

`Extraction` is a frozen dataclass carrying `text`, `media_type`, `extractor`,
and flat metadata. It has no notion of a child, so growing one is the seam this
change turns on.

`IngestionService._ingest_one` reads bytes from a `Path`, hashes them, routes,
extracts, upserts, and rebuilds chunks. Every step assumes a file that exists on
disk. A document produced by expansion has no such file.

The store deletes chunks through a single `AFTER DELETE` trigger on `chunks`
that removes the matching FTS and vector rows. That trigger exists because M1
shipped a delete path which orphaned them, and because SQLite reuses rowids the
next ingest anywhere in the corpus died permanently. Any new delete path has to
go through it rather than around it.

Constraint on verification: this environment cannot reach model weights, so a
design that needs one cannot be shown to work here. Nothing in this slice needs
one — that is why it is the first slice, not an accident.

## Goals / Non-Goals

**Goals:**

- One recursion, driven by the ingestion service, so format support is a
  property of the registry rather than of nesting depth.
- Guards that bound the machine's exposure to a crafted archive, expressed as a
  budget that is spent rather than a set of independent limits.
- A containment path that an analyst can follow by hand, reaching the agent
  through the provenance block that already exists.

**Non-Goals:**

- Parallel expansion. Ingestion is single-threaded today; making recursion
  concurrent is a separate change with its own locking argument.
- Preserving container structure as anything richer than parentage. Folder
  hierarchy inside an archive is captured by the containment path, not by a
  directory model.
- Streaming extraction. Entries are materialised whole; a bounded file size is
  what keeps that safe.

## Decisions

### Children are materialised to a temporary directory, not passed as bytes

An extractor returns children as `(name, bytes)`. The pipeline writes each into
a per-ingest temporary directory and routes it **by path**, exactly as for a
file the analyst named.

*Why.* The router selects on the filename, `_check_readable` enforces size and
symlink rules on a path, and the Docling engine wants a real file. Passing bytes
through instead means a parallel routing path, a parallel size check, and a
temporary file inside the extractor anyway — three places to disagree about what
is safe to read.

*Alternative considered:* extend the `Extractor` protocol to accept
`(name, bytes)`. Rejected for this slice: it changes every existing extractor's
signature to serve the nested case, and the checks that make a path safe would
have to be reimplemented against bytes. Worth revisiting if temporary-file I/O
shows up as a real cost.

*Consequence:* the temporary directory is the extraction root for a nested
entry, so the existing "must not resolve outside the root" check gives the
archive-traversal guard for free rather than as a second implementation.

### Expansion is a work queue, not recursion

`ingest` maintains a queue of pending work items, each carrying its path, its
parent document id, its depth, and its containment path. Items are processed
breadth-first until the queue drains or the budget is exhausted.

*Why.* Depth is then a number on an item rather than a stack, so the depth bound
is a comparison instead of a recursion limit; a partially-expanded ingest can
report precisely what it did not reach; and the budget is a single mutable
object every item spends from, rather than a value threaded through recursive
calls where one missed hand-off silently uncaps it.

*Alternative considered:* direct recursion with a depth parameter. Rejected —
it makes "report what was refused" awkward and puts an attacker-controlled
number in charge of the Python stack.

### One budget object, spent, not three independent limits

`ExpansionBudget` carries remaining depth allowance, remaining descendant count,
and remaining extracted bytes; it is consumed as work proceeds and reports which
bound stopped it.

*Why.* The three limits are not independent — a deep archive and a wide one and
a highly-compressed one are the same attack with different shapes. One object
that reports *which* bound it hit is also what lets the ingest report say
something an analyst can act on rather than "incomplete".

The byte bound counts bytes produced by extraction, not bytes read. That is the
distinction that makes it a zip-bomb defence: the whole point of the attack is
that the bytes read are small.

Defaults live as module constants beside `MAX_FILE_BYTES`, which is where the
existing operational limit lives. They are deliberately **not** in the
`contract:` block: changing them does not invalidate a corpus, and putting them
there would make tuning a limit a reason the store refuses to open.

### Identity of an expanded document is content plus containment path

A directly ingested document keeps today's rule — hash of its bytes. An expanded
document is identified by its extracted bytes together with the path it was
found at.

*Why.* The alternative, deduplicating expanded documents by content alone, means
the same attachment on two messages becomes one document with one parent. That
the same file was attached to two different messages is frequently the finding;
one parent silently discards the second link.

*Alternative considered:* one document with many parents, via a join table.
Correct, and more faithful — but it makes ancestry a graph, makes deletion
ambiguous (a child with two parents surviving one parent's deletion), and buys
an exactness this slice does not need. Recorded as the upgrade path if duplicate
storage becomes a real cost.

*Preserved:* reingesting a container yields the same paths, hence the same
identities, hence the same document ids. Reingest stability — the property
bookmarks and citations depend on — survives.

### Deletion collects descendants explicitly, then deletes through the existing path

Deleting a document resolves its descendant ids with a recursive CTE, then
deletes them through the same code that already deletes a document's chunks.

*Why.* The tempting alternative is a self-referencing foreign key with
`ON DELETE CASCADE`. It requires `PRAGMA foreign_keys=ON` to be set on every
connection, and whether the existing `AFTER DELETE` trigger on `chunks` fires
for cascade-deleted rows depends further on `recursive_triggers`. Two pragmas
have to be right, on every connection, or the corpus silently accumulates
orphaned FTS and vector rows — which is precisely the M1 defect that made the
next ingest anywhere in the corpus fail permanently. An explicit collect-then-
delete depends on no pragma and goes through the one path already known to clean
up.

### A directory is a traversal, not a document

A folder tree keeps today's walk. Files found in it are ingested directly, with
their relative path recorded as their containment path. No document is created
for a directory.

*Why.* A document's identity is the hash of its content, and a directory has no
content — there are no bytes to hash. Creating a document for one would mean
inventing an identity from its path, which is the one thing the identity rule
exists to prevent. An archive is different: it is a file, it has bytes, and
hashing it is what makes reingesting it stable.

*Consequence:* a containment path may begin with directory names that are not
themselves documents. That is the honest description of where the file was
found, which is what the path is for.

### Mail headers go into the extracted text, not only into metadata

A message's sender, recipients, date, and subject are rendered at the top of its
extracted text as well as kept as metadata.

*Why.* Chunks are what search retrieves and what the agent reads. A sender held
only in a metadata column is invisible to both. The cost is that headers are
embedded along with the body, which is acceptable and is what makes "who sent
this" answerable at all before facets exist.

## Risks / Trade-offs

**A container of many small entries multiplies document count by orders of
magnitude** → The descendant-count bound caps it per ingest, and listing can
exclude expanded children so an inventory stays readable. Accepted:
`casefile_statistics` becomes more expensive, and the spec now requires a count
to state what it counted.

**Duplicate storage for a file attached to many messages** → Accepted
deliberately, per the identity decision. The join-table upgrade is recorded
above if it becomes a real cost.

**Temporary-file I/O for every nested entry** → Bounded by the same byte budget
that bounds everything else, and the directory is removed when the ingest ends.
The risk is disk pressure during a large ingest, not unbounded growth.

**`extract-msg` is a third-party parser reading attacker-controlled input** →
Its licence is checked before adoption (task 1.4), it runs behind the same size
bound as every other extractor, and a failure to parse one message is an entry
failure rather than an ingest failure. MSG is the one format here without a
standard-library reader; if the licence or robustness check fails, it drops from
the slice and EML/MBOX still cover mail exports.

**A schema change makes an existing corpus unreadable** → Real, and accepted:
no corpus outside development exists. The contract fingerprint already refuses a
mismatched store rather than corrupting one, so the failure mode is a clear
refusal at open.

**Partial ingests become normal rather than exceptional** → The report has to
carry that honestly: which entries were refused, which bound was hit, and what
was stored anyway. A report that says "done" after stopping at a budget is worse
than a failure.

## Migration Plan

Schema version advances; the store refuses a corpus built under the previous
version at open, with a message naming the mismatch. Rollback is checking out
the previous revision — a corpus created under the new schema is likewise
refused by the old store rather than misread. Development corpora are rebuilt by
reingesting, which is the same operation this change is about.
