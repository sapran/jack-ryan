## Why

The contract fingerprint exists to stop a corpus built under one set of rules
from being appended to or queried under another. It covers chunk size, overlap,
embedder name and dimensions — but not the version of the library that produces
the vectors, and that library changed pooling strategy between releases.

`fastembed` 0.5.1 embedded `intfloat/multilingual-e5-large` with CLS pooling;
0.8.0 uses mean pooling. `pyproject.toml` pins `fastembed>=0.4`, which is not a
pin at all. A corpus ingested under one and queried under the other therefore
carries **the same fingerprint and incompatible vectors**: the guard passes,
nothing errors, and retrieval quietly degrades. That is precisely the failure
the guard exists to prevent, and it is the one class of corruption no later
check can detect — the vectors look well-formed and are the right width.

This is observed, not predicted. A clean install against the current pins
resolves `fastembed` to 0.8.0 and emits the pooling warning at every load, and
the 6/6 verification run recorded in `docs/handover.md` was built on mean-pooled
vectors that nothing records. Fixing it before a real corpus exists is nearly
free; afterwards it forces a full reingest.

## What Changes

- The contract gains an `embed_library` value naming the embedding library and
  its exact version (for example `fastembed==0.8.0`), and the fingerprint
  covers it. **BREAKING**: the fingerprint string changes, so any corpus built
  before this change is refused at boot and must be reingested. That is the
  correct outcome — those corpora have an unrecorded pooling strategy.
- Startup validates the declared `embed_library` against the version actually
  installed, and a mismatch is **fatal and named**, in the same manner as an
  unknown profile or an unresolvable `${VAR}`. A declared value that does not
  match reality would reintroduce the same silent divergence one level up.
- `fastembed` and `docling` are pinned to exact versions in `pyproject.toml`,
  so a rebuild cannot silently move either.
- The extraction library is deliberately **not** added to the fingerprint; see
  `design.md` for why the two cases differ in kind, not just in degree.

## Capabilities

### New Capabilities

None. This closes a gap in capabilities that already exist.

### Modified Capabilities

- `layered-configuration`: the contract declares the embedding library version;
  the fingerprint covers it; a declared-versus-installed mismatch is fatal at
  startup rather than tolerated.
- `chunking-and-embedding`: the embedder that "fails loudly" now also fails
  when the installed embedding library is not the one the corpus was built
  under, because a pooling change is indistinguishable from correct output at
  every later checkpoint.

## Impact

- `src/jackryan/config.py` — the `Contract` dataclass, `DEFAULT_CONTRACT`, and
  `fingerprint()`; a new startup validation that reads the installed
  distribution version.
- `src/jackryan/embedding/` — the load path asserts the declared library, so
  the failure surfaces where the vectors are produced rather than only at boot.
- `pyproject.toml` — exact pins for `fastembed` and `docling`.
- `config.yaml.example` and `.env.example` — the new contract key documented.
- Every existing corpus — refused until reingested. No corpus outside
  development is known to exist, which is why this is proposed now.
- `docs/handover.md` and `docs/implementation-notes.md` — the recorded defect
  moves from "unfixed" to fixed, and the 6/6 run is annotated with the library
  version its vectors were built under.
