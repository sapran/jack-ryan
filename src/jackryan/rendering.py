"""What the two human surfaces agree on when they describe a domain object.

The CLI and the REST route render the same three objects for the same kind of
reader — a person, or a script a person wrote. They had written those renderings
twice, and the copies had drifted: identical for a casefile, differing by a
rounding call for a search hit, and by five fields for a document. Nothing
structural kept them together; only a test comparing the surfaces caught the
parts that mattered.

This module holds what they share. It is presentation of values the service
layer has already decided, not a domain rule, which is why it lives here rather
than under `services/`.

**The agent surface is deliberately absent.** `interfaces/mcp` renders the same
objects differently on purpose — `document_id` rather than `id`, every corpus
value collapsed to one line, and no chunk summary at all, which
`tests/test_mcp_fencing.py` pins. Folding it in here would make those
differences look like drift and invite someone to "fix" them.
"""

from __future__ import annotations

from typing import Any

from .ingestion.quality_gate import read_as
from .storage.port import Casefile, Document, SearchHit


def render_casefile(casefile: Casefile) -> dict[str, Any]:
    """A casefile, as both human surfaces report it.

    No options: the two were byte-identical, and there is nothing either needs
    that the other does not.
    """
    return {
        "id": casefile.id,
        "short_id": casefile.short_id,
        "slug": casefile.slug,
        "title": casefile.title,
        "description": casefile.description,
        "created_at": casefile.created_at.isoformat(),
        "updated_at": casefile.updated_at.isoformat(),
    }


def render_document(document: Document) -> dict[str, Any]:
    """The nine fields both human surfaces report for a document.

    Nine rather than everything, because the two surfaces genuinely differ
    beyond this: REST carries `casefile_id` and `updated_at` and always emits a
    summary; the CLI adds `found_at` and `children` only when they say
    something, and omits an empty summary so a table over a corpus ingested
    without a summariser keeps its shape.

    Those differences stay with the surface that wants them, added to what this
    returns. The alternative — one function taking five flags — would be an
    interface as wide as the implementation it hides, which is the shape this
    module exists to remove rather than reproduce.
    """
    return {
        "id": document.id,
        "short_id": document.short_id,
        "filename": document.filename,
        "media_type": document.media_type,
        "byte_size": document.byte_size,
        "extractor": document.extractor,
        # How the text was obtained. The analyst decides whether a document is
        # worth re-scanning, so they need this at least as much as the assistant
        # does — and under the same name the assistant sees.
        "read_as": read_as(document.text_source),
        "characters": len(document.extracted_text),
        "created_at": document.created_at.isoformat(),
    }


def render_hit(hit: SearchHit, *, round_scores: bool) -> dict[str, Any]:
    """A search hit, as both human surfaces report it.

    One option, for the one thing the two disagreed about: the CLI rounds both
    scores to six decimal places so a terminal table stays readable, and REST
    does not, because a remote caller may want the value it was given. A
    parameter rather than two functions, so the seventeen fields they agree on
    cannot drift apart again — and a named parameter rather than a bare boolean
    at the call site, so neither reads as an accident.
    """

    def scored(value: float | None) -> float | None:
        if value is None or not round_scores:
            return value
        return round(value, 6)

    return {
        "chunk_id": hit.chunk.id,
        "document_id": hit.document.id,
        "document": hit.document.filename,
        "score": scored(hit.score),
        # Never in place of `score`: the fusion score and an uncalibrated
        # cross-encoder logit are different quantities, and the logit is
        # comparable only within this response.
        "rerank_score": scored(hit.rerank_score),
        "ranking": hit.ranking,
        "keyword_rank": hit.keyword_rank,
        "vector_rank": hit.vector_rank,
        "heading_path": hit.chunk.heading_path,
        # The context folded into what was embedded for this passage, empty
        # unless folding was on. The stored text is deliberately unchanged by
        # the fold, so this is the only place an operator can see what the
        # vector was actually built from.
        "summary": hit.chunk.summary,
        # The span of the text returned, which is wider than the matched passage
        # wherever the result was widened. The passage keeps its own span below,
        # because it is what a citation quotes.
        "char_start": hit.char_start,
        "char_end": hit.char_end,
        "matched_char_start": hit.chunk.char_start,
        "matched_char_end": hit.chunk.char_end,
        "narrowed": hit.narrowed,
        # A person reading a hit is told how its text was obtained, exactly as
        # the agent surface is. Recognition renders a word as a plausible
        # different word, and a quotation from a scan can be fluent and wrong.
        "read_as": read_as(hit.document.text_source),
        "text": hit.text,
    }
