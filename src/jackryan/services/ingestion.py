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
from ..ingestion.extractors import Extraction, ExtractionError
from ..ingestion.quality_gate import QualityGate
from ..ingestion.router import FormatRouter
from ..mentions import default_extractors
from ..mentions.port import MentionExtractor
from ..storage.port import (
    Chunk,
    Document,
    DocumentLocation,
    DocumentLocationSet,
    DocumentPage,
    DocumentPassagePage,
    IngestRun,
    Mention,
    StorePort,
    join_location,
)
from ..summarising.port import SummariserPort, SummaryError
from .casefiles import CasefileService

MAX_FILE_BYTES = 512 * 1024 * 1024

# One definition each, imported by both adapters. Deliberately unlike
# `MAX_SEARCH_RESULTS`, which the agent surface sets below the service's own
# bound: a search result carries prose, a listing row carries metadata, so
# there is nothing for a second, tighter adapter bound to protect.
DEFAULT_DOCUMENT_PAGE = 50
MAX_DOCUMENT_PAGE = 200

# A passage listing row is metadata of the same weight as a document listing
# row — identifiers, a position and two integers — so it takes the same bounds
# for the same reason: there is nothing for a tighter adapter bound to protect.
DEFAULT_PASSAGE_PAGE = 50
MAX_PASSAGE_PAGE = 200

# The largest value SQLite accepts as an INTEGER bind. An offset is floored at
# zero and capped here rather than left unbounded: anything larger reaches the
# driver and raises `OverflowError`, which is not a `JackRyanError` and so
# escapes the agent surface's one error translation, making the tool raise
# instead of answering. Both published rules forbid that — an out-of-range
# argument is clamped rather than refused, and a tool returns a payload rather
# than raising. Clamping costs nothing: every offset a caller could act on is
# many orders of magnitude below this, and one this large returns an empty page
# that still reports the selection's true size.
MAX_DOCUMENT_OFFSET = 2**63 - 1

# Twenty paths at the surfaces' 200-character ceiling is at most 4,000
# characters beside a 20,000-character read, and a document observed in more
# than twenty places is characterised by its count rather than by its
# twenty-first path — which is why there is a bound and deliberately no
# continuation to follow.
MAX_DOCUMENT_LOCATIONS = 20

# What an ingest learned about where one document was found. Four values rather
# than a boolean, because "this location was not recorded" and "we cannot say
# whether it was" are different claims and only one of them is a discovery.
LOCATION_FIRST = "first"  # a new document; this is its first location
LOCATION_KNOWN = "known"  # already recorded for this document
LOCATION_NEW = "new"  # not recorded, and the record is whole: a discovery
LOCATION_UNKNOWN = "unknown"  # the document predates the record; unanswerable

LOCATIONS_COMPLETE = "complete"
LOCATIONS_UNKNOWN = "unknown"


def locations_verdict(document: Document) -> str:
    """The word every surface uses for whether a document's places are all recorded.

    The rule is the document's own `locations_are_whole`; this is only the
    vocabulary, and it lives here because the vocabulary is this layer's. Both
    listing adapters and the single-document record ask for it rather than
    mapping the boolean to a word themselves, so the two cannot come to
    disagree about which word means what.
    """
    return LOCATIONS_COMPLETE if document.locations_are_whole else LOCATIONS_UNKNOWN


@dataclass(frozen=True)
class IngestOutcome:
    """What happened to one file."""

    path: str
    status: str  # "ingested" | "reingested" | "failed"
    document_id: str | None = None
    chunks: int = 0
    detail: str = ""
    containment_path: str = ""
    # What this run learned about where the document was found: "first",
    # "known", "new", "unknown", or empty for an outcome that never got that
    # far — a failed document.
    location: str = ""
    # The followable path this run observed the document at. Carried already
    # joined so the report and the query path cannot spell one place two ways.
    location_path: str = ""


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
    # Files a folder walk offered that no registered extractor accepts. A
    # refusal is something handed to us inside something else; this is something
    # a walk found lying beside the evidence. Counted separately because the two
    # want different words, and disclosed rather than dropped: an analyst
    # searching for what one of these files said finds nothing, and silence here
    # is indistinguishable from the corpus not mentioning it.
    skipped: list[str] = field(default_factory=list)

    @property
    def ingested(self) -> int:
        return sum(1 for o in self.outcomes if o.status in ("ingested", "reingested"))

    @property
    def failed(self) -> int:
        return sum(1 for o in self.outcomes if o.status == "failed")

    @property
    def limitations(self) -> list[str]:
        """Why this run did not cover what it was offered, in the one vocabulary
        every surface uses.

        Derived rather than accumulated, and `complete` is derived from it rather
        than computed alongside it: a run reported complete while carrying a
        reason, or incomplete with none to give, is the failure this shape makes
        unreachable.

        Each line agrees with its own count. These strings are the whole of what
        an analyst is told about a shortfall, on all three surfaces, and a
        single skipped file said "1 offered files have no registered extractor"
        — which reads as machine output and invites being skimmed past, which is
        the one thing a disclosure must not invite.
        """

        def counted(n: int, singular: str, plural: str) -> str:
            return f"{n} {singular if n == 1 else plural}"

        lines: list[str] = []
        if self.exhausted_by is not None:
            lines.append(f"expansion stopped at a bound: {self.exhausted_by}")
        if self.failed:
            lines.append(
                counted(
                    self.failed,
                    "offered item failed to be read",
                    "offered items failed to be read",
                )
            )
        if self.refusals:
            lines.append(
                counted(
                    len(self.refusals),
                    "container entry was refused",
                    "container entries were refused",
                )
            )
        if self.skipped:
            lines.append(
                counted(
                    len(self.skipped),
                    "offered file has no registered extractor",
                    "offered files have no registered extractor",
                )
            )
        return lines

    @property
    def new_locations(self) -> list[str]:
        """Copies of documents this casefile already held, found somewhere new.

        Derived, like `limitations`, and deliberately **not** part of it: a file
        found in a second place was ingested, so the run covered everything it
        was offered. Folding this into `limitations` would flip `complete` to
        false and report a discovery as a shortfall.

        Each is the followable path the place was observed at, which is the
        whole of its identity: two paths that differ are two places, and one
        path reached two ways is one.
        """
        return [o.location_path for o in self.outcomes if o.location == LOCATION_NEW]

    @property
    def complete(self) -> bool:
        """Whether everything this run was offered is now in the corpus.

        Deliberately stricter than it was. It previously meant "expansion was
        not cut short", which reported a run where three of five documents
        failed as complete — and `failed` being counted separately does not
        help a caller who read `complete` and stopped.
        """
        return not self.limitations


@dataclass(frozen=True)
class MentionOffsetRepair:
    """What a pass over a casefile's mention positions examined and changed."""

    documents_examined: int
    chunks_examined: int
    chunks_unlocatable: int
    mentions_corrected: int


@dataclass(frozen=True)
class DocumentLocationRecord:
    """Where a document was observed, and whether that record may be read as whole.

    Three fields rather than a flattened copy of the store's set: the locations
    and their count are the store's, the verdict is this layer's rule, and the
    document travels with them so no adapter has to resolve it twice.
    """

    verdict: str
    document: Document
    recorded: DocumentLocationSet

    @property
    def observed_at(self) -> list[DocumentLocation]:
        """Every recorded place, earliest first, each an absolute path.

        The whole set rather than "the ones other than the document's own", and
        the difference matters twice.

        A partial list has to identify the document's own location to exclude
        it, and there is no sound way to. By position it is wrong for every
        migrated document: its `containment_path` was written before any row
        existed, so the earliest row is whatever the next ingest observed, and
        dropping it hides the only copy the record holds while every surface
        still prints a count that includes it. By comparing `containment_path`
        it is wrong for the cross-root case: two dumps sharing a relative path
        would both be discarded.

        And a partial list cannot be rendered symmetrically. The document's own
        `containment_path` is relative to whatever was ingested, and no column
        records that, so a surface showing it beside absolute additional
        locations reports a different visible set depending on which dump was
        ingested first. The complete list is the same set either way, which is
        what the identity rule promises.
        """
        return list(self.recorded.locations)

    @property
    def truncated(self) -> bool:
        return self.recorded.truncated

    @property
    def note(self) -> str:
        """The one sentence every surface says when the record cannot answer.

        Written once here rather than at each surface, for the reason
        `ingestion-coverage` gives about coverage reasons: two renderings of a
        caveat a caller weighs before trusting the corpus are free to diverge,
        and the divergence is invisible.

        It states the effect and not a cause. It used to say the document "was
        ingested before source locations were recorded", which is one reason a
        record can start late and not the only one — a write that stored the
        document and lost the observation opening its record produces the same
        state, and attributing that to an older schema would be asserting
        something this instance cannot know.
        """
        if self.verdict == LOCATIONS_COMPLETE:
            return ""
        return (
            "the record of where this document was found does not reach back to "
            "when it was stored, so the places shown may be incomplete and any "
            "others cannot be recovered"
        )


@dataclass(frozen=True)
class _Work:
    """One file waiting to be ingested, and where it came from."""

    path: Path
    root: Path
    # What the analyst pointed at, as the recorded location's qualifier. Kept
    # apart from `root` because the two diverge exactly where it matters: for a
    # document produced by expansion, `root` is the scratch directory its bytes
    # were materialised into — new on every run — while this is inherited from
    # the top-level file, so a container reingested from the same place records
    # no new location.
    source_root: str
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

        started_at = _now()
        # What the casefile already held before this run wrote anything. Read
        # here and nowhere else: it is the whole basis on which a later reader
        # can tell "no run has reported a problem" from "no run accounts for
        # this evidence".
        documents_before = self._store.casefile_statistics(casefile.id).documents

        depth, descendants, extracted = self._limits
        budget = ExpansionBudget(
            max_depth=depth,
            max_descendants=descendants,
            max_extracted_bytes=extracted,
        )
        refusals: list[str] = []
        skipped: list[str] = []
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
                    # Nothing reads this. Where it came from decides which list
                    # it lands in: an entry inside a container is something the
                    # caller handed us inside something else, and is a refusal;
                    # a file a folder walk found is skipped. Neither is silent
                    # any more — silence here reads as "everything was
                    # ingested", which is the claim this whole report exists to
                    # stop being made by accident.
                    if work.parent_id is not None:
                        refusals.append(
                            f"{work.containment_path}: no extractor accepts this file"
                        )
                    else:
                        skipped.append(work.containment_path)
                    continue
                outcome, document, extraction = self._ingest_work(casefile.id, work)
                outcomes.append(outcome)
                if extraction is not None:
                    # What the reader itself would not touch. Prefixed with the
                    # container's own path, so a refusal reads as the chain a
                    # person would follow, exactly as a child's containment path
                    # does. Recorded even when the document later failed: those
                    # entries are then the only record of what the container
                    # held.
                    refusals.extend(
                        f"{work.containment_path}/{reason}" for reason in extraction.refusals
                    )
                if document is None:
                    continue
                queue.extend(
                    self._expand(document, work, workspace, budget, refusals, extraction)
                )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

        report = IngestReport(
            casefile_id=casefile.id,
            outcomes=outcomes,
            refusals=refusals,
            exhausted_by=budget.exhausted_by,
            skipped=skipped,
        )
        # Recorded after the loop and never in a `finally`: a run that raised
        # part way is deliberately left unrecorded, because recording it would
        # mean deciding what a half-run covered and any answer is a guess. What
        # makes that absence *detectable* is the pair of document counts either
        # side of this run — the next run's `documents_before` will exceed this
        # run's `documents_after`, and `continuity_breaks` reports the gap.
        # Absence alone was not enough: it made only a *first* unrecorded run
        # visible, so an abort after any clean run left the casefile reading
        # `complete` with offered files missing.
        #
        # A failure to write this row is not swallowed either: an insert of
        # eleven values that fails means the store is broken, and the caller has
        # to hear it. It is also the one failure the gap catches for free — the
        # next run sees documents this one never accounted for.
        self._store.record_ingest_run(
            IngestRun(
                id=uuid.uuid4().hex,
                casefile_id=casefile.id,
                started_at=started_at,
                finished_at=_now(),
                documents_before=documents_before,
                documents_after=self._store.casefile_statistics(casefile.id).documents,
                items_ingested=report.ingested,
                items_failed=report.failed,
                entries_refused=len(report.refusals),
                files_without_extractor=len(report.skipped),
                exhausted_by=report.exhausted_by or "",
            )
        )
        return report

    def _initial_work(self, path: Path) -> list[_Work]:
        """What the caller pointed at, as work items.

        A directory is walked rather than made a document: a directory has no
        bytes, so it has no content identity, and inventing one from its path is
        the thing the identity rule exists to prevent. Its names survive in each
        file's containment path.
        """
        # Resolved, because a location is recorded to be followed later and a
        # path relative to whatever directory the command happened to run in
        # cannot be. This is the qualifier that makes two dumps each holding
        # `note.txt` at their top level two locations rather than one.
        if path.is_dir():
            source_root = str(path.resolve())
            return [
                _Work(
                    path=child,
                    root=path,
                    source_root=source_root,
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
                source_root=str(path.parent.resolve()),
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
        extraction: Extraction,
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
        stopped_by_budget = False
        expansion_failed: Exception | None = None
        try:
            for index, child in enumerate(self._router.iter_children(work.path)):
                if not budget.take_child(len(child.data)):
                    refusals.append(f"{work.containment_path}: {budget.exhausted_by}")
                    stopped_by_budget = True
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
                        # Inherited, deliberately not `nested_root`: that is a
                        # scratch directory recreated on every run, so recording
                        # it would insert a fresh location row and report a
                        # false discovery each time this container was
                        # reingested. The top-level root plus this entry's
                        # containment path is also what a person actually
                        # follows — open that archive, find this entry.
                        source_root=work.source_root,
                        parent_id=document.id,
                        depth=work.depth + 1,
                        containment_path=f"{work.containment_path}/{child.name}",
                        named_directly=False,
                    )
                )
        except Exception as exc:
            # One unreadable container does not fail the ingest, and does not
            # discard the entries it already yielded.
            expansion_failed = exc
            refusals.append(
                f"{work.containment_path}: could not be expanded: "
                f"{type(exc).__name__}: {exc}"
            )

        # The listing and the delivery are two passes over one archive, and a
        # reader that drops an entry between them — over the per-entry ceiling,
        # unreadable, a member `extractfile` declines — leaves the container's
        # own text naming a document that will never exist. Reconciled against
        # the count the extractor published rather than re-deciding the ceiling
        # here, so there is no second definition of what is too large.
        #
        # Its reach is exactly the extractors that publish `entries`: the three
        # archive formats do, the mail extractors do not and are skipped by the
        # `isdigit` guard rather than compared against zero. That is a real
        # limit, not a detail — `test_every_container_extractor_publishes_its_entry_count`
        # is what stops a new container format losing the reconciliation by
        # omitting one dictionary key.
        #
        # Not reported when a bound stopped this container or its expansion
        # raised: both already appended a refusal saying so, and a shortfall is
        # their consequence rather than a second finding.
        listed = extraction.metadata.get("entries", "")
        if not stopped_by_budget and expansion_failed is None and listed.isdigit():
            missing = int(listed) - len(produced)
            if missing > 0:
                refusals.append(
                    f"{work.containment_path}: {missing} of {listed} listed entries "
                    "were not delivered by the reader"
                )
        return produced

    def _ingest_work(
        self, casefile_id: str, work: _Work
    ) -> tuple[IngestOutcome, Document | None, Extraction | None]:
        """Ingest one work item, reporting what happened and what was stored.

        The `Extraction` is bound before the `try` and returned on the failure
        path too, so a container whose own read succeeded but whose document
        then failed still hands back the entries its reader refused. Those
        refusals are then the only record of what the container held, and
        returning `None` here would have discarded them — which the caller's
        comment already promised not to do.
        """
        extraction: Extraction | None = None
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
            # summarising need no stored row, and `store_document` keeps the id
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

            observed_at_path = join_location(work.source_root, work.containment_path)
            # The document and the observation that opens its record are one
            # write. Two writes left a window in which the document survived
            # asserting a whole history with nothing recorded — and the next
            # ingest from a different root then supplied the only place the
            # record held, so it read as the whole story while the place this
            # document actually came from was never written and never could be.
            #
            # Whether the record was already whole is read from `existing`,
            # before this write changes it: nothing may be called a discovery
            # for a document whose earlier history is missing.
            existing_record_was_whole = existing is not None and existing.locations_are_whole
            stored, location_is_new = self._store.store_document(
                document, observed_at_path, now
            )
            # Mentions travel with the chunks rather than in a later call:
            # `replace_chunks` mints every chunk id afresh, so a separate write
            # afterwards would attach them to rows that had just been replaced.
            self._store.replace_chunks(stored.id, prepared, embeddings, mentions)
            if existing is None:
                location = LOCATION_FIRST
            elif not existing_record_was_whole:
                # The record cannot answer for this document — it predates the
                # record, or the write that should have opened it did not
                # complete. This place may well be one it was already observed
                # at, so calling it a discovery would be a finding this instance
                # cannot support.
                location = LOCATION_UNKNOWN
            elif location_is_new:
                location = LOCATION_NEW
            else:
                location = LOCATION_KNOWN
            return (
                IngestOutcome(
                    path=str(work.path),
                    status="reingested" if existing else "ingested",
                    document_id=stored.id,
                    chunks=len(prepared),
                    containment_path=work.containment_path,
                    location=location,
                    location_path=observed_at_path,
                ),
                stored,
                extraction,
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
                extraction,
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

    # -- repair ------------------------------------------------------------

    def repair_mention_offsets(self, casefile_reference: str) -> MentionOffsetRepair:
        """Recompute where each mention sits in its document, from the stored text.

        A mention's document position is derived when its chunk is written, from
        that chunk's recorded start. Chunks written while the recorded start
        named the untrimmed window are wrong by the trimmed whitespace, so two
        overlapping chunks place one occurrence twice and the inventory counts it
        twice. Recomputing the position corrects that without re-extracting,
        re-chunking or re-embedding anything.

        Operator-invoked rather than a migration step: locating a stored text
        inside the span its offsets name is not expressible in the schema
        ladder's statements, and a corpus is not rewritten in place because
        somebody opened it.

        Writes only the derived position. Where a chunk's stored text is not
        found inside its own span — a half-completed ingest leaving new text
        against old offsets, the same inconsistency `Windower._slice` declines to
        widen — that chunk is counted and left alone: a position guessed for it
        would resolve and be wrong.
        """
        casefile = self._casefiles.resolve(casefile_reference)
        documents = chunks_seen = unlocatable = corrected = 0
        for document_id in self._store.list_document_ids(casefile.id):
            document = self._store.get_document(document_id)
            if document is None:
                continue
            documents += 1
            text = document.extracted_text
            starts: dict[str, int] = {}
            for chunk in self._store.list_document_chunks(document_id):
                chunks_seen += 1
                # Searched inside the span the offsets name and never in the
                # whole document: the same text can occur elsewhere, and a match
                # found there would move the mention into a passage nobody chose.
                within = text[chunk.char_start : chunk.char_end].find(chunk.text)
                if within < 0:
                    unlocatable += 1
                    continue
                starts[chunk.id] = chunk.char_start + within
            corrected += self._store.recompute_mention_offsets(starts)
        return MentionOffsetRepair(
            documents_examined=documents,
            chunks_examined=chunks_seen,
            chunks_unlocatable=unlocatable,
            mentions_corrected=corrected,
        )

    # -- queries -----------------------------------------------------------

    def list_documents(
        self, casefile_reference: str, include_expanded: bool = False
    ) -> list[Document]:
        """A casefile's documents, expansions excluded unless asked for.

        The default is what was put in rather than everything that came out of
        it: three archives holding forty thousand documents are three things an
        analyst added. Every adapter reaches the rule here, so none of them has
        to know it.

        Adapters use `list_document_page`; this returns the whole casefile, and
        loads every document's text to do it.
        """
        casefile = self._casefiles.resolve(casefile_reference)
        return self._store.list_documents(casefile.id, include_expanded=include_expanded)

    def list_document_page(
        self,
        casefile_reference: str,
        parent_reference: str = "",
        include_expanded: bool = False,
        offset: int = 0,
        limit: int = DEFAULT_DOCUMENT_PAGE,
    ) -> DocumentPage:
        """A bounded page of a casefile's documents, or of one container's contents.

        An empty `parent_reference` lists what an analyst put in, or everything
        in the casefile when `include_expanded` is set. A reference lists what
        was expanded directly out of that document, and takes precedence:
        children are expansions, so the two selections cannot contradict each
        other, and the returned page names which one it is rather than leaving
        an agent to infer it.

        **Both bounds are clamped, not just the limit**, and both ends of each:
        `limit` to between 1 and `MAX_DOCUMENT_PAGE`, `offset` to between 0 and
        `MAX_DOCUMENT_OFFSET`. Clamped rather than refused, as every other bound
        on this surface is — the agent surface has no request-validation layer
        above it and an over-large argument is a harmless mistake. The offset's
        upper bound is the one that is easy to assume unnecessary: it was
        missing, and a value above SQLite's integer range reached the driver and
        raised `OverflowError`, which is not a `JackRyanError`, so the tool
        raised instead of answering.

        **The second parameter is a reference, not `include_expanded`** — unlike
        `list_documents`, whose flag sits second. The order is the one the agent
        surface forwards positionally through `anyio.to_thread.run_sync`, which
        passes no keywords, so it must not be rearranged. Migrating a
        `list_documents(cf, True)` call by changing the method name alone passes
        `True` as `parent_reference` and raises `AttributeError` on `.strip()`,
        which is not a `JackRyanError` and so escapes both adapters'
        translations. Pass `include_expanded=` by keyword.
        """
        casefile = self._casefiles.resolve(casefile_reference)
        bounded = max(1, min(int(limit), MAX_DOCUMENT_PAGE))
        start = min(max(0, int(offset)), MAX_DOCUMENT_OFFSET)

        # Checked before resolving, because `resolve_document` refuses an empty
        # reference — and an omitted parent is the default, not a mistake.
        candidate = (parent_reference or "").strip()
        parent = (
            self.resolve_document(casefile_reference, candidate) if candidate else None
        )
        page = self._store.list_document_page(
            casefile.id,
            include_expanded=include_expanded,
            parent_id=parent.id if parent else None,
            offset=start,
            limit=bounded,
        )
        if parent is None:
            return page
        # `resolve_document`'s queries select `*` and alias no `child_count`, so
        # the resolved parent reports zero children while the page's own
        # `total_matching` — counted under exactly the parent's direct-child
        # predicate — says otherwise. Nothing renders it today, but handing back
        # an object that contradicts itself is the very defect this change fixes
        # for rows: a container reported as a leaf.
        return replace(page, parent=replace(parent, child_count=page.total_matching))

    def list_document_passage_page(
        self,
        casefile_reference: str,
        reference: str,
        offset: int = 0,
        limit: int = DEFAULT_PASSAGE_PAGE,
    ) -> DocumentPassagePage:
        """A bounded page of one document's stored passages, in reading order.

        This is what makes a document reached by *browsing* citable.
        `case_cite` takes a passage identifier, and until this existed no
        surface handed one back for a document reached through the document
        listing — a read returns text, spans and provenance, and no passage. So
        the container journey had to run a ranked search to recover an id
        before it could cite what it had just read, which puts the citation back
        behind the one mechanism container navigation exists to route around: an
        attachment's text is short, its name is generic, and it competes against
        the whole corpus.

        It ranks nothing and scores nothing. The order is the document's own, so
        this is an index of a document rather than a judgement about it — which
        passage matters is the caller's to decide, from the document's structure
        and from reading a candidate through `passage_window`.

        **On this service rather than on `SearchService`**, though a passage is a
        retrieval object, because the argument is a *document* reference and
        `resolve_document` is the one definition of how one is resolved inside a
        casefile — prefixes, the ambiguity refusal and the compartment boundary
        included. Giving `SearchService` its own would be a second definition of
        the rule that confines this call, which is the failure the whole
        service layer is arranged to prevent.

        Both bounds are clamped at both ends, as every bound on this surface is:
        `limit` to between 1 and `MAX_PASSAGE_PAGE`, `offset` to between 0 and
        `MAX_DOCUMENT_OFFSET`. The offset's upper bound is the one that looks
        unnecessary and is not — a value above SQLite's integer range reaches
        the driver and raises `OverflowError`, which is not a `JackRyanError`,
        so the tool would raise instead of answering.

        The resolved document travels back on the page, as a container does on a
        document listing, so a surface can name what it indexed without
        resolving the reference a second time.
        """
        document = self.resolve_document(casefile_reference, reference)
        bounded = max(1, min(int(limit), MAX_PASSAGE_PAGE))
        start = min(max(0, int(offset)), MAX_DOCUMENT_OFFSET)
        page = self._store.list_document_passage_page(document.id, start, bounded)
        return replace(page, document=document)

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

    def document_locations(
        self, casefile_reference: str, reference: str
    ) -> DocumentLocationRecord:
        """Where one document's bytes were observed, bounded, with a verdict.

        The verdict is a rule of this layer rather than of the store, the same
        way a casefile's coverage verdict is: the store holds the rows, and what
        those rows may be claimed to mean is domain reasoning. Resolution goes
        through `resolve_document`, so casefile scoping and 8-character prefixes
        are inherited rather than restated.

        A record is whole exactly when it has existed since the document was
        created, which is what comparing the earliest observation against
        `created_at` establishes. Derived rather than read from a stored claim,
        because a stored claim is a second copy of this fact written in a
        different transaction from the rows it describes, and the two can
        disagree — which is how a document that lost its first observation came
        to report the one place a later ingest happened to find as its whole
        history.

        The rule itself lives on the document, as `locations_are_whole`, and is
        asked rather than restated here. Spelling it in both places is the
        two-copies-can-disagree defect that retiring the stored claim was meant
        to end, one level up — so every query that returns a document for a
        caller to judge selects what the rule needs.
        """
        document = self.resolve_document(casefile_reference, reference)
        recorded = self._store.document_locations(document.id, MAX_DOCUMENT_LOCATIONS)
        verdict = locations_verdict(document)
        return DocumentLocationRecord(
            verdict=verdict, document=document, recorded=recorded
        )
