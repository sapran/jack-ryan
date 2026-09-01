"""The summarising boundary.

A summariser reads a chunk beside the document it came from and writes the short
standalone context that says where in the whole that fragment sits, so a passage
retrieved on its own arrives already situated. It also reduces a document's
ordered chunk notes to one summary of the document.

Unlike the reranker, it writes. A reranker reorders candidates at query time and
stores nothing, which is why it is a profile setting and no corpus depends on it.
A per-chunk summary is folded into what the embedder is given, so every vector in
a folded corpus was built from text this model produced — which is why the
summariser's identity is part of corpus identity, and why a corpus written under
one recipe refuses to be searched under another.

Two failures, and only the first of them is the reranker's:

`check` is a misconfiguration, exactly as the reranker's is. A profile that names
a summariser the instance cannot reach is asking for a corpus it will never get,
so it is fatal for the whole run rather than for one document.

Failing while summarising is where the reranker's precedent stops applying, and
the inversion is deliberate. A reranker that fails has cost the caller a better
ordering and nothing else, so serving the fused order is honest. A document
embedded bare inside a folded corpus is a different thing: its vectors are the
declared width, from the declared model, built from a different kind of input
from every other document's. Both kinds are well-formed, no later check can
separate them, and nothing downstream can detect it. So a summariser failure
fails the document — which is reported — rather than degrading to an
unsummarised embed, which is not.
"""

from __future__ import annotations

from typing import Protocol, Sequence

from ..errors import ConfigError, JackRyanError


class SummaryError(JackRyanError):
    """The summariser failed while summarising.

    A `JackRyanError` rather than a `ConfigError`: the settings are right and the
    summariser was reachable when it was checked. This request, this response, or
    this endpoint's behaviour at this moment went wrong, and the thing that
    failed is the document it happened to.
    """

    code = "summary_failed"


class SummariserUnavailable(ConfigError):
    """The named summariser could not be built.

    A `ConfigError` rather than a `SummaryError`: nothing about any document is
    wrong, and no retry will help. The setting is wrong.

    A separate type so that the ingestion loop can let it past the per-document
    handler by type rather than by call order. A misconfiguration caught as a
    failed document would be reported once per document and fixed by none of
    those reports.
    """


class SummariserPort(Protocol):
    name: str
    """Load-bearing: this value is part of corpus identity while folding is on.

    The model name alone is not enough. What determines the embedded text is the
    model together with the prompt, the document-truncation limit and the
    sampling parameters, all of which live in shipped code — so an implementation
    composes those into this value rather than reporting back the model name it
    was handed. Editing the recipe then changes corpus identity with nobody
    having to remember to bump a version.
    """

    def check(self) -> None:
        """Reach the summariser, or raise `SummariserUnavailable` naming the setting.

        Called when the summariser is first needed rather than at load, for the
        reason the reranker's `check` is: only the implementation can answer
        whether a named model is usable, and answering costs a request that
        `jackryan status` should not pay for.
        """
        ...

    def summarise_chunks(
        self, document_text: str, chunk_texts: Sequence[str]
    ) -> list[str]:
        """Situate each chunk within the document it came from.

        Returns exactly one summary per input, in input order: result *i* is the
        context for `chunk_texts[i]` and for no other chunk. The caller folds
        result *i* into what it embeds for chunk *i*, so a reordering pairs one
        chunk's context with another chunk's text and nothing stored afterwards
        would say so.

        A short return is a `SummaryError`, never a silent pad. A padded list
        would fold context into some chunks of one document and leave the rest
        bare — the same corruption corpus identity exists to prevent, arriving
        one level finer, inside a single document where no identity check can
        reach it.

        Every returned summary is non-empty for the same reason: with folding on,
        an empty context embeds the bare chunk, which is the mixed corpus again.
        """
        ...

    def summarise_document(self, chunk_summaries: Sequence[str]) -> str:
        """Reduce a document's ordered chunk notes to one summary of the whole.

        The result is stored and never embedded, which is why it is not part of
        corpus identity: how it is written moves no vector, so changing it must
        not refuse a corpus. A later change that embeds it anywhere has to move
        its prompt into the hashed recipe in the same change.
        """
        ...
