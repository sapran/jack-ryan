## 1. The rule in the published specs

- [x] 1.1 Read `layered-configuration`'s fingerprint requirement in full and
      decide whether this change makes any SHALL newly true; verify by asking
      what an operator could observe, not by whether the code got better. *It
      makes none newly true. "The value reported to an operator as the
      instance's corpus identity SHALL be the value the store enforces" was
      already true and already asserted by
      `test_the_reported_identity_is_the_one_the_store_enforces`. The
      disagreement this removes was between two internal fields; `summariser_name`
      reaches no adapter surface — `/health` and `jackryan status` carry only the
      identity string — so no operator could have observed it.*
- [x] 1.2 Confirm the composition rule is untouched; verify against the archived
      designs rather than from memory. *`corpus-identity-and-schema-migration`
      and `embed-input-is-corpus-coupled` both require identity be composed where
      the runtime-chosen values are known rather than declared in the contract.
      Composition stays in `app.py`; the type is constructed there and nowhere
      else.*
- [x] 1.3 Ship `skip_specs: true` with the argument as a comment; verify
      `openspec validate --all --strict` accepts it.

## 2. The value type

- [x] 2.1 Add a frozen `CorpusIdentity(contract, embedder, summariser="")` to
      `config.py` with `__str__` rendering the recorded string; verify the string
      is byte-identical to what `corpus_fingerprint` produced. *Checked against
      the literal in `test_escaping_leaves_every_existing_identity_unchanged`,
      which was read from a real `store_meta` table rather than recomposed:
      identical, folded and unfolded.*
- [x] 2.2 Leave `Contract.fingerprint()` rendering its own five components;
      verify the split mirrors the design rather than being an accident of where
      the code was. *It does: the contract is declared, the embedder and
      summariser are composed. One flat renderer would erase the distinction the
      whole design turns on.*
- [x] 2.3 Reduce `corpus_fingerprint` to one line over the type; verify its ten
      test callers and the retrieval-evaluation oracle are unaffected. *All pass
      untouched; `tests/test_evaluate_retrieval.py` still compares
      `docs/retrieval-baseline.json`'s `corpus` field against a live call.*
- [x] 2.4 Refuse a `parse` on the type; verify the reason is written where a
      later change will read it. *In the class docstring and in `design.md`.
      `tests/test_config.py:_parsed_identity` must stay independent — its whole
      job is to prove a crafted name cannot impersonate a component, and sharing
      code with what it checks would defeat that.*

## 3. The composition root

- [x] 3.1 Replace `Context`'s two fields with `identity: CorpusIdentity`; verify
      `summariser_name` really had no production reader before removing it as a
      field. *Grep across `src/` and `scripts/` returned only its own assignment
      in `app.py`. Three tests read it, all still passing through the property.*
- [x] 3.2 Make `corpus_fingerprint` and `summariser_name` read-only properties;
      verify no call site changes. *None did — `server.py:185`, `cli.py:214`,
      `scripts/evaluate_retrieval.py:999` and about thirteen test sites are
      untouched. **The entire suite passed with zero test edits** before the two
      new tests were added, which is the evidence that these are views rather
      than a rename.*
- [x] 3.3 Construct the value in `build_context` and hand `str(identity)` to the
      store; verify `storage/` still imports nothing from `config.py`. *It does
      not. The store's parameter is still an opaque `str`, which is what
      `schema-migration` treats identity as.*

## 4. The tests the type makes possible

- [x] 4.1 Assert the summariser component appears exactly when there is a
      summariser; verify by appending it unconditionally. *Three tests go red,
      including the new one by name — "the value says summariser='' and the
      string it renders disagrees" — and the golden oracle.*
- [x] 4.2 Assert `Context`'s two views cannot disagree with the value they read
      from; verify by making one of them lie. *`summariser_name` forced to `""`:
      the new test fails with `assert '' == 'qwen3/9a3f1c2b4d5e'`. Worth noting
      that `tests/test_summarising.py`'s equivalent assertion is **skipped**
      without an LLM endpoint, so this is real new coverage rather than a
      duplicate.*
- [x] 4.3 Assert the field is gone rather than merely shadowed; verify the test
      would notice a second field reappearing. *`"summariser_name" not in {f.name
      for f in fields(Context)}` — a re-added field would satisfy the property
      test while restoring the hazard, so the property test alone is not enough.*

## 5. Verification

- [x] 5.1 Run `pytest -q`; verify 710 plus the new tests. *712 passed, 3
      skipped.*
- [x] 5.2 Confirm both golden literals unchanged; verify against the files rather
      than by reasoning. *`tests/test_config.py`'s oracle and
      `docs/retrieval-baseline.json`'s `corpus` field both pass untouched, and
      neither file is in the diff.*
- [x] 5.3 Run `openspec validate --all --strict`; verify 18 items pass.
- [x] 5.4 Leak-grep the diff; verify nothing matches.
