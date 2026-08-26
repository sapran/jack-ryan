# Tasks

## 1. Corpus identity is composed, not assumed

- [x] 1.1 Add `corpus_fingerprint(contract, embedder_name)` beside `Contract.fingerprint()`, appending the embedder identity; verify a test asserts the same contract under `model` and under `deterministic` yields two different values
- [x] 1.2 Document `EmbedderPort.name` as load-bearing — it decides whether a corpus opens, so two implementations must never share one and renaming one invalidates its corpora
- [x] 1.3 Verify `Contract.fingerprint()` keeps its own meaning and its existing tests still pass unchanged, since it is now a component rather than the whole

## 2. The composition root records it

- [x] 2.1 Reorder `build_context` to construct the embedder before `store.initialize`, and pass `corpus_fingerprint(...)`; verify the existing app and store tests pass unchanged
- [x] 2.2 Verify an injected embedder (`build_context(config, embedder=...)`) contributes its own `name`, since that is the path the tests use
- [x] 2.3 Confirm constructing `ModelEmbedder` before opening the store is still cheap and cannot fail — it defers loading to first use — because the new ordering depends on it

## 3. Prove the guard actually guards

- [x] 3.1 Reproduce the defect end to end: ingest into one data dir under the deterministic embedder, reopen under the model embedder, and verify the store now refuses; the test must be seen to fail when the embedder is dropped from the identity
- [x] 3.2 Verify the refusal names both the recorded and the configured value
- [x] 3.3 Verify a corpus reopened under the *same* embedder still opens, so the guard is not simply refusing everything

## 4. Report what is enforced

- [x] 4.1 Change `/health` and `jackryan status` to report the enforced corpus identity rather than the contract fingerprint alone; verify the REST test asserts the reported value equals what the store holds
- [x] 4.2 Verify no adapter computes identity itself — both read it from the composition root, so there is one definition

## 5. Records

- [x] 5.1 Move the parked finding in `docs/implementation-notes.md` to fixed, naming which of the two candidate fixes was taken and why
- [x] 5.2 Update `docs/handover.md` if it states anything this change makes false
- [x] 5.3 Correct `config.yaml.example` where it implies every profile value is safe to change
- [x] 5.4 Verify `pytest` and `openspec validate --all --strict` are both clean before pushing
