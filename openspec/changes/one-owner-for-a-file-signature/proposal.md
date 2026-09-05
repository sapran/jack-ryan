## Why

Two modules asked the same question about the same bytes, and each kept its own
copy of the answer.

`sniffing.py:93-94` and `legacy_office.py:51-53` both declared `_OLE2_MAGIC` and
`_ZIP_MAGIC`, under identical names, with no import between them. RTF's
signature was a third case of the same thing: named `_RTF_MAGIC` in
`legacy_office`, and buried as a literal inside `sniffing`'s `_MAGIC` table.

The two modules ask narrower and wider versions of one question — "what is this
file" and "is this file under a legacy name actually the container that name
implies" — but they ask it of the same bytes, and two spellings drifting apart
is a silent defect: a file would route one way and convert another.

And a comment claimed a sharing the code did not have. `router.py:47` said the
scratch copy's name was "the same argument and **the same constant** as
`legacy_office._copy_as_target`", while that function hardcoded `f"source.{target}"`
(`legacy_office.py:254`). The comment described a shared module that did not
exist.

Underneath that comment sat the real duplication: both paths make a scratch
directory, put a file in it under a name a delegate will accept, delegate,
relabel the failure with the operator's filename, and remove the directory
whatever happened. Written twice, with the mkdtemp guard and the two `except`
clauses character-identical.

## What Changes

**Current behaviour.** Three byte-string signatures with two owners each, a
constant claimed to be shared and not, and one scratch-and-delegate shape
implemented twice.

**Desired behaviour.**

- **`sniffing.py` owns the three signatures**, including RTF's, lifted out of
  the `_MAGIC` table into a named constant and referenced there.
  `legacy_office` imports them by name, so `legacy_office._OLE2_MAGIC` still
  resolves — sixteen tests read it that way.
- **`SCRATCH_STEM` moves to `extractors.py`**, which `router` and
  `legacy_office` both already import and neither may import from the other.
  `router` re-exports it, which is where the tests read it from. The two paths
  spelled the same name differently — one appending a dotted suffix, the other
  interpolating an undotted target — and now produce it from one constant.
- **`deliver_via_scratch_directory` in `extractors.py`** holds the shared shape.
  The caller supplies a `produce` callable rather than a finished path, because
  the two do genuinely different work inside that directory: one copies a file
  in, the other runs a converter that writes an output directory and a private
  LibreOffice profile beside the result.
- **The legacy path decides its lineage and its producer before any directory
  exists.** A file this extractor will refuse now costs no scratch directory at
  all, and the two outcomes cannot drift apart the way they could when each
  branch assigned them separately.

**Deliberately not in scope.** Unifying the two temp-directory prefixes —
`tests/test_content_routing.py` globs `jackryan-routed-*` to prove cleanup and
separately asserts that string never reaches an error message, so they are
load-bearing in opposite directions and stay a parameter. Reconciling how the
two paths rebuild their `Extraction`; see Impact.

## Impact

- Affected specs: **none**, established by falsification. Grepping
  `openspec/specs/` for "scratch", "copy" and the signature constants returns
  nothing; `document-ingestion` covers content routing behaviourally — which
  file is read as what — and says nothing about how the file reaches the
  extractor. Shipped with `skip_specs: true`.
- Affected code: `src/jackryan/ingestion/sniffing.py`,
  `legacy_office.py`, `router.py`, `extractors.py`
- Nothing observable changes: same routing decisions, same lineage strings, same
  error messages, same prefixes. One behaviour does improve incidentally — a
  legacy file that is neither OLE2 nor OOXML no longer has a scratch directory
  created and removed before it is refused.
- One test moves: `tests/test_legacy_office.py` patched `legacy_office.tempfile`,
  and now patches `extractors.tempfile`, which is where the directory is
  allocated. It would have kept passing either way — `legacy_office.tempfile`
  was the global module object, so the substitution reached the helper anyway —
  and that is exactly why it was repointed: a test passing for a reason its
  reader cannot see is worse than one that fails.
- **Recorded, not fixed:** the two paths still rebuild their result differently.
  `router` uses `dataclasses.replace`, carrying every field the delegate set;
  `legacy_office` builds a fresh `Extraction`, which overrides `media_type` to
  the legacy type deliberately and drops `is_container` by omission. Latent only
  — neither delegate is ever a container — but it is a real difference and it is
  in `docs/implementation-notes.md` rather than in this diff.
