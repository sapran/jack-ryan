"""Failures an agent can act on.

A tool returns a payload rather than raising: an agent can branch on a returned
value, whereas a transport failure is something it can only retry. The codes are
the ones the service layer raises, so the vocabulary is identical on every
surface.
"""

from __future__ import annotations

import functools
from typing import Any, Awaitable, Callable

from ...errors import JackRyanError


def error_payload(code: str, message: str) -> dict[str, Any]:
    return {"error": code, "message": message}


def from_exception(exc: JackRyanError) -> dict[str, Any]:
    return error_payload(exc.code, str(exc))


def returns_error_payload(
    tool: Callable[..., Awaitable[dict[str, Any]]],
) -> Callable[..., Awaitable[dict[str, Any]]]:
    """Translate a typed failure into a payload, for every tool, in one place.

    `service-adapter-boundary` requires each adapter to translate the service
    layer's typed errors "in exactly one place rather than per route or per
    command", so a new route or command inherits the mapping instead of
    restating it. REST satisfies this with one exception handler; this surface
    satisfied it eight times, once per tool — the same rule enforced eight
    times, and therefore eight places it can be forgotten.

    Wrapping the whole tool rather than one call inside it is the point.
    `mcp-tool-surface` says a tool SHALL NOT raise, and a tool's payload is
    built after whatever it awaited — so a typed error from anything reached
    while building one used to escape as a transport failure, which an agent can
    only retry rather than branch on.

    Two mechanics the SDK forces, both load-bearing:

    `functools.wraps` is not cosmetic here. `Tool.from_function` builds the
    advertised input schema from `inspect.signature(fn, eval_str=True)`, which
    follows `__wrapped__` back to the real tool; without it every tool would
    advertise `*args, **kwargs` — a schema with no parameters at all — and the
    return annotation that produces the structured output schema would be lost
    with it.

    The wrapper must be `async def`. The SDK decides that with
    `inspect.iscoroutinefunction` against the *wrapper*, and that does not
    follow `__wrapped__` — a synchronous wrapper returning a coroutine would be
    registered as a plain function and run through a worker thread, handing back
    an un-awaited coroutine instead of a payload.
    """

    @functools.wraps(tool)
    async def translated(*args: Any, **kwargs: Any) -> dict[str, Any]:
        try:
            return await tool(*args, **kwargs)
        except JackRyanError as exc:
            return from_exception(exc)

    return translated
