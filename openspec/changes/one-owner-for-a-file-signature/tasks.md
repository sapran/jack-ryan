## 1. The rule in the published specs

- [x] 1.1 Establish by falsification that no spec is affected; verify by searching for what the change touches rather than by judging that a refactor cannot touch a spec. *Grepped `openspec/specs/` for "scratch", "copy" and the signature constants: nothing. `document-ingestion` covers content routing behaviourally — which file is read as what — and says nothing about how the file reaches the extractor, which is the only thing this moves.*
- [x] 1.2 Ship the change directory with `skip_specs: true`; verify the marker is honoured rather than assuming it, since it is silently ignored without valid metadata. *`schema:` and `created:` both present. `openspec validate --all --strict` passes.*

## 2. One owner per signature

- [x] 2.1 Lift RTF's signature out of `sniffing`'s `_MAGIC` table into a named constant and reference it from the table; verify `producible_suffixes()` still derives `.rtf`, since it reads that table. *It does — the tuple now holds `(_RTF_MAGIC, ".rtf")` and the derived set is unchanged.*
- [x] 2.2 Have `legacy_office` import the three signatures rather than declaring them; verify the **import form**, because sixteen tests read `legacy_office._OLE2_MAGIC` and only `from .sniffing import ...` keeps that attribute bound. *Watched failing with the module form (`sniffing._OLE2_MAGIC` inline): 16 failed, every one `AttributeError: module 'jackryan.ingestion.legacy_office' has no attribute '_OLE2_MAGIC'`.*
- [x] 2.3 Record why the two modules may share these bytes at all; verify the reason is stated where the constants live rather than in a commit message. *In `sniffing`'s comment: the two ask a narrower and a wider version of one question about the same bytes, and two spellings drifting apart means a file routes one way and converts another.*

## 3. One scratch name

- [x] 3.1 Move `SCRATCH_STEM` to `extractors`; verify the alternative homes close a cycle. *`router` importing `legacy_office` would, since `extractors` already imports `legacy_office` lazily. `extractors` is imported by both and imports neither.*
- [x] 3.2 Re-export it through `router`; verify the test that imports it from there still resolves. *`tests/test_content_routing.py` imports `CONTENT_ROUTED, SCRATCH_STEM, FormatRouter` from `router` and uses the constant; 27 passed.*
- [x] 3.3 Reconcile the dotted and undotted spellings; verify both paths produce the identical name, since `router._resolve` builds it to ask an extractor whether it `accepts` the file and a mismatch would hand the file to a different extractor than the one chosen. *`source.xlsx` from both, checked directly rather than reasoned about.*

## 4. One scratch-and-delegate

- [x] 4.1 Add `deliver_via_scratch_directory` to `extractors`; verify it takes a **producer** rather than a finished path, and that the reason is the difference between the two callers rather than generality for its own sake. *Content routing copies one file in; legacy Office may run a converter that writes an output directory and a per-call LibreOffice profile beside the result. A helper taking a path could serve only the first, leaving the second with its own teardown — the half that has gone wrong before.*
- [x] 4.2 Call `tempfile.mkdtemp` through the module rather than importing the name; verify a test substituting it still observes the allocation. *It does; `tests/test_legacy_office.py` patches `extractors.tempfile` and records the directory.*
- [x] 4.3 Keep the prefix a parameter; verify the two are load-bearing in opposite directions rather than merely different. *`test_content_routing.py` globs `jackryan-routed-*` to prove cleanup, and separately asserts that exact string never reaches an error message. Nothing globs `jackryan-legacy-`.*
- [x] 4.4 Point both callers at the helper and drop the imports each no longer needs; verify `tempfile` is genuinely unused in each before removing it. *Removed from `router` and from `legacy_office`. `shutil` stays in both — `router` still copies, `legacy_office` still probes for the converter binary.*
- [x] 4.5 Have the legacy branch yield `(lineage, produce)` together; verify a refused file now allocates no directory, and that the two can no longer disagree. *One statement sets both, where each branch previously assigned them separately. The refusal for "neither OLE2 nor OOXML" is raised before `mkdtemp`.*

## 5. Verification

- [x] 5.1 Watch the shared teardown fail: remove the `finally` and confirm **both** suites catch it. *4 failed — three parametrised cases in `test_legacy_office.py` (`assert not True`) and `test_the_scratch_copy_is_removed_on_success_and_on_failure` in `test_content_routing.py`. Two unrelated strategies now guard one implementation, which is the argument for consolidating it.*
- [x] 5.2 Repoint the cleanup test at the module that now allocates; verify it would have passed either way, and say why it was moved anyway. *`legacy_office.tempfile` was the global `tempfile` module object, so the substitution reached the helper regardless. Moved because a test that passes for a reason its reader cannot see is worse than one that fails.*
- [x] 5.3 Run the full suite; verify the count is unchanged, since this change adds no behaviour. *697 passed, 3 skipped — same as before.*
- [x] 5.4 Reverse each mutation by hand rather than with `git checkout`; verify no residue survived. *Grepped for the marker strings: none. `git checkout <file>` discarded uncommitted work twice earlier in this session, which is why it was not used here.*
- [x] 5.5 Record the result-rebuild difference rather than fixing it. *`router` uses `replace`, `legacy_office` builds a fresh `Extraction` overriding `media_type` deliberately and dropping `is_container` by omission. Unifying them would be a behaviour change inside a change claiming none. In `docs/implementation-notes.md`.*
- [x] 5.6 Run `openspec validate --all --strict`.

## 6. Review round

- [x] 6.1 Have the change reviewed against the ingestion invariants; verify the two load-bearing claims independently rather than taking the commit message's word. *Both reproduced by the reviewer: unbinding the module attribute the way the inline form would gives **exactly 16 failures, all `AttributeError`**, and neutralising `rmtree` inside the helper gives 4 targeted failures across both suites. No findings at or above the reporting bar.*
- [x] 6.2 Confirm the reordering leaks no scratch directory; verify by counting directories rather than by reading the control flow. *Measured: the two refusal paths create **zero** directories, both delegate-failure paths create one and remove it, and the temp-root count across `test_legacy_office.py` and `test_content_routing.py` is unchanged at 28 before and after.*
- [x] 6.3 Confirm every error message is byte-identical; verify by producing them, not by comparing templates. *All four message-producing paths exercised against the built code and compared with the pre-image: identical. The dotted/undotted asymmetry feeds one template and cancels.*
- [x] 6.4 Finish the three cosmetic points the review raised, all in code this change wrote. *Blank-line residue in `router` where `SCRATCH_STEM` used to sit; return annotations on `_converted_to` and `_copied_to`, which the rest of the module has; and the repointed test's comment, which read as though patching `extractors.tempfile` were scoped to that module when it is the global `tempfile` and therefore process-wide — the comment now says `extractors` names where the allocation happens, not where the patch reaches.*
