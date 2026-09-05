## Context

Two ingestion paths hand a file to a delegate under a name other than the one it
has on disk: content routing, when the registry cannot name a file and its bytes
can; and legacy Office, when a binary format has to be converted before anything
can read it. They had converged on the same shape independently, which is why
the duplication was invisible — nothing looked copied, because nothing was.

## Goals / Non-Goals

**Goals.** One owner per signature. One implementation of the scratch-and-
delegate shape. No observable change.

**Non-Goals.** Unifying the temp prefixes or the error strings. Reconciling how
the two paths rebuild their `Extraction`. Touching the routing decisions
themselves.

## Decisions

### The signatures live where every other signature lives

`sniffing.py` already owns the whole signature table and derives
`producible_suffixes()` from it, so a signature added there enters that set
without anyone remembering. Putting the three container magics anywhere else
would have created a second place to look.

`legacy_office` imports them **by name** — `from .sniffing import _OLE2_MAGIC,
...` — rather than referencing `sniffing._OLE2_MAGIC` inline. That is not style:
sixteen tests read `legacy_office._OLE2_MAGIC`, and the import form is what keeps
that attribute bound. Watched failing by switching to the module form, which
turns all sixteen into `AttributeError`.

RTF's signature was a literal inside the `_MAGIC` table, so "move it so sniffing
owns it" was really "lift it into a named constant and reference it from the
table". Saying which of those is happening matters, because the table is what
`producible_suffixes()` reads.

### `SCRATCH_STEM` goes to `extractors`, not to either caller

`router` and `legacy_office` both import `extractors`, and `router` importing
`legacy_office` would close a cycle — `extractors` already imports
`legacy_office` lazily. So `extractors` is the only home that costs nothing.
`router` re-exports the name, because that is where `tests/test_content_routing.py`
imports it from.

The two callers spelled the same name differently: `f"{SCRATCH_STEM}{suffix}"`
with a dotted suffix, and `f"source.{target}"` with an undotted target. Both
produce `source.xlsx`, verified rather than assumed — and this is the one place
where getting it wrong would be quiet, because `router._resolve` builds the same
name to ask an extractor whether it `accepts` the file. A mismatch there would
mean the extractor chosen is not the one handed the file.

### The helper takes a producer, not a path

`deliver_via_scratch_directory(path, *, prefix, produce, delegate, read_as)`.

`produce` is a callable receiving the directory, because the two callers do
different work inside it. Content routing copies one file in. Legacy Office may
instead run LibreOffice, which writes an output directory and a per-call profile
directory beside the result. A helper taking a finished source path could serve
only the first, and the second would have kept its own copy of the teardown —
which is the half that has actually gone wrong before.

`docs/handover.md` records two defects found in exactly this teardown: a
`mkdtemp` outside every `try`, and a converter still writing into the directory
after the `finally` had removed it. That history is the argument for one
implementation, and it is why the helper's docstring carries it.

`tempfile.mkdtemp` is called through the module rather than imported by name, so
a test substituting `tempfile.mkdtemp` still observes what this allocates.

### The legacy path decides before it allocates

The branch on the file's first eight bytes now yields a `(lineage, produce)`
pair, chosen before any directory exists. Two consequences, one intended and one
free: the lineage and the producer can no longer disagree, because one statement
sets both; and a file that is neither OLE2 nor OOXML is refused without a scratch
directory having been created and removed for it.

## Risks / Trade-offs

**A shared teardown is a shared blast radius.** One bug in
`deliver_via_scratch_directory` now reaches both paths. That is the trade, and it
is the right one here: the failure mode this replaces was two teardowns drifting,
and this project has already found two defects in that code. Both suites test it
independently and by **opposite** strategies — `test_content_routing.py` globs
the temp root, `test_legacy_office.py` patches `mkdtemp` and watches the actual
directory — so one implementation now has two unrelated checks on it. Removing
the `finally` fails four tests across both files.

**The producer callable is indirection.** `_converted_to` and `_copied_to`
return closures, which is one more hop than a straight call. Named methods with
docstrings rather than inline lambdas, so the hop is legible.

**The result rebuild is still duplicated, deliberately.** `router` uses
`replace`; `legacy_office` builds a fresh `Extraction` that overrides
`media_type` on purpose and drops `is_container` by omission. Unifying them
would be a behaviour change — `is_container` would start coming from the
delegate — inside a change that claims to have none. Recorded in
`docs/implementation-notes.md` instead.
