"""Ingestion: files in, retrievable text out.

Every rule about what may be ingested and what happens to it lives here, so
that the CLI, the REST layer, and later the agent surface all ingest the same
way.
"""

from __future__ import annotations

import hashlib
import shutil
import tempfile
import uuid
from collections import deque
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path

from ..config import Contract
from ..embedding.port import EmbedderPort
from ..errors import ConfigError, ValidationError
from ..ingestion.budget import ExpansionBudget
from ..ingestion.chunker import chunk_text
from ..ingestion.extractors import ExtractionError
from ..ingestion.quality_gate import QualityGate
from ..ingestion.router import FormatRouter
from ..mentions import default_extractors
from ..mentions.port import MentionExtractor
from ..storage.port import Chunk, Document, Mention, StorePort
from ..summarising.port import SummariserPort, SummaryError
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
    containment_path: str = ""


@dataclass(frozen=True)
class IngestReport:
    casefile_id: str
    outcomes: list[IngestOutcome]
    # Entries a container held that were not ingested — an unsafe path, a
    # too-large member, a format nothing reads. Reported rather than dropped:
    # silence here reads as "everything was ingested".
    refusals: list[str] = field(default_factory=list)
    # Which bound stopped expansion, if one did.
    exhausted_by: str | None = None

    @property
    def ingested(self) -> int:
        return sum(1 for o in self.outcomes if o.status in ("ingested", "reingested"))

    @property
    def failed(self) -> int:
        return sum(1 for o in self.outcomes if o.status == "failed")

    @property
    def complete(self) -> bool:
        """Whether everything offered was reached.

        False when a bound stopped expansion or an entry was refused. What was
        already stored stays stored — a partial ingest is a real result, but
        reporting it as a whole one is not.
        """
        return self.exhausted_by is None and not self.refusals


@dataclass(frozen=True)
class _Work:
    """One file waiting to be ingested, and where it came from."""

    path: Path
    root: Path
    # The directory this file's own children may be written into, if it has any.
    parent_id: str | None
    depth: int
    containment_path: str
    named_directly: bool


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
        budget: ExpansionBudget | None = None,
        gate: QualityGate | None = None,
        summariser: SummariserPort | None = None,
        chunk_summaries: bool = False,
        extractors: list[MentionExtractor] | None = None,
    ) -> None:
        if router is not None and gate is not None:
            raise ValueError(
                "pass either a router or a gate, not both: the router already owns one, "
                "and two would be free to disagree"
            )
        self._store = store
        self._casefiles = casefiles
        self._embedder = embedder
        self._contract = contract
        self._summariser = summariser
        # Whether the per-chunk summary is folded into what is embedded, decided
        # at the composition root where the profile switch and the summariser are
        # both known. Held as one boolean rather than re-derived here, because it
        # is the same value that decided corpus identity: if this and the
        # identity string could disagree, the store would be enforcing a rule the
        # pipeline was not following.
        self._fold_summaries = bool(chunk_summaries and summariser is not None)
        # Injectable for the same reason the gate and the embedder are: so a test
        # can drive one extractor rather than build a document that happens to
        # exercise all four. Absent, the shipped registry — which is where
        # selection lives, so adding an extractor is registering one.
        self._extractors = default_extractors() if extractors is None else extractors
        self._router = router or FormatRouter(gate=gate)
        # Held as limits rather than as a live budget: each ingest spends its
        # own. Injectable so a deployment can tune a ceiling without editing
        # code, and so a test can reach one without building a hostile archive
        # big enough to cross the real default.
        template = budget or ExpansionBudget()
        self._limits = (
            template.max_depth,
            template.max_descendants,
            template.max_extracted_bytes,
        )

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
        # An empty value would become Path("."), quietly ingesting the working
        # directory. Refuse it the way every other reference is refused.
        if not str(target).strip():
            raise ValidationError("an ingest path is required")
        path = Path(target).expanduser()
        if not path.exists():
            raise ValidationError(f"{path} does not exist")

        # Before anything is read, and asked of the router rather than of a
        # copy held here: the engine that gets verified has to be the engine the
        # extractors read with. A recognition engine that cannot be built is
        # never worked around — an instance that quietly reads scans without one
        # stores them as empty documents, which is unrecoverable without
        # noticing and reingesting.
        self._router.gate.verify()

        # The summariser gets the same treatment, and for a sharper reason: this
        # is the one request in the run that carries no evidence. `check` sends a
        # one-token probe, so it establishes that the endpoint answers, accepts
        # the credential and knows the model *before* the first document's text
        # leaves the machine. Without it the first thing a wrong endpoint
        # receives is corpus text, and it receives it once per chunk for the
        # whole casefile.
        #
        # Fatal for the run rather than per document, because it is a
        # misconfiguration: `SummariserUnavailable` is a `ConfigError` and is
        # deliberately not caught by `_ingest_work`. A thousand identical
        # per-document failures report one setting a thousand times and fix it
        # none of them.
        if self._summariser is not None:
            self._summariser.check()

        depth, descendants, extracted = self._limits
        budget = ExpansionBudget(
            max_depth=depth,
            max_descendants=descendants,
            max_extracted_bytes=extracted,
        )
        refusals: list[str] = []
        outcomes: list[IngestOutcome] = []
        # Everything expanded out of a container is written here and read back
        # through the same path checks a file on disk gets. Removed whatever
        # happens, including when the ingest raises.
        workspace = Path(tempfile.mkdtemp(prefix="jackryan-expand-"))
        try:
            queue = deque(self._initial_work(path))
            while queue:
                work = queue.popleft()
                if self._router.extractor_for(work.path) is None and not work.named_directly:
                    # Nothing reads this. Where it came from decides whether that
                    # is worth saying: a folder of mixed content is normal and
                    # stays quiet, but an entry inside a container is something
                    # the caller handed us inside something else, and silence
                    # there would read as "the archive was fully ingested".
                    if work.parent_id is not None:
                        refusals.append(
                            f"{work.containment_path}: no extractor accepts this file"
                        )
                    continue
                outcome, document = self._ingest_work(casefile.id, work)
                outcomes.append(outcome)
                if document is None:
                    continue
                queue.extend(
                    self._expand(document, work, workspace, budget, refusals)
                )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

        return IngestReport(
            casefile_id=casefile.id,
            outcomes=outcomes,
            refusals=refusals,
            exhausted_by=budget.exhausted_by,
        )

    def _initial_work(self, path: Path) -> list[_Work]:
        """What the caller pointed at, as work items.

        A directory is walked rather than made a document: a directory has no
        bytes, so it has no content identity, and inventing one from its path is
        the thing the identity rule exists to prevent. Its names survive in each
        file's containment path.
        """
        if path.is_dir():
            return [
                _Work(
                    path=child,
                    root=path,
                    parent_id=None,
                    depth=0,
                    containment_path=str(child.relative_to(path)),
                    named_directly=False,
                )
                for child in sorted(p for p in path.rglob("*") if p.is_file())
            ]
        return [
            _Work(
                path=path,
                root=path.parent,
                parent_id=None,
                depth=0,
                containment_path=path.name,
                named_directly=True,
            )
        ]

    def _expand(
        self,
        document: Document,
        work: _Work,
        workspace: Path,
        budget: ExpansionBudget,
        refusals: list[str],
    ) -> list[_Work]:
        """Materialise what a container holds, as further work.

        The container's own extraction already ran; this asks the router for its
        entries and writes each one down. Nothing here knows what format an
        entry is — that is the router's job on the next pass, which is what
        makes a format supported inside a container exactly when it is supported
        outside one.
        """
        extractor = self._router.extractor_for(work.path)
        if extractor is None or not hasattr(extractor, "iter_children"):
            return []
        if not budget.allows_depth(work.depth + 1):
            refusals.append(f"{work.containment_path}: {budget.exhausted_by}")
            return []

        nested_root = workspace / document.id
        produced: list[_Work] = []
        try:
            for index, child in enumerate(self._router.iter_children(work.path)):
                if not budget.take_child(len(child.data)):
                    refusals.append(f"{work.containment_path}: {budget.exhausted_by}")
                    break
                # The name on disk is generated, never the entry's own. Only the
                # suffix is taken from it, because the router selects on that —
                # and a suffix cannot contain a path separator, so it cannot
                # choose where the file lands. The entry's real name survives in
                # the containment path, which is display, not filesystem.
                suffix = Path(child.name).suffix.lower()
                nested_root.mkdir(parents=True, exist_ok=True)
                materialised = nested_root / f"{index:06d}{suffix}"
                materialised.write_bytes(child.data)
                produced.append(
                    _Work(
                        path=materialised,
                        root=nested_root,
                        parent_id=document.id,
                        depth=work.depth + 1,
                        containment_path=f"{work.containment_path}/{child.name}",
                        named_directly=False,
                    )
                )
        except Exception as exc:
            # One unreadable container does not fail the ingest, and does not
            # discard the entries it already yielded.
            refusals.append(
                f"{work.containment_path}: could not be expanded: "
                f"{type(exc).__name__}: {exc}"
            )
        return produced

    def _ingest_work(
        self, casefile_id: str, work: _Work
    ) -> tuple[IngestOutcome, Document | None]:
        """Ingest one work item, reporting what happened and what was stored."""
        try:
            self._check_readable(work.path, work.root)
            raw = work.path.read_bytes()
            content_hash = hashlib.sha256(raw).hexdigest()

            # Identity is content for a file off disk, content *and* where it
            # was found for one expanded out of a container: the same attachment
            # on two messages is two documents, because which message carried it
            # is itself evidence. The containment path is recorded either way —
            # it is what a person follows — but only counts toward identity for
            # an expansion, so two copies in one folder stay one document.
            identity_path = work.containment_path if work.parent_id else ""
            existing = self._store.find_document_by_hash(
                casefile_id, content_hash, identity_path
            )
            extraction = self._router.extract(work.path)

            now = _now()
            document = Document(
                # Reusing the existing identifier is what keeps references held
                # elsewhere valid across a reingest.
                id=existing.id if existing else uuid.uuid4().hex,
                casefile_id=casefile_id,
                content_hash=content_hash,
                filename=Path(work.containment_path).name,
                media_type=extraction.media_type,
                byte_size=len(raw),
                extracted_text=extraction.text,
                extractor=extraction.extractor,
                text_source=extraction.text_source,
                created_at=existing.created_at if existing else now,
                updated_at=now,
                parent_id=work.parent_id,
                containment_path=work.containment_path,
                identity_path=identity_path,
            )
            # Everything that can fail happens before anything is written.
            #
            # `document.id` is already settled above — it is the existing row's
            # id on a reingest and a fresh one otherwise — so chunking and
            # summarising need no stored row, and `upsert_document` keeps the id
            # it is given. That is what lets the whole fallible sequence run
            # first.
            #
            # It has to be this way round. Persisting first and summarising after
            # meant a summariser failure reported the document as failed while
            # its row, its text and its chunks were already committed and
            # searchable — and, because a failed document is not expanded, an
            # archive whose summary failed was stored with its entries silently
            # never ingested and the report still claiming to be complete. Every
            # other per-document failure in this method leaves nothing behind,
            # and this one now matches them.
            prepared, embeddings, mentions, document_summary = self._prepare_chunks(document)
            document = replace(
                document,
                summary=document_summary,
                summary_by=self._summariser.name if document_summary else "",
            )

            stored = self._store.upsert_document(document)
            # Mentions travel with the chunks rather than in a later call:
            # `replace_chunks` mints every chunk id afresh, so a separate write
            # afterwards would attach them to rows that had just been replaced.
            self._store.replace_chunks(stored.id, prepared, embeddings, mentions)
            return (
                IngestOutcome(
                    path=str(work.path),
                    status="reingested" if existing else "ingested",
                    document_id=stored.id,
                    chunks=len(prepared),
                    containment_path=work.containment_path,
                ),
                stored,
            )
        except ConfigError:
            # A misconfiguration, whichever call raised it — a summariser that is
            # named but cannot be reached is the case that arrives here. Re-raised
            # rather than turned into a failed document: the split between fatal
            # and per-document has to hold by type, not by which call came first,
            # or reordering these clauses would silently convert one into the
            # other. `SummariserUnavailable` is a `ConfigError` for this reason.
            raise
        except (ValidationError, ExtractionError, SummaryError) as exc:
            # `SummaryError` joins the two existing per-document failures rather
            # than degrading to an unsummarised embed. With folding on, a
            # document embedded bare carries vectors built from different input
            # from every other document's, all of the declared width and all
            # well-formed, and nothing downstream can separate them. A document
            # reported as failed can be reingested; one silently incomparable
            # with the rest cannot be found again.
            return (
                IngestOutcome(
                    path=str(work.path),
                    status="failed",
                    detail=str(exc),
                    containment_path=work.containment_path,
                ),
                None,
            )

    def _prepare_chunks(
        self, document: Document
    ) -> tuple[list[Chunk], list[list[float]], list[Mention], str]:
        """Chunk, summarise, embed and read a document, writing nothing.

        Returns the chunks, their embeddings, the mentions found in them, and the
        document's summary — which is empty whenever no summariser is configured.
        Deliberately free of writes: every fallible step of a document's ingest
        happens here, so the caller can persist only once all of them have
        succeeded and a failed document leaves nothing behind.
        """
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

        if self._fold_summaries and chunks:
            # One summary per chunk, in order, or a `SummaryError` — never a pad.
            summaries = self._summariser.summarise_chunks(
                document.extracted_text, [c.text for c in chunks]
            )
            if len(summaries) != len(chunks):
                # Checked here as well as in the implementation, because this is
                # the seam a summariser the pipeline does not control crosses.
                # zip() below would otherwise pair the surviving summaries with
                # the wrong chunks and drop the rest, silently.
                raise SummaryError(
                    f"summariser returned {len(summaries)} summaries for {len(chunks)} "
                    f"chunks of {document.filename!r}; folding cannot be paired up"
                )
            chunks = [
                replace(chunk, summary=summary)
                for chunk, summary in zip(chunks, summaries)
            ]

        # The fold, and the whole corpus-coupling argument in two expressions:
        # the embedder is given the summary and the text, and the caller's
        # `replace_chunks` is given the text alone. A folded corpus and a bare one
        # therefore hold identical `chunks.text` and different vectors, which is
        # why the summariser's identity has to be in the corpus identity the store
        # enforces — and why `chunks.summary` records what was folded in.
        embed_input = [
            f"{c.summary}\n\n{c.text}" if c.summary else c.text for c in chunks
        ]
        embeddings = self._embedder.embed_documents(embed_input)

        return chunks, embeddings, self._mentions(chunks), self._document_summary(chunks)

    def _mentions(self, chunks: list[Chunk]) -> list[Mention]:
        """Every identifier the registry finds in these chunks.

        Read from `chunk.text` rather than from the document's extracted text, so
        a mention's offsets address the chunk that a citation resolves to. The
        same identifier in two overlapping chunks is two mentions; counting them
        is the facet's job, not this one's.

        Gated on nothing. Four compiled patterns over a document's chunks cost
        milliseconds and reach no endpoint, and a facet nobody switched on is a
        facet nobody has. The absence of a switch is also deliberate the other
        way round: an extractor that turns out to be noisy has to be fixed or
        dropped, and a setting would let it survive instead.
        """
        found: list[Mention] = []
        for chunk in chunks:
            for extractor in self._extractors:
                for hit in extractor.find(chunk.text):
                    found.append(
                        Mention(
                            chunk_id=chunk.id,
                            document_id=chunk.document_id,
                            casefile_id=chunk.casefile_id,
                            kind=extractor.kind,
                            value=hit.value,
                            normalised=hit.normalised,
                            char_start=hit.char_start,
                            char_end=hit.char_end,
                            extractor=extractor.name,
                        )
                    )
        return found

    def _document_summary(self, chunks: list[Chunk]) -> str:
        """One summary of the whole document, or empty when none is configured.

        Built from the chunk summaries when folding is on and from the chunk
        texts when it is not, so a per-document summary is available without
        turning on the fold that refuses an existing corpus.

        A document with no chunks yields an empty summary without a request:
        there is nothing to summarise, and asking a model to say so costs a call
        per empty document.
        """
        if self._summariser is None or not chunks:
            return ""
        notes = [c.summary for c in chunks] if self._fold_summaries else [c.text for c in chunks]
        return self._summariser.summarise_document(notes)

    # -- queries -----------------------------------------------------------

    def list_documents(
        self, casefile_reference: str, include_expanded: bool = False
    ) -> list[Document]:
        """A casefile's documents, expansions excluded unless asked for.

        The default is what was put in rather than everything that came out of
        it: three archives holding forty thousand documents are three things an
        analyst added. Every adapter reaches the rule here, so none of them has
        to know it.
        """
        casefile = self._casefiles.resolve(casefile_reference)
        return self._store.list_documents(casefile.id, include_expanded=include_expanded)

    def list_children(self, casefile_reference: str, reference: str) -> list[Document]:
        """What was expanded directly out of one document."""
        document = self.resolve_document(casefile_reference, reference)
        return self._store.list_children(document.id)

    def containment_chain(self, casefile_reference: str, reference: str) -> list[Document]:
        """The documents from the ingested file down to this one, inclusive.

        What an analyst follows to find the same evidence by hand.
        """
        document = self.resolve_document(casefile_reference, reference)
        return [*self._store.ancestors(document.id), document]

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
