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

## 6. What review found

- [x] 6.1 Have the rendered string checked against develop's implementation over
      hostile inputs, not just the golden literal; verify the check covered the
      characters escaping exists for. *Review ran both implementations over 4
      contracts × 22 × 22 name pairs including `""`, `" "`, `"\t"`, `"\x00"`,
      `"\n"`, `"|"`, `"\\"`, `"=="`, non-ASCII, and `None`/`0`/`False` passed
      where a `str` belonged: **0 divergences**, including the two-argument
      default path. Whitespace-only is truthy in both and appends; `None` is
      falsy in both and omits.*
- [x] 6.2 Confirm no dataclass field shadows either new property and nothing
      still passes the old names as keyword arguments; verify from
      `dataclasses.fields`, not by reading. *Fields are exactly `config`,
      `identity`, `store`, `embedder`, `casefiles`, `ingestion`, `search`; both
      old names resolve to `property` objects in `Context.__dict__`. `app.py` is
      the only construction site and no `dataclasses.replace` on a `Context`
      exists anywhere.*
- [x] 6.3 Confirm a value cannot reach the store where a string belonged; verify
      by removing the `str()`. *Loud, not silent: `sqlite3.ProgrammingError:
      Error binding parameter 2: type 'CorpusIdentity'`, six tests red in
      `test_app.py`.*
- [x] 6.4 Record the `__repr__` observation; verify why it is not fixed.
      *`repr(identity)` is the generated dataclass repr, not the recorded string.
      Nothing formats an identity with `!r` today and the refusal message
      interpolates what it read from `store_meta`. Overriding `__repr__` would
      hide the fields from a debugger — the opposite trade, no more obviously
      right — so it is written into `design.md` instead.*
- [x] 6.6 Close the one unguarded path review found; verify with the mutation
      that survived. *Dropping `_escaped()` around the embedder left **all 712
      tests green**. Of the three composed values, `embed_model` and the
      summariser each had an impersonation test and the embedder had none — and
      `test_two_different_configurations_cannot_share_one_identity` looks like it
      covers this and does not, because one escaped end is enough to break that
      particular collision; its own docstring warns about that shape of false
      coverage. Added `test_an_embedder_name_cannot_impersonate_another_component`,
      using the reader-side `_parsed_identity` so the check and the thing checked
      stay different code. The surviving mutation now fails exactly that test,
      by name. What it makes reachable is the worst collision available here: an
      embedder named `model|summariser=q` renders the identity of a corpus folded
      by `q`, so a folded corpus opens under an unfolded configuration with
      `/health` reporting a match. Nil reachability today — both shipped
      embedders name themselves with class literals — but `EmbedderPort.name` is
      a bare `str` on the protocol, and the argument for escaping it is written
      in the code.*
- [x] 6.7 Record the folding asymmetry review found; verify it is not reachable
      through shipped configuration before parking it. *`app.py` decides
      `folding` from the summariser **object**; `__str__` decides the component
      from its **name** being truthy. A summariser with `name = ""` folds while
      recording an unfolded identity — the direction that must never happen.
      `summarising/__init__.py` strips and rejects an empty `summary_model`, so
      only the `summariser=` injection seam reaches it and only test doubles use
      that. Recorded in `docs/implementation-notes.md`, not fixed: the repair is
      a new refusal on a startup path and belongs in a change that argues for it.*
- [x] 6.5 Explain the reviewer's scope note rather than dismissing it. *It
      reported the diff as also carrying `services/windowing.py` and the storage
      split. It had diffed against the **local** `develop` ref, stale at
      `aed01d2` — before #31 and #32 merged. Against `origin/develop`
      (`ffb6626`) the diff is 9 files and 515 insertions, which is this change
      alone. Its conclusions are unaffected; it read the right files. Future
      review briefs should name `origin/develop` explicitly.*
