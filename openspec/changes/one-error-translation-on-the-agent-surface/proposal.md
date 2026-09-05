## Why

`service-adapter-boundary` already says how a typed error reaches a caller:

> Every adapter SHALL translate them into its own idiom in exactly one place
> rather than per route or per command, so a new route or command inherits the
> mapping instead of restating it.

REST satisfies that with a single exception handler (`server.py:168-173`). The
agent surface did not. It wrote the same three lines eight times, once per tool,
at `interfaces/mcp/server.py:145, 169, 213, 260, 284, 354, 410, 484`:

```python
except JackRyanError as exc:
    return from_exception(exc)
```

Three things follow from that, and none is a matter of taste:

1. **The rule was enforced eight times, so there were eight places to forget
   it.** A ninth tool inherits nothing. The spec's own reasoning for demanding
   one place is that this surface has no request-validation layer above it and
   is driven by a model rather than by a caller who read the documentation.
2. **The translation did not cover the whole tool.** In five of the eight, the
   `try` closed before the payload was built. `case_get_passage` asks the
   service for a window *after* it closes — so a typed failure there left the
   tool as an exception, which `mcp-tool-surface` forbids in as many words:
   a tool "SHALL NOT raise, because an agent can act on a returned value and can
   only retry a transport failure."
3. **Nothing tested the tools' advertised schemas**, so the shape of a fix like
   this was unguarded.

## What Changes

**Current behaviour.** Each tool opens with a `try` covering its service calls
and returns `from_exception` on a typed failure. Anything the tool does after
that block — building a payload, asking the service for a window — is outside
the translation, and a typed error from it propagates as a transport failure.

**Desired behaviour.**

- **One decorator, `returns_error_payload`, applied to every tool.** The rule
  lives in `interfaces/mcp/errors.py`, the module whose subject is turning a
  failure into something an agent can act on. A ninth tool inherits it by being
  decorated, and the eight `try` blocks are gone.
- **The translation covers the whole tool, not its opening calls.** This closes
  the `mcp-tool-surface` hole at `case_get_passage`: a typed failure from
  `passage_window` is now a payload. Nothing on that path raises a
  `JackRyanError` today, so no live behaviour changes — the seam is closed
  before it is reached, not after.
- **What was registered is inspected, not inferred from the call sites.** Three
  ways of applying this decorator wrongly are silent to some or all of the
  suite: without `functools.wraps` a tool advertises the wrapper's own two
  required parameters instead of its own; a synchronous wrapper is registered as
  a plain function; and applied *above* `@server.tool(...)` the SDK registers
  the undecorated function, so the translation never runs. The last one, done to
  a tool nothing else calls, leaves the entire suite green. Two tests now assert
  the advertised parameters and `required` lists, and that every registered tool
  is the wrapper and is async.

**Deliberately not in scope.** The catch stays `JackRyanError`. Widening it to
`Exception` would convert a crash into a typed payload — a behaviour change in
the wrong direction, and it would swallow the rung sentinel the test gate relies
on. `int(limit)` at `server.py:249` raises `ValueError`, not `JackRyanError`, and
is unaffected in either direction.

## Impact

- Affected specs: `service-adapter-boundary` (MODIFIED — a scenario making the
  existing SHALL testable on this adapter), `mcp-tool-surface` (MODIFIED — a
  scenario that the no-raise rule holds however far through a tool the failure
  happens)
- **Not** affected: `mcp-surface-profiles` and `analyst-pack`. Both were read
  rather than assumed. Profiles are pruned by name after definition
  (`server.py:_defined_tool_names`), and `Tool.name` comes from the explicit
  `name=` argument, so a decorator cannot change what a profile admits; the pack
  names tools without describing how they fail. A MODIFIED block for either
  would reproduce it byte-identically, which the delta guidance says to cut.
- Affected code: `src/jackryan/interfaces/mcp/errors.py` (the decorator),
  `src/jackryan/interfaces/mcp/server.py` (eight tools, one import line)
- New tests: `tests/test_mcp_surface.py` — the advertised parameters of all
  eight tools, and a typed failure raised after a tool's opening calls
- No migration, no schema change, no corpus-identity component. Nothing this
  change touches writes anything.
- A dead import is removed in passing: `error_payload` had no caller in `src/`
  or `tests/` and sits on the one import line this change already edits.
