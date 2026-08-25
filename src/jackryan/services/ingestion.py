"""Ingestion: files in, retrievable text out.

Every rule about what may be ingested and what happens to it lives here, so
that the CLI, the REST layer, and later the agent surface all ingest the same
way.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..config import Contract
from ..embedding.port import EmbedderPort
from ..errors import ValidationError
from ..ingestion.chunker import chunk_text
from ..ingestion.extractors import ExtractionError
from ..ingestion.router import FormatRouter
from ..storage.port import Chunk, Document, StorePort
from .casefiles import CasefileService

MAX_FILE_BYTES = 512 * 1024 * 1024


@dataclass(frozen=True)
class IngestOutcome:
    """What happened to one file."""

    path: str
    status: str  # "ingested" | "reingested" | "failed"
    document_id: str | None = None
    chunks: int = 0
    detail: str = ""


@dataclass(frozen=True)
class IngestReport:
    casefile_id: str
    outcomes: list[IngestOutcome]

    @property
    def ingested(self) -> int:
        return sum(1 for o in self.outcomes if o.status in ("ingested", "reingested"))

    @property
    def failed(self) -> int:
        return sum(1 for o in self.outcomes if o.status == "failed")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class IngestionService:
    def __init__(
        self,
        store: StorePort,
        casefiles: CasefileService,
        embedder: EmbedderPort,
        contract: Contract,
        router: FormatRouter | None = None,
    ) -> None:
        self._store = store
        self._casefiles = casefiles
        self._embedder = embedder
        self._contract = contract
        self._router = router or FormatRouter()

    # -- guards ------------------------------------------------------------

    def _check_readable(self, path: Path, root: Path) -> None:
        """Refuse what cannot be read safely.

        A symlink is refused rather than followed, and a path that escapes the
        directory being ingested is refused, so that pointing at a folder
        cannot reach outside it.
        """
        if path.is_symlink():
            raise ValidationError(f"{path.name} is a symbolic link; refusing to follow it")
        resolved = path.resolve()
        if not str(resolved).startswith(str(root.resolve())):
            raise ValidationError(f"{path.name} resolves outside the ingest root")
        size = path.stat().st_size
        if size > MAX_FILE_BYTES:
            raise ValidationError(
                f"{path.name} is {size} bytes, over the {MAX_FILE_BYTES}-byte limit"
            )
        if size == 0:
            raise ValidationError(f"{path.name} is empty")

    # -- ingestion ---------------------------------------------------------

    def ingest(self, casefile_reference: str, target: str | Path) -> IngestReport:
        casefile = self._casefiles.resolve(casefile_reference)
        path = Path(target).expanduser()
        if not path.exists():
            raise ValidationError(f"{path} does not exist")

        if path.is_dir():
            root = path
            candidates = sorted(p for p in path.rglob("*") if p.is_file())
        else:
            root = path.parent
            candidates = [path]

        outcomes: list[IngestOutcome] = []
        for candidate in candidates:
            if self._router.extractor_for(candidate) is None:
                # A folder of mixed content is normal; skip quietly rather than
                # failing the whole run on a file nobody asked to ingest.
                continue
            outcomes.append(self._ingest_one(casefile.id, candidate, root))
        return IngestReport(casefile_id=casefile.id, outcomes=outcomes)

    def _ingest_one(self, casefile_id: str, path: Path, root: Path) -> IngestOutcome:
        try:
            self._check_readable(path, root)
            raw = path.read_bytes()
            content_hash = hashlib.sha256(raw).hexdigest()

            existing = self._store.find_document_by_hash(casefile_id, content_hash)
            extraction = self._router.extract(path)

            now = _now()
            document = Document(
                # Reusing the existing identifier is what keeps references held
                # elsewhere valid across a reingest.
                id=existing.id if existing else uuid.uuid4().hex,
                casefile_id=casefile_id,
                content_hash=content_hash,
                filename=path.name,
                media_type=extraction.media_type,
                byte_size=len(raw),
                extracted_text=extraction.text,
                extractor=extraction.extractor,
                created_at=existing.created_at if existing else now,
                updated_at=now,
            )
            stored = self._store.upsert_document(document)
            count = self._rebuild_chunks(stored)
            return IngestOutcome(
                path=str(path),
                status="reingested" if existing else "ingested",
                document_id=stored.id,
                chunks=count,
            )
        except (ValidationError, ExtractionError) as exc:
            return IngestOutcome(path=str(path), status="failed", detail=str(exc))

    def _rebuild_chunks(self, document: Document) -> int:
        pieces = chunk_text(
            document.extracted_text,
            max_chars=self._contract.chunk_max_chars,
            overlap_chars=self._contract.chunk_overlap_chars,
        )
        chunks = [
            Chunk(
                id=uuid.uuid4().hex,
                document_id=document.id,
                casefile_id=document.casefile_id,
                ordinal=piece.ordinal,
                heading_path=piece.heading_path,
                text=piece.text,
                char_start=piece.char_start,
                char_end=piece.char_end,
            )
            for piece in pieces
        ]
        embeddings = self._embedder.embed_documents([c.text for c in chunks])
        self._store.replace_chunks(document.id, chunks, embeddings)
        return len(chunks)

    # -- queries -----------------------------------------------------------

    def list_documents(self, casefile_reference: str) -> list[Document]:
        casefile = self._casefiles.resolve(casefile_reference)
        return self._store.list_documents(casefile.id)

    def resolve_document(self, casefile_reference: str, reference: str) -> Document:
        from ..errors import AmbiguousReferenceError, NotFoundError

        casefile = self._casefiles.resolve(casefile_reference)
        candidate = (reference or "").strip()
        if not candidate:
            raise ValidationError("a document reference is required")

        exact = self._store.get_document(candidate)
        if exact is not None and exact.casefile_id == casefile.id:
            return exact

        matches = self._store.find_documents_by_id_prefix(casefile.id, candidate)
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            shown = ", ".join(m.short_id for m in matches[:5])
            raise AmbiguousReferenceError(
                f"{reference!r} matches {len(matches)} documents ({shown}); use the full id"
            )
        raise NotFoundError(f"no document in this casefile matches {reference!r}")
