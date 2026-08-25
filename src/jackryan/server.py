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
from .app import Context, build_context
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
    return {
        "id": casefile.id,
        "short_id": casefile.short_id,
        "slug": casefile.slug,
        "title": casefile.title,
        "description": casefile.description,
        "created_at": casefile.created_at.isoformat(),
        "updated_at": casefile.updated_at.isoformat(),
    }


class IngestRequest(BaseModel):
    path: str = Field(..., description="File or folder on the instance to ingest")


def serialize_document(document: Document) -> dict[str, Any]:
    return {
        "id": document.id,
        "short_id": document.short_id,
        "casefile_id": document.casefile_id,
        "filename": document.filename,
        "media_type": document.media_type,
        "byte_size": document.byte_size,
        "extractor": document.extractor,
        "characters": len(document.extracted_text),
        "created_at": document.created_at.isoformat(),
        "updated_at": document.updated_at.isoformat(),
    }


def serialize_hit(hit: SearchHit) -> dict[str, Any]:
    return {
        "chunk_id": hit.chunk.id,
        "document_id": hit.document.id,
        "document": hit.document.filename,
        "score": hit.score,
        "keyword_rank": hit.keyword_rank,
        "vector_rank": hit.vector_rank,
        "heading_path": hit.chunk.heading_path,
        "char_start": hit.chunk.char_start,
        "char_end": hit.chunk.char_end,
        "text": hit.chunk.text,
    }


def create_app(context: Context | None = None) -> FastAPI:
    # The context is built here rather than in the lifespan because the agent
    # surface is mounted from it at construction time. Mounting later would
    # mean an app that serves REST while silently offering no tools.
    owned = context is None
    ctx = context or build_context()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.context = ctx
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
            "contract": ctx.config.contract.fingerprint(),
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
    # harness at one address and gets both. A failure to build it is fatal
    # rather than swallowed: an instance that serves REST while silently
    # advertising no tools is the worst of both outcomes.
    from .interfaces.mcp import build_mcp_server

    app.mount(
        "/mcp",
        build_mcp_server(ctx).streamable_http_app(streamable_http_path="/"),
    )

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
        request: Request, reference: str, q: str, limit: int = 10
    ) -> dict[str, Any]:
        ctx: Context = request.app.state.context
        # Embedding a query and two index scans are blocking work too.
        hits = await run_in_threadpool(ctx.search.search, reference, q, limit)
        return {"query": q, "total": len(hits), "results": [serialize_hit(h) for h in hits]}

    return app
