"""REST adapter.

Deliberately thin: it translates HTTP to service calls and typed errors to
status codes, and holds no rule of its own. Anything that looks like a domain
decision here belongs in the service layer instead.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
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
from .storage.port import Casefile

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


def create_app(context: Context | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.context = context or build_context()
        try:
            yield
        finally:
            if context is None:
                app.state.context.close()

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

    return app
