## 1. The reader dependency

- [ ] 1.1 Establish that no maintained pure-Python RAR5 reader exists and that libarchive's RAR5 reader is a clean-room BSD implementation carrying no unRAR code; verify the argument is recorded in `design.md` with the licence consequence — every unRAR-derived decoder is non-free in Debian, libarchive's is in main
- [ ] 1.2 Prove libarchive reads the real archives before writing any code; verify it against all 26 in the dump and record entries, bytes and failures, reconciling per-entry declared size against bytes actually streamed so a silent truncation cannot pass
- [ ] 1.3 Establish whether any archive in the dump is multi-volume, since libarchive cannot read those; verify by name and by header rather than by assumption
- [ ] 1.4 Add `libarchive-c` to `pyproject.toml` with the reason at the site — the binding is CC0, the library BSD-2-clause, neither disturbing AGPL-3.0-or-later; verify `uv pip install -e ".[dev]"` resolves and the pin is exact enough to be reproducible
- [ ] 1.5 Add `libarchive13t64` to the Dockerfile apt layer with `--no-install-recommends`, extending the existing comment rather than adding a second one; verify the package count and re-measure the image size from `docker images` rather than estimating it
- [ ] 1.6 Establish what `import libarchive` does on a host with no system library; verify it raises `AttributeError: undefined symbol`, not `ImportError` or `OSError`, and record why that forces a lazy import

## 2. The reader seam

- [ ] 2.1 Add `find_rar_reader()` to `containers.py` returning the libarchive version or `None`, importing inside the function and converting any exception; verify a test asserts it returns a value on this host and `None` when the import is made to fail
- [ ] 2.2 Add `RAR_UNAVAILABLE` as a single literal and `rar_status()` returning the version or that literal, mirroring `converter_status()`; verify the literal is defined once and both adapters read it, so the two cannot drift
- [ ] 2.3 Probe with `libarchive.ffi.version_number()` rather than a bare import; verify a comment says why — the import is what succeeds misleadingly

## 3. The extractor

- [ ] 3.1 Add `RarExtractor` to `containers.py` beside `ZipExtractor`, subclassing nothing, with `name = "rar"` and `suffixes = {".rar": "application/vnd.rar"}`; verify a test asserts the suffix appears in `FormatRouter().supported_suffixes()` and that the router selects it for a `.rar` path
- [ ] 3.2 Implement `extract()` to open its own `file_reader`, build the entry listing as the container's own text, and apply `_unsafe_reason` to each entry name, collecting refusals; verify a test asserts the listing text names every safe entry and that a traversing name lands in `refusals` rather than in the listing
- [ ] 3.3 Return `Extraction` with `is_container=True` and an `entries` count in metadata, matching `ZipExtractor`'s shape exactly; verify a test asserts `is_container` and the count, and that the container is stored despite having no text of its own beyond the listing
- [ ] 3.4 Raise `ExtractionError` naming the archive when the reader cannot open it, covering the encrypted case; verify a test with an encrypted fixture asserts the message names encryption and that no document with zero children is stored
- [ ] 3.5 Raise `ExtractionError` naming multi-volume explicitly rather than letting libarchive's "Too small block encountered" surface; verify a test asserts a `.partN.rar` name is refused with a message an operator can act on
- [ ] 3.6 Raise `ExtractionError` naming `libarchive` and the remedy when the reader is unavailable; verify a test with the import made to fail asserts the message names the library, and that the ingest run continues
- [ ] 3.7 Implement `iter_children()` as a generator opening its own `file_reader`, applying `_unsafe_reason` and skipping non-regular entries, accumulating each entry's blocks and stopping at `MAX_ENTRY_BYTES + 1`; verify a test asserts an entry over the bound is excluded on bytes read rather than on declared size
- [ ] 3.8 Yield `Child(name=entry.pathname, data=...)` one entry at a time, reading each entry's blocks before advancing the cursor; verify a test asserts the generator is not materialised — that consuming one child does not require reading the whole archive — and that abandoning it partway does not raise

## 4. Registration

- [ ] 4.1 Add one lazy import and one `RarExtractor()` entry to `default_extractors()`, positioned with the other containers and before the document engine; verify a test asserts the registry order places it before `DoclingExtractor`
- [ ] 4.2 Add a `.rar` row to the router-selection table in `tests/test_extraction.py`; verify the table asserts the extractor `name`, not just that something accepted it

## 5. The operator surfaces

- [ ] 5.1 Add a `rar` key to the `jackryan status` capability payload from `rar_status()`, with the comment saying why it is reported rather than enforced; verify a test asserts the key is present
- [ ] 5.2 Add the same key to `GET /health` from the same function; verify a test asserts both surfaces report the identical value for one host, since two agreeing definitions is one definition too many

## 6. Verification

- [ ] 6.1 Build synthetic RAR fixtures without committing binary case material; verify the approach is recorded — RAR compression is proprietary and no writer is available, so fixtures are either committed minimal synthetic archives or generated, and whichever is chosen is stated with its reason
- [ ] 6.2 Show every new test fails without the change: reintroduce the gap, watch each go red with the reported symptom, restore; verify the count of tests shown red equals the count added
- [ ] 6.3 Run `pytest -q`; verify the full suite is green, which is the same gate CI runs, and that the pre-existing `test_a_timeout_kills_the_whole_converter_tree_not_just_the_launcher` flake is the only deselection
- [ ] 6.4 Run `openspec validate --all --strict`; verify it is clean and that the ADDED requirement titles collide with no published requirement in `container-extraction`
- [ ] 6.5 Grep the changed files for the public-repo leak patterns; verify no real filename, document title, hostname or path fingerprint entered any tracked file

## 7. Proof on the real corpus

- [ ] 7.1 Ingest the 26 real archives into the existing casefile; verify the run completes and record ingested, failed and refused counts
- [ ] 7.2 Reconcile the result against the measurement taken in 1.2; verify the stored descendant count equals the 406 readable entries minus what the router legitimately refuses, and that the arithmetic closes exactly rather than approximately
- [ ] 7.3 Verify the encrypted archive is a failed document with a reason, not a stored container with zero children
- [ ] 7.4 Verify search reaches text that exists only inside an archive, and that a citation resolves through the containment path to the archive it came from
- [ ] 7.5 Verify `integrity_check`, chunk/vector/FTS row parity and zero orphans after the ingest, as the previous reingest did
