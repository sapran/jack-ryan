# Tasks

## 1. Pin the corpus-coupled dependencies

- [x] 1.1 Pin `fastembed` and `docling` to exact versions in `pyproject.toml`, matching what is installed today (`fastembed==0.8.0`, `docling==2.122.0`); verify `uv pip install -e ".[dev]"` resolves to exactly those
- [x] 1.2 Leave a comment at the pins saying why they are exact — `fastembed` is in the corpus fingerprint, `docling` output becomes the chunks — so a later cleanup does not loosen them back

## 2. The contract declares the embedding library

- [x] 2.1 Add `embed_library` to `DEFAULT_CONTRACT` and to the `Contract` dataclass, defaulting to the installed `fastembed` version in `<distribution>==<version>` form; verify a test asserts the default matches what is installed
- [x] 2.2 Include `embed_library` in `fingerprint()`; verify a test asserts two contracts differing only in that value produce different fingerprints
- [x] 2.3 The spec's "every contract value is consumed" scenario turned out to have no test at all — written now: it asserts the `Contract` fields and `DEFAULT_CONTRACT` keys agree and that every one appears in the fingerprint, which is the omission that let `embed_library` be missed in the first place
- [x] 2.4 Document the key in `config.yaml.example` with a one-line note that changing it forces a reingest

## 3. The declaration is verified against reality

- [x] 3.1 Add a helper that reads the installed distribution version and compares it to the declared `embed_library`, raising `ConfigError` naming both versions on mismatch, and naming the distribution when the version cannot be read at all; verify unit tests cover match, mismatch, and unreadable
- [x] 3.2 Call it during configuration load, alongside the unknown-profile and unresolved-placeholder checks; verify a test asserts load fails and the message names both versions
- [x] 3.3 Call it again in the embedder load path so every producer of vectors crosses it, not only a full boot; verify a test constructs an embedder directly under a mismatched contract and asserts it refuses
- [x] 3.4 Verify the refusal is a typed error from `errors.py` and that no adapter-specific exception escapes the service layer

## 4. Prove the guard actually guards

- [x] 4.1 Reintroduce the defect: build a store under one `embed_library`, then open it under another, and verify the store refuses rather than appending — the test must be seen to fail when the value is removed from `fingerprint()`
- [x] 4.2 Verify the deterministic embedder path is unaffected, since it is selected explicitly and produces no model vectors
- [x] 4.3 Verify a fresh corpus builds end to end under the declared version with no behaviour change other than the new fingerprint

## 5. Records

- [x] 5.1 Update `docs/handover.md`: the defect moves from "confirmed, unfixed" to fixed, and the recorded 6/6 run is annotated as having been built on `fastembed==0.8.0` mean-pooled vectors, now refused until reingested
- [x] 5.2 Remove the fingerprint entry from `docs/implementation-notes.md`, leaving the two script findings that remain open
- [x] 5.3 Verify `pytest` and `openspec validate --all --strict` are both clean before pushing
