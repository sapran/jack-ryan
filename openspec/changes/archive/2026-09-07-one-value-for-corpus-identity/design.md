## Context

Corpus identity is the string that decides whether an existing corpus may be
opened. It is composed at the composition root from three things: the contract
an operator declares, the embedder the code selected, and — only when folding is
on — the summariser, whose name carries a hash of shipped code.

That composition is load-bearing and settled. It is argued in `CLAUDE.md`, in
`docs/design.md` §5, and in two archived designs
(`corpus-identity-and-schema-migration`, `embed-input-is-corpus-coupled`). **This
change moves code and never the rule.**

## Goals / Non-Goals

**Goals.**

- One value, so a component of identity cannot be held separately from the
  identity it belongs to.
- One implementation of the rendering.
- The recorded string byte-identical, verified against a literal read from a real
  `store_meta` table rather than recomposed from code.

**Non-Goals.**

- Moving composition out of `app.py`. `layered-configuration` requires identity
  be *"computed where all of them are known"*; the composition root is that
  place, and a `CorpusIdentity` constructed anywhere else would be a copy of a
  decision rather than the decision.
- Passing the type into `storage/`.
- Resolving the naming drift.
- Giving the type a `parse`.

## Decisions

### The type composes; the contract still renders itself

`Contract.fingerprint()` keeps its five components and its `|` join.
`CorpusIdentity.__str__` joins that to `embedder=` and, conditionally,
`summariser=`.

The alternative — folding all eight components into one renderer — was rejected
because `Contract.fingerprint()` is called directly by tests and by
`docs/retrieval-baseline.json`'s oracle, and because the split mirrors the design
it exists to express: the contract is *declared*, the other two are *composed*.
One renderer would flatten that distinction into a list of strings.

### `corpus_fingerprint` survives as a function

It is now `return str(CorpusIdentity(contract, embedder_name, summariser_name))`.

Keeping it costs one line and avoids churning ten test sites plus
`tests/test_evaluate_retrieval.py`'s comparison against the shipped baseline. It
is also a reasonable thing to want: "the string for these three values" without
holding a value. What matters is that there is now one implementation of the
rendering behind both entry points.

### `Context` holds the value; the old names become properties

`identity: CorpusIdentity` replaces the two fields. `corpus_fingerprint` and
`summariser_name` are read-only properties over it.

This is what makes the change free at every call site — `server.py:185`,
`cli.py:214`, `scripts/evaluate_retrieval.py:999` and about thirteen test sites
are untouched, and **the entire suite passed with zero test edits** before the
two new tests were added. A property is the right shape here rather than a
compatibility shim: `corpus_fingerprint` is the name the published `/health`
field maps from and should stay readable under it.

### No `parse`, deliberately

`tests/test_config.py` carries `_parsed_identity`, a hand-rolled splitter used to
prove that a summariser name containing `|embedder=` cannot impersonate a
component. Its independence is the point, the same way
`test_escaping_leaves_every_existing_identity_unchanged` uses a literal read from
a real store rather than a recomputation — its own docstring calls that *"an
oracle the code cannot drift into agreeing with"*.

A `CorpusIdentity.parse` would be a natural-looking addition and would let that
test share code with what it checks. Refused, and recorded here so a later change
does not add it as a tidy-up.

## Risks / Trade-offs

**The gain is modest and should not be oversold.** Three of the four files the
review named own their part correctly. What this removes is one duplicated
rendering and one pair of fields that could disagree — where the disagreement was
never operator-visible, because `summariser_name` reaches no adapter surface. It
is worth doing because the invariant becomes structural and because the type is
where a later change to identity will want to live; it is not worth claiming more
than that.

**Two golden literals must stay byte-identical**, and both are checked:
`tests/test_config.py`'s oracle, read from a real `store_meta` table; and
`docs/retrieval-baseline.json`'s `corpus` field, compared against a live
`corpus_fingerprint(Contract(), "model")` by `tests/test_evaluate_retrieval.py`.
Both pass unchanged. The oracle also catches the one mutation that matters:
appending the summariser component unconditionally fails it, along with the new
test.

**A frozen dataclass gains `__eq__` where a string had one.** Two
`CorpusIdentity` values compare by their three fields rather than by the rendered
string. Those cannot disagree today — the rendering is a total function of the
fields — but a future component that rendered conditionally on something outside
the dataclass would make them diverge. Nothing compares identities by value; the
store compares strings. Verified in review: no code path compares two identities,
hashes one, or uses one as a dict key.

**And it gains a `__repr__` that is not the recorded string.** `str(identity)` is
the value an operator compares against a refusal; `repr(identity)` is the
generated dataclass repr, which prints the whole `Contract`. No site formats an
identity with `!r` today, and a refusal message interpolates the string it read
from `store_meta` rather than a value. But this is a class whose entire purpose is
one string, so a later error message written with `!r` would print something an
operator cannot compare. Recorded rather than fixed: overriding `__repr__` to
return the rendered string would hide the fields from a debugger, which is the
opposite trade and no more obviously right.
