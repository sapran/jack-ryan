## Why

The architecture review said corpus identity is "spread across four files, owned
by nothing". On inspection **three of the four own something genuinely theirs**,
and gathering them would be wrong:

| File | Owns | Verdict |
|---|---|---|
| `config.py` | escaping, component order, the join | the only real duplication |
| `app.py` | composition from runtime-chosen values | must stay — `layered-configuration` requires identity be *"computed where all of them are known"* |
| `summarising/model.py` | the summariser's own name and recipe hash | that module's business |
| `storage/` | comparison and refusal | the store's business; it holds the recorded value |

So this change is **smaller than the review billed it**, and says so here rather
than letting review find it.

What is real is on `Context`, which carried two fields:

```python
corpus_fingerprint: str      # app.py:33
summariser_name: str = ""    # app.py:57
```

Both came from the same three lines and were stored apart, with nothing making
them agree. Worse, `summariser_name` had **no production reader at all** — a
`grep` across `src/` and `scripts/` returned only its own assignment. That is the
shape the `casefile-statistics` change already fixed once: a value on a seam that
is written and never read.

And the rule binding them — *the `|summariser=` component appears exactly when a
summariser is folded in* — was a coincidence of two functions agreeing, not
something a test could state, because there was no single thing to state it
about.

## What Changes

**Current behaviour.** Identity is rendered by two functions that must agree on a
separator, and carried as two `Context` fields that must agree on a summariser.

**Desired behaviour.**

- **A frozen `CorpusIdentity` in `config.py`** holding `contract`, `embedder` and
  `summariser`, rendering the recorded string in `__str__`. It owns the
  composition: the join, the escaping of the composed names, and the
  omit-when-empty rule.
- **`Contract.fingerprint()` still renders its own five components.** The type
  composes; it does not absorb.
- **`corpus_fingerprint()` stays** as a thin function returning
  `str(CorpusIdentity(...))`. Ten test sites and the retrieval-evaluation oracle
  call it, and there is now one implementation of the rendering behind it.
- **`Context.identity: CorpusIdentity` is the field**, and `corpus_fingerprint`
  and `summariser_name` become read-only **properties** derived from it. Every
  existing reader keeps working unchanged and the two can no longer disagree.
- **The store still takes an opaque `str`.** `storage/` imports nothing from
  `config.py`, and `schema-migration`'s purpose statement treats identity as an
  opaque comparable value. Passing the type in would make storage depend on
  configuration for no gain.

**No behaviour changes.** The rendered string is byte-identical — checked against
the literal a real `store_meta` table produced — and the whole suite passed with
zero test edits before the two new tests were added.

**Deliberately not in scope.** The parked naming drift:
`initialize(contract_fingerprint=…)`, the `store_meta` key `contract_fingerprint`,
and the `"contract"` field in `/health` and `jackryan status` all say *contract*
while holding corpus identity. Renaming the stored key needs a migration rung and
the JSON field is a published surface. Both stay, and the note recording them
stays.

**Explicitly refused.** `CorpusIdentity` gets no `parse`.
`tests/test_config.py` splits an identity with a parser of its own to prove a
crafted name cannot impersonate a component; routing that through the class would
make the check and the thing checked the same code.

## Impact

- **Specs: none**, and this one was closer than the others. `layered-configuration`
  already requires that *"the value reported to an operator as the instance's
  corpus identity SHALL be the value the store enforces"*, and that was already
  true and already asserted. A scenario about two internal fields not disagreeing
  would be a claim about implementation: `summariser_name` is not on any adapter
  surface — `/health` and `jackryan status` carry only the identity string — so no
  operator could ever have observed the disagreement this removes.
- **Code:** `src/jackryan/config.py`, `src/jackryan/app.py`.
- **Tests:** two added to `tests/test_config.py`. No existing test changed.
- **Docs:** `CLAUDE.md` gains the name of the type that owns the rendering; the
  composition rule's wording is untouched.
