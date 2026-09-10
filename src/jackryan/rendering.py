"""What the two human surfaces agree on when they describe a domain object.

The CLI and the REST route render the same objects for the same kind of
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

from typing import Any, Callable

from .ingestion.quality_gate import read_as
from .services.ingestion import DocumentLocationRecord, IngestReport
from .storage.port import Casefile, Document, MentionDocumentPage, SearchHit


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


def render_report(report: IngestReport) -> dict[str, Any]:
    """An ingest result, as both human surfaces return it.

    Shared rather than written twice, because the fields added here are the
    ones a caller decides whether to trust the corpus on, and two copies of
    that answer is one too many. The agent surface is absent for the same
    reason it is absent from every other renderer here: it does not ingest.
    """
    return {
        "casefile_id": report.casefile_id,
        "ingested": report.ingested,
        "failed": report.failed,
        "complete": report.complete,
        "limitations": report.limitations,
        "exhausted_by": report.exhausted_by,
        "refusals": report.refusals,
        "skipped": report.skipped,
        "outcomes": [
            {
                "path": o.path,
                "status": o.status,
                "document_id": o.document_id,
                "chunks": o.chunks,
                "detail": o.detail,
                # What this run learned about where the document was found.
                # Here rather than at each surface so the two cannot drift:
                # `ingestion-coverage` requires both human surfaces to return
                # the same fields under the same names.
                "location": o.location,
                # The followable path, because `path` above is where the file
                # was read from — and for a document produced by expansion that
                # is a scratch file already deleted by the time a caller reads
                # the response. Without this a JSON or REST caller cannot
                # recover the location the run reported, while the CLI's text
                # prints it.
                "location_path": o.location_path,
            }
            for o in report.outcomes
        ],
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


def location_paths(record: DocumentLocationRecord) -> list[str]:
    """Every recorded place, as the paths a payload carries and a person reads.

    Its own function because two callers need this list — the block below, and
    the CLI's line-by-line text output. Rendering it in both places is how
    every other pair in this module came to disagree, and it would also put
    the block's key names back into an adapter, which
    `tests/test_result_shape.py` now forbids.
    """
    return [location.path for location in record.observed_at]


def render_location_record(
    record: DocumentLocationRecord, *, drop_empty_note: bool
) -> dict[str, Any]:
    """Where a document was observed, as both human surfaces report it.

    Five keys in one place rather than two hand-built copies. A caller weighs
    this block before trusting the corpus — it says whether the record reaches
    back to when the document was stored — and two renderings of that caveat
    are free to diverge invisibly, which is the argument the record's own
    `note` already makes for wording the sentence once.

    The verdict and the count are unconditional, unlike the CLI *listing*
    qualifiers that share their names: this is one document's full record, and
    a person reading it needs `1` to mean one rather than having to infer it
    from an absent key.

    `drop_empty_note` is the one thing the two surfaces disagree about. REST
    always carries `locations_note`, because a JSON consumer branching on a
    missing key is worse served than one branching on an empty string — the
    same reason `server.serialize_document` always carries a summary. The CLI
    omits it, so a person is never shown an empty caveat. A parameter rather
    than a second copy, exactly as `render_hit`'s rounding is, because
    preserving both payloads byte-identically is the point of moving them here.
    """
    block: dict[str, Any] = {
        "locations_recorded": record.verdict,
        "locations": record.recorded.total,
        "observed_at": location_paths(record),
        "locations_truncated": record.truncated,
    }
    if record.note or not drop_empty_note:
        # Absent rather than present-and-empty where a surface asked for that.
        # The CLI's payload has never carried an empty caveat, and a change
        # that claims to move a payload is not the place to start.
        block["locations_note"] = record.note
    return block


def render_carrier_page(
    page: MentionDocumentPage,
    mention: str,
    *,
    render_row: Callable[[Document], dict[str, Any]],
) -> dict[str, Any]:
    """One page of the documents carrying an identifier, as both surfaces return it.

    The envelope is where the two surfaces had nothing to disagree about and
    everything to lose: its four paging scalars are what separates "this is
    all of them" from "this is the first page", and a surface computing one of
    them its own way agrees on every row while misleading about coverage.
    `tests/test_result_shape.py` compares all four across every surface for
    that reason; this makes two of them one definition rather than two that
    happen to match.

    `mention` is passed in rather than read off the page because it is what the
    caller asked for, while `page.value` beside it is the normalised form the
    counts are grouped by. Echoing the request is how a caller sees the two
    differ.

    `render_row` is passed in because the row is the one thing the two
    surfaces genuinely differ on: the CLI's comes from `cli._render_document`
    and REST's from `server.serialize_document`, which is `render_document`
    plus REST's own extras. A parameter rather than a flag, so a third surface
    brings its own row along instead of adding a branch here.
    """
    return {
        "mention": mention,
        "kind": page.kind,
        "value": page.value,
        # This page's rows, beside the whole carrier set below. A caller that
        # cannot tell the two apart reports the first page as coverage.
        "total": len(page.carriers),
        "offset": page.offset,
        "total_matching": page.total_matching,
        "truncated": page.truncated,
        "continue_from": page.continue_from,
        "documents": [
            {
                **render_row(carrier.document),
                # The two values that belong to the identifier rather than to
                # the document: how many times this document carries it, and
                # the passage that makes the document citable with no ranked
                # search having run.
                "mentions": carrier.mentions,
                "chunk_id": carrier.chunk_id,
            }
            for carrier in page.carriers
        ],
    }
