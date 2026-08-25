"""Failures an agent can act on.

A tool returns a payload rather than raising: an agent can branch on a returned
value, whereas a transport failure is something it can only retry. The codes are
the ones the service layer raises, so the vocabulary is identical on every
surface.
"""

from __future__ import annotations

from typing import Any

from ...errors import JackRyanError


def error_payload(code: str, message: str) -> dict[str, Any]:
    return {"error": code, "message": message}


def from_exception(exc: JackRyanError) -> dict[str, Any]:
    return error_payload(exc.code, str(exc))
