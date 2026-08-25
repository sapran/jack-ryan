"""Typed errors shared by the service layer.

Adapters (REST, CLI, and later MCP) translate these into their own idiom.
The service layer never raises adapter-specific exceptions, so every adapter
inherits the same failure semantics.
"""


class JackRyanError(Exception):
    """Base for every error the service layer raises deliberately."""

    code = "error"


class ConfigError(JackRyanError):
    """Configuration is missing, malformed, or internally inconsistent.

    Always fatal at boot: a misconfigured instance fails loudly rather than
    running with a silently substituted default.
    """

    code = "config_error"


class NotFoundError(JackRyanError):
    """A referenced object does not exist."""

    code = "not_found"


class AmbiguousReferenceError(JackRyanError):
    """A short id prefix matched more than one object."""

    code = "ambiguous_reference"


class ValidationError(JackRyanError):
    """Caller-supplied input failed a service-layer rule."""

    code = "validation_error"


class ConflictError(JackRyanError):
    """The write would violate a uniqueness rule."""

    code = "conflict"
