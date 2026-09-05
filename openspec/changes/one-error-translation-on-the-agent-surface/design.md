## Context

The agent surface is eight closures inside `build_mcp_server`, each registered
by `@server.tool(...)` and each returning `dict[str, Any]`. They shared one
failure convention and eight copies of it.

The SDK is `mcp` 2.1.1, using `MCPServer` — not `FastMCP`, which also ships in
that package and reads function signatures differently. Everything below was
checked against the installed source rather than against the documentation,
because the whole change turns on how the SDK inspects a decorated function.

## Goals / Non-Goals

**Goals.** One translation for every tool. The translation covering a tool's
whole body, so the `mcp-tool-surface` no-raise rule holds wherever the failure
happens. A test that fails if the advertised schemas are lost.

**Non-Goals.** Changing which exceptions are translated. Changing any payload.
Touching the profile pruning, the annotations table, or the fence. Making
`case_search`'s `int(limit)` a typed failure — it is a `ValueError` and stays
one.

## Decisions

### The decorator lives in `errors.py`, not beside the tools

`interfaces/mcp/errors.py` already exists and its docstring already states the
rule the decorator enforces: a tool returns a payload rather than raising,
because an agent can branch on a value and can only retry a transport failure.
Putting the mechanism next to the statement of the rule means a reader who finds
one finds the other. `server.py` keeps the tools; `errors.py` keeps what happens
when one fails.

### It is applied below `@server.tool(...)`, and that ordering is not cosmetic

Decorators apply bottom-up. `@returns_error_payload` must wrap the tool first so
that `server.tool` registers the wrapper; reversed, the SDK would register the
bare function and the translation would sit outside the thing being called,
never running.

### `functools.wraps` is load-bearing, not tidiness

`Tool.from_function` builds the advertised input schema from
`inspect.signature(fn, eval_str=True)` (`func_metadata.py:322`). That call
defaults to `follow_wrapped=True`, so it walks `__wrapped__` back to the real
tool and recovers its parameter names, annotations and defaults — and its
`dict[str, Any]` return annotation, which is what produces the structured output
schema.

Without `wraps`, every tool advertises `*args, **kwargs`: a schema with **no
parameters at all**. An agent is then told the tools take no arguments, and
every real call is refused as an unexpected argument. Watched failing: with
`wraps` removed, `case_list_casefiles advertises {'kwargs', 'args'}`.

`eval_str=True` resolves the string annotations that `from __future__ import
annotations` produces, and it resolves them against the *unwrapped* function's
globals — so the annotations still evaluate in `server.py`'s namespace even
though the decorator lives in `errors.py`.

### The wrapper must be `async def`

The SDK decides sync-versus-async with `inspect.iscoroutinefunction` against the
**wrapper** (`_callable_inspection.py`). Unlike `inspect.signature`, that does
not follow `__wrapped__`. A synchronous wrapper returning a coroutine would be
registered `is_async=False` and run through `anyio.to_thread.run_sync`, which
would hand the caller an un-awaited coroutine instead of a payload. Watched
failing: a `def` wrapper breaks twelve tool calls in `tests/test_mcp_surface.py`.

`call_fn` invokes `await fn(**kwargs)` — keyword-only — so
`async def translated(*args, **kwargs)` forwards everything cleanly.

### Wrapping the whole tool closes a real hole, and it is one line wide

`case_get_passage` asks the service for a window at `server.py:362`, *after* the
`try` that used to end at `:355`. A `JackRyanError` from there escaped the tool
as an exception, which `mcp-tool-surface` forbids.

Traced before claiming it: `passage_window → _window_for →
get_document_chunks_around`, plus span arithmetic. Nothing on that path raises a
`JackRyanError` in the current code, so **no live behaviour changes**. The seam
is closed before anything reaches it rather than after — which is the only time
closing one is cheap.

Everything else that sits outside the old `try` blocks was checked individually
and cannot raise a `JackRyanError`: `one_line`, `listing_payload`,
`search_payload`, `fence`, `provenance`, and `read_as`, which is total —
`return text_source if text_source in TEXT_SOURCES else UNRECORDED`.

### The catch stays `JackRyanError`

Widening to `Exception` would convert crashes into typed payloads, which reads
as a tidier surface and is the opposite of what this project wants: a crash an
agent retries forever is worse than one that surfaces. It would also swallow the
`BaseException`-adjacent discipline the ingest test gate depends on. The
narrowness is the feature.

## Risks / Trade-offs

**A decorator hides control flow.** Eight visible `try` blocks became one
invisible wrapper, and a reader of a single tool can no longer see what happens
when it fails. This is the standard cost of the shape the spec asks for, and
REST already pays it. Mitigated by the decorator's docstring carrying the whole
argument, and by the schema test naming what breaks if it is applied wrongly.

**The widening is deliberate but unexercised in production.** No current code
path reaches the newly covered line with a typed error. The new test reaches it
by substituting a refusing `passage_window` on the real service object, so the
guarantee is exercised even though no shipped code produces it yet.

**A decorated closure is harder to call directly in a test.** Nothing in the
suite does — every test goes through `server.call_tool` — but a future test
wanting the raw function would have to reach `__wrapped__`.
