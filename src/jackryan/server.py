"""REST adapter.

Deliberately thin: it translates HTTP to service calls and typed errors to
status codes, and holds no rule of its own. Anything that looks like a domain
decision here belongs in the service layer instead.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import __version__
from .ingestion.containers import rar_status
from .ingestion.legacy_office import converter_status
from .app import Context, build_context
from .rendering import render_casefile, render_document, render_hit
from .errors import (
    AmbiguousReferenceError,
    ConflictError,
    JackRyanError,
    NotFoundError,
    ValidationError,
)
from .storage.port import Casefile, Document, SearchHit

_STATUS_FOR_ERROR = {
    ValidationError: 400,
    NotFoundError: 404,
    ConflictError: 409,
    AmbiguousReferenceError: 409,
}


class CasefileCreate(BaseModel):
    title: str = Field(..., description="Human-readable name for the investigation")
    description: str = Field("", description="What this casefile is for")
    slug: str | None = Field(None, description="Optional explicit handle; derived from title if omitted")


class CasefileUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    slug: str | None = None


def serialize(casefile: Casefile) -> dict[str, Any]:
    return render_casefile(casefile)


class IngestRequest(BaseModel):
    path: str = Field(..., description="File or folder on the instance to ingest")


def serialize_document(document: Document) -> dict[str, Any]:
    """The shared fields, plus the three a remote caller gets and the CLI does not.

    `casefile_id` because a response may be read without the request that
    produced it; `updated_at` because a caller polling for change needs it; and
    the summary whether or not there is one, because a JSON consumer branching
    on a missing key is worse served than one branching on an empty string.
    """
    return {
        **render_document(document),
        "casefile_id": document.casefile_id,
        # Model-written, not the document's own words, which is why the producer
        # travels beside it. Empty unless a summariser was configured at ingest.
        "summary": document.summary,
        "summary_by": document.summary_by,
        "updated_at": document.updated_at.isoformat(),
    }


def serialize_hit(hit: SearchHit) -> dict[str, Any]:
    """Unrounded, unlike the CLI: a remote caller may want the value it was given."""
    return render_hit(hit, round_scores=False)


def create_app(context: Context | None = None) -> FastAPI:
    # The context is built here rather than in the lifespan because the agent
    # surface is mounted from it at construction time. Mounting later would
    # mean an app that serves REST while silently offering no tools.
    owned = context is None
    ctx = context or build_context()

    # Built here, not inside the lifespan, because the app is mounted from it
    # at construction time.
    from .interfaces.mcp import build_mcp_server

    from mcp.server.transport_security import TransportSecuritySettings

    mcp_app = build_mcp_server(ctx).streamable_http_app(
        streamable_http_path="/",
        # Rebinding protection stays on; which names are acceptable is a
        # deployment fact, so it comes from configuration.
        transport_security=TransportSecuritySettings(
            allowed_hosts=list(ctx.config.profile.mcp_allowed_hosts),
            allowed_origins=list(ctx.config.profile.mcp_allowed_hosts),
        ),
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.context = ctx
        # Starlette does not run a mounted sub-app's lifespan, and the MCP
        # session manager is started by exactly that lifespan. Without this the
        # mount accepts requests and fails every one of them.
        async with mcp_app.router.lifespan_context(mcp_app):
            try:
                yield
            finally:
                if owned:
                    ctx.close()

    app = FastAPI(
        title="Jack Ryan",
        version=__version__,
        summary="A self-hosted investigation workbench",
        lifespan=lifespan,
    )

    @app.exception_handler(JackRyanError)
    async def handle_domain_error(_: Request, exc: JackRyanError) -> JSONResponse:
        status = next(
            (code for kind, code in _STATUS_FOR_ERROR.items() if isinstance(exc, kind)), 500
        )
        return JSONResponse(status_code=status, content={"error": exc.code, "message": str(exc)})

    @app.get("/health")
    async def health(request: Request) -> dict[str, Any]:
        ctx: Context = request.app.state.context
        return {
            "status": "ok",
            "version": __version__,
            "profile": ctx.config.profile.name,
            # The value the store enforces, not the contract alone: an
            # operator comparing this against a refusal must be looking at
            # the same string the guard compared.
            "contract": ctx.corpus_fingerprint,
            # Same key and same two-valued vocabulary as `jackryan status`:
            # one answer about the host, whichever surface is asked.
            "legacy_office": converter_status(),
            # Same key and same two-valued vocabulary as `jackryan status`.
            "rar": rar_status(),
        }

    @app.get("/api/casefiles")
    async def list_casefiles(request: Request) -> dict[str, Any]:
        ctx: Context = request.app.state.context
        casefiles = ctx.casefiles.list()
        return {"total": len(casefiles), "casefiles": [serialize(c) for c in casefiles]}

    @app.post("/api/casefiles", status_code=201)
    async def create_casefile(request: Request, payload: CasefileCreate) -> dict[str, Any]:
        ctx: Context = request.app.state.context
        casefile = ctx.casefiles.create(
            title=payload.title, description=payload.description, slug=payload.slug
        )
        return serialize(casefile)

    @app.get("/api/casefiles/{reference}")
    async def get_casefile(request: Request, reference: str) -> dict[str, Any]:
        ctx: Context = request.app.state.context
        return serialize(ctx.casefiles.resolve(reference))

    @app.patch("/api/casefiles/{reference}")
    async def update_casefile(
        request: Request, reference: str, payload: CasefileUpdate
    ) -> dict[str, Any]:
        ctx: Context = request.app.state.context
        casefile = ctx.casefiles.update(
            reference,
            title=payload.title,
            description=payload.description,
            slug=payload.slug,
        )
        return serialize(casefile)

    @app.delete("/api/casefiles/{reference}")
    async def delete_casefile(request: Request, reference: str) -> dict[str, Any]:
        ctx: Context = request.app.state.context
        return {"deleted": serialize(ctx.casefiles.delete(reference))}

    # The agent surface rides the same process as REST, so an analyst points one
    # harness at one address and gets both.
    app.mount("/mcp", mcp_app)

    @app.post("/api/casefiles/{reference}/ingest")
    async def ingest(request: Request, reference: str, payload: IngestRequest) -> dict[str, Any]:
        ctx: Context = request.app.state.context
        # Ingestion is long and synchronous; running it on the event loop would
        # freeze every other request for its duration.
        report = await run_in_threadpool(ctx.ingestion.ingest, reference, payload.path)
        return {
            "casefile_id": report.casefile_id,
            "ingested": report.ingested,
            "failed": report.failed,
            "outcomes": [
                {
                    "path": o.path,
                    "status": o.status,
                    "document_id": o.document_id,
                    "chunks": o.chunks,
                    "detail": o.detail,
                }
                for o in report.outcomes
            ],
        }

    @app.get("/api/casefiles/{reference}/documents")
    async def list_documents(request: Request, reference: str) -> dict[str, Any]:
        ctx: Context = request.app.state.context
        documents = ctx.ingestion.list_documents(reference)
        return {"total": len(documents), "documents": [serialize_document(d) for d in documents]}

    @app.get("/api/casefiles/{reference}/documents/{document_reference}")
    async def get_document(
        request: Request, reference: str, document_reference: str
    ) -> dict[str, Any]:
        ctx: Context = request.app.state.context
        return serialize_document(ctx.ingestion.resolve_document(reference, document_reference))

    @app.get("/api/casefiles/{reference}/search")
    async def search(
        request: Request, reference: str, q: str, limit: int = 10, mention: str = ""
    ) -> dict[str, Any]:
        ctx: Context = request.app.state.context
        # Embedding a query and two index scans are blocking work too.
        # A keyword argument here, unlike the MCP surface's positional one:
        # `run_in_threadpool` forwards keywords and `anyio.to_thread.run_sync`
        # does not.
        hits = await run_in_threadpool(
            ctx.search.search, reference, q, limit, mention=mention
        )
        return {
            "query": q,
            "mention": mention,
            "total": len(hits),
            "ranking": hits[0].ranking if hits else "fusion",
            "results": [serialize_hit(h) for h in hits],
        }

    @app.get("/api/casefiles/{reference}/mentions")
    async def mentions(
        request: Request, reference: str, kind: str = "", limit: int = 50
    ) -> dict[str, Any]:
        """The identifiers a casefile contains, counted."""
        ctx: Context = request.app.state.context
        facets = await run_in_threadpool(
            ctx.search.mention_facets, reference, kind, limit
        )
        return {
            "kind": kind,
            "total": len(facets),
            "results": [
                {
                    "kind": f.kind,
                    "value": f.value,
                    "mentions": f.mentions,
                    "documents": f.documents,
                }
                for f in facets
            ],
        }

    return app
