## Context

Three renderings, two surfaces, six functions. The architecture review counted
the differences and got one of them wrong — it reported the document renderers
as differing on summary handling, when they differ in five ways. That mattered:
it is the difference between "extract one function" and "extract a core and
leave the divergence where it belongs".

## Goals / Non-Goals

**Goals.** One definition of every field the two human surfaces share. The
divergence still visible, and still deliberate. No behaviour change beyond what
is stated.

**Non-Goals.** Folding in the agent surface. Reconciling the rounding or the
conditional fields — both are decisions, not accidents. A flag-driven renderer.

## Decisions

### A shared core plus adapter extras, not one function with five flags

`render_document` returns the nine fields both surfaces carry. REST spreads it
and adds three; the CLI spreads it and conditionally adds three others.

The alternative — `render_document(document, *, casefile_id=..., updated_at=...,
found_at=..., children=..., summary=...)` — would be an interface almost as
wide as the body it hides, and every caller would have to read the flags to know
what it returns. That is the shallow shape this change exists to remove.

The rounding is different, and gets a parameter: `render_hit(hit, *,
round_scores)`. One boolean for one disagreement over two of seventeen fields,
where the alternative is two copies of the other fifteen. Named rather than
positional so neither call site reads as an accident.

### Each adapter keeps its own named function

`cli._render_document`, `server.serialize_document` and `server.serialize_hit`
could each be an alias for the shared one plus a wrapper, or simply re-exported.
They stay as real functions in their own modules for two reasons.

The mechanical one: `tests/test_text_source.py` imports all three document
renderers by name and compares them, and its failure message reports
`render.__module__`. Alias them to one implementation and every one of them
reports `jackryan.rendering` — the test is titled for four renderers agreeing on
one key, and it would lose the ability to say which one disagreed.

The better one: the surfaces *do* differ, and the difference should live where
the surface is. A reader of `server.py` should be able to see that REST always
emits a summary without following an import.

### REST's key order changes, and that is the one thing to argue about

A shared core spread first, extras appended, cannot reproduce an order that
interleaved them — REST had `casefile_id` third and the summary before
`created_at`. So the order changes while the key set and every value stay
identical.

Preserving it exactly would mean the shared function returning fields the caller
then re-lists positionally, which is the duplication again with extra steps.
JSON objects are unordered by specification, nothing in this repository asserts
the order, and no documented client depends on it. Taken, and stated in the
proposal rather than discovered in a diff.

### The agent surface stays out, and the module says so

`interfaces/mcp` renders these objects for a different reader under different
rules. Its exclusion is written into `rendering.py`'s own docstring, because the
risk is not that someone folds it in by accident — it is that someone reads
three similar renderers and two shared ones, concludes the third is an
oversight, and "finishes the job".

## Risks / Trade-offs

**The key-order change is real, if minor.** It is the only observable effect of
this change, and it lands on the surface with remote callers rather than the one
with a person at a terminal. Mitigated only by being stated; if a client is
found that depends on it, the fix is to have REST re-list its keys.

**A shared renderer invites the wrong kind of tidying.** Someone who sees
`render_document` returning nine of REST's thirteen fields may try to "complete"
it. The docstring argues against that in place, and the new parity test asserts
both what is shared and what is not, in both directions — so collapsing the
divergence fails a test rather than passing quietly.

**The two new tests would have passed before this change.** They describe a
property that was already true by coincidence; what changed is that it is now
true by construction. They are a guard against future drift, not evidence that
this refactor happened — and that distinction is worth keeping straight, because
running them green proves nothing about the diff.
