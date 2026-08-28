"""The reranking boundary.

A reranker reads a query and a passage together and says how well they answer
each other. Unlike the embedder it writes nothing: it reorders candidates at
query time and its scores are never stored, which is why it is a profile setting
and not part of corpus identity.

Two failures, deliberately not the same failure:

`check` is a misconfiguration. A profile that names a reranker the instance
cannot build is asking for results it will never get, and an instance that
quietly serves the fused order instead has hidden that from the operator.

`score` failing on one response is transient. Refusing to answer would make
retrieval quality a condition of retrieval — the search still has a ranking,
just not the better one — so the fused order stands and the response says so.
"""

from __future__ import annotations

from typing import Protocol, Sequence

from ..errors import ConfigError, JackRyanError


class RerankError(JackRyanError):
    """The reranker failed while scoring a response."""

    code = "rerank_failed"


class RerankerUnavailable(ConfigError):
    """The named reranker could not be built.

    A `ConfigError` rather than a `RerankError`: nothing about the request is
    wrong, and no retry will help. The setting is wrong.
    """


class RerankerPort(Protocol):
    name: str
    """The model this reranker runs, as the operator named it.

    Reported beside a measurement, because a retrieval figure means nothing
    without the reranker that produced it.
    """

    def check(self) -> None:
        """Build the model, or raise `RerankerUnavailable` naming the setting.

        Called when the reranker is first needed rather than at load: only the
        implementation can answer whether a model name is usable, and answering
        costs seconds and possibly a download that `jackryan status` should not
        pay for.
        """
        ...

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        """Score each passage against the query, in the order given.

        The values are uncalibrated and comparable only within one call. They
        are not probabilities and not comparable between queries or between
        models.
        """
        ...
