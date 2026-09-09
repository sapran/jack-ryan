"""The storage seam.

Every persistence call in the service layer goes through ``StorePort``. This
is the one deliberate abstraction in the system: it exists so a heavier engine
can replace the embedded store later without the service layer noticing.

The port speaks in domain objects, never in rows or SQL, and it performs no
validation — rules belong in the service layer so that every adapter inherits
them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath
from typing import Protocol


@dataclass(frozen=True)
class Document:
    """An ingested file: its bytes' identity, and the text recovered from it."""

    id: str
    casefile_id: str
    content_hash: str
    filename: str
    media_type: str
    byte_size: int
    extracted_text: str
    extractor: str
    created_at: datetime
    updated_at: datetime
    # Which rung of the extraction quality gate produced `extracted_text`: the
    # document's own text layer, recognition, a vision model, or direct parsing
    # for a format with no page images. Empty only for a document this codebase
    # did not write. Text recovered by recognition can be fluent and wrong, so
    # this travels with the text all the way to the agent.
    text_source: str = ""
    # The model-written summary of the whole document, empty when none was
    # written. Prose no human wrote, which is why every surface that shows it
    # fences it and names its author rather than presenting it as the
    # document's own words.
    summary: str = ""
    # Which summariser wrote `summary`. Recorded per document where the chunk's
    # producer deliberately is not, because the per-document summary moves no
    # vector and is therefore outside corpus identity — so nothing else in the
    # store records who wrote it. A surface reporting whichever summariser the
    # instance happens to be configured with today as the author of a summary
    # written before that model changed would be asserting something it cannot
    # know. The same rule as `text_source` above: what the fingerprint does not
    # guard, the per-document record makes findable.
    summary_by: str = ""
    # Absent for a file ingested directly; set for one found inside another.
    parent_id: str | None = None
    # The names from the ingested file down to this one, joined — including the
    # directories a folder walk passed through. What an analyst follows to find
    # the same evidence by hand. Display, not identity.
    containment_path: str = ""
    # The part of that path which counts toward identity: empty for a file
    # ingested directly, the containment path for one expanded out of a
    # container. Two copies in one folder are one document; the same attachment
    # on two messages is two.
    identity_path: str = ""
    # How many documents were expanded directly out of this one. Carried so a
    # listing can show that there is more to reach without fetching it.
    child_count: int = 0
    # How many places this document's bytes were observed at, and when the
    # earliest of them was recorded. Carried so a listing can mark a file found
    # in several places without fetching them — the `child_count` precedent —
    # and populated only when a query aliases them.
    location_count: int = 0
    first_observed_at: datetime | None = None

    @property
    def short_id(self) -> str:
        return self.id[:8]

    @property
    def is_expanded(self) -> bool:
        """Whether this document came out of another rather than off disk."""
        return self.parent_id is not None

    @property
    def locations_are_whole(self) -> bool:
        """Whether every place these bytes were observed at is recorded.

        Derived, and deliberately not stored. It is true exactly when the record
        has existed since the document was created, which is what comparing the
        earliest observation against `created_at` establishes.

        A stored claim would be a second copy of this fact, in a different
        transaction from the rows it describes, and the two can disagree: an
        instance that wrote the claim and then failed before writing the
        observation left a document asserting a history it did not have, and one
        later observation from somewhere else then read as the whole story.

        Answers `False` when nothing is recorded and when nothing was aliased,
        which is the safe direction: a caller that did not ask for the counts
        cannot be told the record is whole.
        """
        return self.first_observed_at is not None and self.first_observed_at <= self.created_at

    @property
    def additional_locations(self) -> int:
        """Recorded places other than the one this document reports.

        One expression for what used to be two thresholds. A document whose
        record is whole holds a row for its own location, so a second place
        means two rows; one whose record is not whole has no row for its own, so
        its first row is already somewhere else. Both are the same statement
        about additional places, which is why adapters ask this rather than
        each carrying the arithmetic.
        """
        return max(0, self.location_count - (1 if self.locations_are_whole else 0))


def join_location(source_root: str, containment_path: str) -> str:
    """The path a file was observed at: what was ingested, plus the way down.

    One definition, called by the ingest write and by the report it returns, so
    the two cannot spell a location differently. The result is the location's
    whole identity — two observations that join to the same path are one place,
    however each was reached.
    """
    return str(PurePosixPath(source_root) / containment_path)


@dataclass(frozen=True)
class DocumentLocation:
    """One place a document's bytes were observed.

    One path, not a root and a path within it. The pair discriminated
    observations rather than places: the same file reached by walking a folder
    and by naming it directly produced two pairs for one file. The path is the
    place, and it still separates two dumps that each hold one file at their top
    level, because those paths differ.

    It is absolute, so it is followable by hand — which is the standard the
    containment path is already held to — and for a document produced by
    expansion it runs from the top-level file that was ingested down the
    containment chain to it.
    """

    path: str
    first_seen_at: datetime


@dataclass(frozen=True)
class DocumentLocationSet:
    """A document's recorded source locations, bounded, and how many there are.

    Facts only. Whether the set may be treated as whole is the service layer's
    rule, and lives with the verdict rather than here — the same split
    `IngestionCoverage` and `CasefileCoverage` already make.
    """

    locations: list[DocumentLocation]
    total: int

    @property
    def truncated(self) -> bool:
        return len(self.locations) < self.total


@dataclass(frozen=True)
class Chunk:
    """A retrievable span of a document, locatable in its extracted text."""

    id: str
    document_id: str
    casefile_id: str
    ordinal: int
    heading_path: str
    text: str
    char_start: int
    char_end: int
    # The context that was folded into what was embedded for this chunk, empty
    # when nothing was folded. `text` above is deliberately left unchanged by
    # the fold — it stays the chunk's own text — so without this column nothing
    # on disk would record what the vector was actually built from. No producer
    # travels beside it: this is non-empty only when folding was on, and that
    # is exactly the case where corpus identity already names the summariser,
    # so the store holds that fact once rather than twice.
    summary: str = ""

    @property
    def short_id(self) -> str:
        return self.id[:8]


@dataclass(frozen=True)
class PassageReference:
    """A stored passage addressed without its text, for indexing a document.

    Deliberately not a `Chunk`, and the difference is the whole reason it
    exists. A listing of a document's passages that carried each one's text
    would pay for the document's entire stored corpus in order to report its
    shape — the same cost `list_document_ids` exists to avoid one level up, and
    the one `list_document_page` selects narrow rows to avoid. Handing back a
    `Chunk` with `text=""` instead would be worse than expensive: a passage
    holding no text and a passage whose text was not fetched would be the same
    object, and only one of those is a corpus defect.

    `characters` is read from the stored text rather than derived from the span.
    The two agree exactly on a corpus ingested after the chunker began
    recording the trimmed span, and disagree on an older one, whose rows still
    describe the untrimmed window. This is what a caller would receive if it
    read the passage, so it comes from the passage.
    """

    id: str
    document_id: str
    ordinal: int
    heading_path: str
    char_start: int
    char_end: int
    characters: int

    @property
    def short_id(self) -> str:
        return self.id[:8]


@dataclass(frozen=True)
class Window:
    """A span of a document's text that contains a matched chunk.

    Taken as one contiguous slice of the document's extracted text, never
    assembled by joining chunk texts: chunks overlap by configuration, so
    joining them repeats the overlap, and a chunk's stored text has been
    stripped of whitespace its offsets still describe. The slice is what a
    person reading the document at those offsets would see, which is what makes
    the citation checkable by hand.
    """

    text: str
    char_start: int
    char_end: int


@dataclass(frozen=True)
class SearchHit:
    """One ranked result, carrying what is needed to use and to verify it."""

    chunk: Chunk
    document: Document
    score: float
    keyword_rank: int | None
    vector_rank: int | None
    # Set when the text returned is wider than the matched chunk. `None` means
    # the two are the same, which is what every caller saw before windows
    # existed.
    window: Window | None = None
    # Whether this result's text was cut back — because widening it would have
    # repeated text an earlier result already carried, or because the response's
    # character bound had been reached. Said per result so a response can report
    # it without the caller inferring it from lengths.
    narrowed: bool = False
    # The reranker's score for this result, where one ran. Never replaces
    # `score`, which stays the fusion score: an uncalibrated logit and a
    # reciprocal-rank sum are different quantities, and overwriting one with the
    # other would destroy the evidence that fusion ran at all.
    rerank_score: float | None = None
    # Which stage decided this result's position: `fusion`, `rerank`, or
    # `rerank-unavailable` when a reranker was configured and could not score
    # this response. A fact about the response rather than about one result, and
    # carried on every result because a search returns a list — but it is the
    # only way a caller can tell a ranking it was promised from one it was given,
    # and a degraded response from an instance that was never configured for one.
    ranking: str = "fusion"

    @property
    def text(self) -> str:
        """The text this result carries: the window where there is one."""
        return self.window.text if self.window else self.chunk.text

    @property
    def char_start(self) -> int:
        """Where the returned text starts in the document."""
        return self.window.char_start if self.window else self.chunk.char_start

    @property
    def char_end(self) -> int:
        """Where the returned text ends in the document."""
        return self.window.char_end if self.window else self.chunk.char_end

    @property
    def is_widened(self) -> bool:
        return self.window is not None


@dataclass(frozen=True)
class Casefile:
    """The unit of scoping, provenance, and later access control."""

    id: str
    slug: str
    title: str
    description: str
    created_at: datetime
    updated_at: datetime

    @property
    def short_id(self) -> str:
        """The 8-character prefix used as a handle across every surface."""
        return self.id[:8]


@dataclass(frozen=True)
class Mention:
    """An identifier found in a chunk's text, addressed by that chunk.

    A mention is derived from a chunk and keyed on it, so it is written by the
    same call that writes the chunk and removed by the same deletion. It records
    what was found, where, and by which extractor — never a judgement about what
    the identifier means, which is the analyst's to make.
    """

    # The chunk this identifier was found in: what a citation resolves to, and
    # what a deletion removes the mention by.
    chunk_id: str
    # The document and the casefile that chunk belongs to. Both are derivable
    # from `chunk_id` and are carried anyway, which is denormalisation on
    # purpose. The inventory counts distinct documents per identifier and every
    # query is confined to one casefile, so these two are the grouping key and
    # the filter key of every read this table exists to serve. Reaching them
    # through a join back to `chunks` would put the leading column of both
    # mention indexes out of reach and turn each of those reads into a scan of
    # every mention in the store. Nothing writes them but the chunk being
    # stored, so the copies cannot come to disagree.
    document_id: str
    casefile_id: str
    # Which kind of identifier this is, as the extractor that found it declares
    # it.
    kind: str
    # The text exactly as the chunk had it, so a quotation still shows what the
    # document said rather than what normalisation made of it.
    value: str
    # The comparable form, and what a pivot matches on: one account written with
    # spaces in one document and without them in another is one identifier.
    normalised: str
    # Where `value` sits in the chunk's text, never the document's. The chunk is
    # the unit the store addresses and the unit a citation resolves to, so these
    # offsets select the mention from the same text a hit carries.
    char_start: int
    char_end: int
    # Which extractor found it. Recorded per mention rather than inferred from
    # `kind`, because the registry is the seam a model-backed extractor arrives
    # through and two extractors may then answer for one kind — at which point
    # an analyst discounting a match needs to know which of them made it.
    extractor: str
    # How far the extractor stands behind this match. Every shipped extractor
    # validates rather than guesses and so asserts 1.0; this exists for the
    # model-backed extractor that will not be able to.
    confidence: float = 1.0


@dataclass(frozen=True)
class MentionFacet:
    """One line of a casefile's identifier inventory: an identifier and its weight.

    An inventory of what was found, never a claim about what is there. An
    identifier written without the keyword its extractor anchors on, or with a
    transposed digit, is absent from this list and present in the corpus.
    """

    kind: str
    # The normalised form, which is what the counts below are grouped by: two
    # spellings of one account are one entry here, as they are one pivot.
    value: str
    # How many times it was mentioned, and in how many documents. Both, because
    # neither substitutes for the other — an identifier mentioned forty times in
    # one document is a different fact from one mentioned once in each of forty,
    # and an analyst choosing where to look next has to tell them apart.
    mentions: int
    documents: int


@dataclass(frozen=True)
class MentionCarrier:
    """One document that carries an identifier, and the passage to cite for it."""

    document: Document
    # Distinct textual occurrences in this document, counted the way the facet
    # counts them — by position, never by stored row. Chunks overlap by the
    # contract's overlap, so one occurrence near a boundary is extracted twice
    # and a row count is wrong by exactly that overlap, invisibly. Counted this
    # way, these figures sum to the facet's `mentions` for the identifier,
    # which is the only check either number gets.
    mentions: int
    # A passage carrying the earliest occurrence: what makes a document reached
    # by enumeration citable without a ranked search first. The earliest
    # position in the document, then the lowest chunk ordinal, because the two
    # chunks sharing an overlap hold the same occurrence. Empty only if a
    # mention outlived its chunk, which the foreign key forbids; an empty value
    # then reaches `case_cite` as a typed refusal rather than as a citation.
    chunk_id: str


@dataclass(frozen=True)
class MentionDocumentPage:
    """One bounded page of the documents carrying one identifier.

    A domain object rather than a dict, for the reason `CasefileStatistics`
    gives, and a type of its own rather than a `DocumentPage`: an entry here is
    a document *plus* two values derived from the identifier, exactly as a
    `SearchHit` is a document plus values derived from a query. Widening
    `Document` with optional fields instead would touch every surface that
    shows a document, which is the argument `docs/implementation-notes.md`
    already parks for `character_count`.
    """

    carriers: list[MentionCarrier]
    # How many documents carry the identifier in the store, which is not how
    # many this page carries. Both are needed: a caller that cannot tell "this
    # is all of them" from "this is the first fifty" reports the first fifty as
    # coverage.
    total_matching: int
    offset: int
    limit: int
    # What was matched, filled by the store from the arguments it was given, so
    # that two adapters cannot describe one selection differently — the same
    # arrangement as `DocumentPage.selection`. `kind` is empty where a bare
    # value matched any kind; `value` is the normalised form, which is what the
    # counts are grouped by and what an adapter must show, because it may
    # differ from what the caller typed.
    kind: str
    value: str

    @property
    def truncated(self) -> bool:
        """Whether documents carrying the identifier were left unreturned."""
        return self.offset + len(self.carriers) < self.total_matching

    @property
    def continue_from(self) -> int | None:
        """The offset that resumes this listing, or `None` when it ended."""
        return self.offset + len(self.carriers) if self.truncated else None

    @property
    def beyond_the_end(self) -> bool:
        """Whether this page is empty because it began past the carrier set.

        A property of the page rather than of any surface, because every
        surface has to answer the same question and must not answer it
        differently: "no document carries this" said of a page past the end is
        a false claim of absence, which is the failure the exhaustive
        enumeration exists to remove. The agent surface guarded it and the CLI
        did not, which is exactly the divergence one definition prevents.
        """
        return not self.carriers and bool(self.offset) and bool(self.total_matching)


@dataclass(frozen=True)
class CasefileStatistics:
    """The size and shape of one casefile, counted in the database.

    A domain object rather than a dict because this port speaks in domain
    objects: a dict of five keys puts the field names in a string, where a typo
    is a `KeyError` at the surface and a rename is silent. The names here are the
    ones every adapter reports, and they deliberately do not match the SQL
    aliases that produce them — `documents_ingested` reads as what it is, where
    a bare `ingested` beside `documents` reads as a different unit.
    """

    # Every document in the casefile, however it arrived.
    documents: int
    # Split by how they arrived, because the totals answer different questions.
    # A casefile of three archives holding forty thousand documents is both "3"
    # and "40,003", and a figure offered without saying which misrepresents the
    # size of the corpus — which an agent then repeats as coverage.
    documents_ingested: int
    documents_expanded: int
    # Characters of extracted text, summed in the database. Loading every
    # document's text to measure it costs the whole corpus in memory for one
    # integer.
    characters: int
    # Media type to count. A mapping rather than a tuple of pairs: it is handed
    # to the agent surface as a payload field and iterated for a formatted
    # block, and `Extraction.metadata` sets the precedent for a mapping inside a
    # frozen dataclass.
    by_type: dict[str, int]


@dataclass(frozen=True)
class IngestRun:
    """One completed ingest run, as it is recorded.

    Written and never read back row by row — the aggregate below is the only
    read — for the same reason a `Mention` is: the aggregate is what a caller
    asks for, and an unbounded per-row read has no consumer. Field names are the
    column names, deliberately: `CasefileStatistics` diverges from its SQL
    aliases to stay readable, and every value-by-value assertion still passes
    against silently different keys, so where there is no readability reason to
    differ they are held identical.
    """

    id: str
    casefile_id: str
    started_at: datetime
    finished_at: datetime
    documents_before: int
    documents_after: int
    items_ingested: int
    items_failed: int
    entries_refused: int
    files_without_extractor: int
    exhausted_by: str


@dataclass(frozen=True)
class IngestionCoverage:
    """What the store records about how a casefile was filled.

    Counted facts only. Whether they add up to a claim of completeness is a
    domain rule and lives in the service layer, so that the store cannot hold a
    second opinion about it.
    """

    runs: int
    runs_with_limitations: int
    items_ingested: int
    items_failed: int
    entries_refused: int
    files_without_extractor: int
    # Runs whose `documents_before` does not match the previous recorded run's
    # `documents_after` — a gap where documents arrived through a run that was
    # never recorded, because it raised, was killed, or failed to write its own
    # row. A count, not a judgement: what it implies about completeness is the
    # service layer's rule.
    continuity_breaks: int
    # Every distinct bound that stopped an expansion in this casefile, ordered.
    bounds_reached: tuple[str, ...]
    # Documents the casefile already held when its earliest recorded run began.
    documents_before_first_run: int


@dataclass(frozen=True)
class DocumentPage:
    """One bounded page of a casefile's documents, and what it is a page of.

    A domain object rather than a tuple or a dict, for the reason
    `CasefileStatistics` gives: a count offered without its name is a count a
    caller can misread, and a mapping puts the field names in strings where a
    rename is silent.
    """

    documents: list[Document]
    # How many documents the selection holds in the store, which is not how many
    # this page carries. Both are needed: an agent that cannot tell "this is all
    # of them" from "this is the first fifty" reports the first fifty as
    # coverage.
    total_matching: int
    offset: int
    limit: int
    # Which set was listed: `ingested` for the casefile's intake, `all` for every
    # document in it, `children` for one container's direct contents. Derived by
    # the store from the arguments it was given, so two adapters cannot name the
    # same selection differently.
    selection: str
    # The container this page is inside, when one was asked for. Set by the
    # service layer, which resolved the reference; the store leaves it empty
    # because the store is handed an identifier, not a reference. The same
    # arrangement as `Document.child_count`, which only the query that aliases it
    # populates.
    parent: Document | None = None

    @property
    def truncated(self) -> bool:
        """Whether documents matching this selection were left unreturned."""
        return self.offset + len(self.documents) < self.total_matching

    @property
    def continue_from(self) -> int | None:
        """The offset that resumes this listing, or `None` when it ended."""
        return self.offset + len(self.documents) if self.truncated else None


@dataclass(frozen=True)
class DocumentPassagePage:
    """One bounded page of a document's stored passages, in reading order.

    A domain object rather than a tuple or a dict, for the reason
    `CasefileStatistics` gives, and a type of its own rather than a
    `DocumentPage`: the entries are passages, not documents.

    The field names are `DocumentPage`'s and `MentionDocumentPage`'s
    deliberately. This is the third paged listing on the surface, and
    `mcp-tool-surface` asks for one continuation contract rather than a new
    spelling per listing — an agent that has learned to follow `truncated` and
    `continue_from` must not have to learn a third.
    """

    passages: list[PassageReference]
    # How many passages the document holds in the store, which is not how many
    # this page carries. Both are needed: a caller that cannot tell "this is all
    # of them" from "this is the first fifty" reports the first fifty as
    # coverage.
    total_matching: int
    offset: int
    limit: int
    # The document these passages belong to. Set by the service layer, which
    # resolved the reference; the store leaves it empty because the store is
    # handed an identifier, not a reference. The same arrangement as
    # `DocumentPage.parent`.
    document: Document | None = None

    @property
    def truncated(self) -> bool:
        """Whether passages of this document were left unreturned."""
        return self.offset + len(self.passages) < self.total_matching

    @property
    def continue_from(self) -> int | None:
        """The offset that resumes this listing, or `None` when it ended."""
        return self.offset + len(self.passages) if self.truncated else None

    @property
    def beyond_the_end(self) -> bool:
        """Whether this page is empty because it began past the last passage.

        A property of the page rather than of any surface, for the reason
        `MentionDocumentPage.beyond_the_end` gives: every surface has to answer
        the same question and must not answer it differently. "This document has
        no passages to cite" said of a page past the end is a false claim of
        absence, and this is the capability that exists to remove exactly that
        class of false negative.
        """
        return not self.passages and bool(self.offset) and bool(self.total_matching)


class StorePort(Protocol):
    """What the service layer requires of a store."""

    def initialize(self, contract_fingerprint: str, embed_dimensions: int) -> None:
        """Create or open the store, and verify it matches the contract.

        Raises if the store on disk was built under a different contract: a
        corpus is only appendable under the rules that created it. The vector
        index is sized from the contract, which is why the width is needed here.
        """
        ...

    def create_casefile(self, casefile: Casefile) -> Casefile: ...

    def get_casefile(self, casefile_id: str) -> Casefile | None: ...

    def get_casefile_by_slug(self, slug: str) -> Casefile | None: ...

    def find_casefiles_by_id_prefix(self, prefix: str) -> list[Casefile]: ...

    def list_casefiles(self) -> list[Casefile]: ...

    def update_casefile(self, casefile: Casefile) -> Casefile: ...

    def delete_casefile(self, casefile_id: str) -> bool: ...

    # -- documents and chunks ---------------------------------------------

    def store_document(
        self, document: Document, location_path: str, observed_at: datetime
    ) -> tuple[Document, bool]:
        """Store a document and where its bytes were observed, in one write.

        Returns the stored document and whether that location was new to it.

        The location is a required parameter rather than a second call or an
        optional argument, because whether this document's record may be read as
        whole is answered from that record: a document committed without the
        observation that opens it asserts a history it does not have, and one
        later observation from elsewhere then reads as the whole story. A seam
        that can be used in the wrong order eventually is — the reason this
        module already gives for writing a chunk's derived rows in the chunk's
        own call — and an optional one is used wrongly without eventually.

        The document's identifier is reused when the same bytes are already
        stored, and the observation is kept only if the path is new: the first
        sighting's timestamp is the fact worth having, and it is what the
        wholeness of the record is judged against.
        """
        ...

    def get_document(self, document_id: str) -> Document | None: ...

    def find_document_by_hash(
        self, casefile_id: str, content_hash: str, identity_path: str = ""
    ) -> Document | None: ...

    def document_locations(
        self, document_id: str, limit: int
    ) -> DocumentLocationSet: ...

    def delete_document(self, document_id: str) -> bool: ...

    def ancestors(self, document_id: str) -> list[Document]: ...

    def descendant_ids(self, document_id: str) -> list[str]: ...

    def find_documents_by_id_prefix(self, casefile_id: str, prefix: str) -> list[Document]: ...

    def list_documents(
        self, casefile_id: str, include_expanded: bool = False
    ) -> list[Document]: ...

    def list_document_page(
        self,
        casefile_id: str,
        include_expanded: bool = False,
        parent_id: str | None = None,
        offset: int = 0,
        limit: int = -1,
    ) -> DocumentPage:
        """One bounded page of a casefile's documents, and the size of the set.

        `parent_id` selects one document's direct children, and takes precedence
        over `include_expanded`: children are expansions by definition, so the
        two cannot conflict. A negative `limit` is SQLite's own "no bound", used
        by the unbounded listing above and by nothing else.

        The count SHALL be computed under the same predicate as the page. A total
        derived from a different predicate than the rows is a number a caller
        cannot act on, and nothing downstream detects it.
        """
        ...

    def replace_chunks(
        self,
        document_id: str,
        chunks: list[Chunk],
        embeddings: list[list[float]],
        mentions: list[Mention],
    ) -> None:
        """Replace a document's chunks, their vectors and their mentions atomically.

        Mentions are a parameter of this call rather than a method of their own,
        and that is the whole of the reason they appear here. A chunk's
        identifier is minted afresh on every reingest, so a separate write made
        after the chunks were stored would attach its rows to identifiers that
        had just been replaced. That failure is not detectable afterwards: the
        rows are well-formed and reference identifiers that did once exist. A
        seam that can be used in the wrong order eventually is, so the wrong
        order is not offered.
        """
        ...

    def find_chunks_by_id_prefix(self, casefile_id: str, prefix: str) -> list[Chunk]: ...

    def casefile_statistics(self, casefile_id: str) -> CasefileStatistics: ...

    def record_ingest_run(self, run: IngestRun) -> None:
        """Record a completed run. Nothing is recorded for a run that raised."""
        ...

    def ingestion_coverage(self, casefile_id: str) -> IngestionCoverage: ...

    def get_document_chunks_around(
        self, document_id: str, ordinal: int, radius: int
    ) -> list[Chunk]: ...

    def list_document_ids(self, casefile_id: str) -> list[str]:
        """Every document in a casefile, expansions included, oldest first.

        Identifiers rather than documents, and that is the whole reason it
        exists: `list_documents` carries each row's extracted text, so a
        maintenance pass over a casefile would hold the corpus in memory in
        order to walk it. Ordered so that a run is reproducible.
        """
        ...

    def list_document_chunks(self, document_id: str) -> list[Chunk]:
        """One document's chunks, in ordinal order.

        Unbounded and carrying every chunk's text: a maintenance call, used by
        the offset repair, which needs the text to locate a passage in its
        document. A surface asking for a document's passages wants
        `list_document_passage_page` instead.
        """
        ...

    def list_document_passage_page(
        self, document_id: str, offset: int, limit: int
    ) -> DocumentPassagePage:
        """One bounded page of a document's passages, and how many it holds.

        Addressed by document identifier, like `document_locations` and
        `list_document_chunks` beside it: the service resolved the reference
        inside its casefile before calling, which is where that rule lives.

        The count SHALL be computed under the same predicate as the page. A
        total derived from a different predicate than the rows is a number a
        caller cannot act on, and here — as in `documents_with_mention` — a
        total counted wider than the page keeps `truncated` true past the last
        entry, so a caller following `continue_from` never terminates.

        The ordering SHALL be total. `chunks` does not enforce uniqueness on
        `(document_id, ordinal)`: the chunker produces them sequentially, but
        nothing in the schema says so, and `mcp-tool-surface` requires an
        ordering in which a page boundary cannot fall inside a tie and repeat or
        skip an entry.

        No unbounded form is offered, and an implementation SHALL enforce that
        rather than trusting its caller — the same requirement
        `documents_with_mention` states, for the same two reasons: a negative
        `limit` is SQLite's own "no bound" and the neighbouring
        `list_document_page` honours one, and a `limit` of 0 returns no rows
        while the count still reports the whole set, so `truncated` stays true
        and `continue_from` never advances. Both are floored to at least one.

        A passage SHALL be returned without its text. The text is what makes
        this expensive, the caller asked for an index, and the tools that return
        a passage and a citation are one call away.
        """
        ...

    def recompute_mention_offsets(self, text_starts: dict[str, int]) -> int:
        """Rewrite the document position of every mention on the named chunks.

        Takes, per chunk identifier, where that chunk's stored text begins in
        its document, and sets each mention's position to that plus the
        mention's own chunk-relative offset — the same derivation
        `replace_chunks` makes at write time, from a value the caller has
        established against the document's text. Returns how many rows actually
        changed, so a caller can report a correction and tell a repeated run
        from a first one. Nothing else about a mention is touched.
        """
        ...

    def search_keyword(
        self,
        casefile_id: str,
        query: str,
        limit: int,
        mention_kind: str = "",
        mention_value: str = "",
    ) -> list[str]: ...

    def search_vector(
        self,
        casefile_id: str,
        embedding: list[float],
        limit: int,
        mention_kind: str = "",
        mention_value: str = "",
    ) -> list[str]: ...

    def mention_facets(
        self, casefile_id: str, kind: str, limit: int
    ) -> list[MentionFacet]:
        """Count a casefile's identifiers, most mentioned first.

        An empty `kind` reports every kind. `limit` bounds the result, because a
        corpus holds far more identifiers than a caller can read.

        Counted by the store rather than by the service layer, which holds no
        SQL: fetching a casefile's mentions in order to count them in Python
        costs the whole table in memory for a handful of integers.
        """
        ...

    def documents_with_mention(
        self,
        casefile_id: str,
        mention_kind: str,
        mention_value: str,
        offset: int,
        limit: int,
    ) -> MentionDocumentPage:
        """One page of the documents carrying one normalised identifier.

        An empty `mention_kind` matches any kind, as the search filter's does.
        `mention_value` is the normalised form; validating it and refusing an
        empty one belongs to the service layer, where the kinds are known.

        The count SHALL be computed under the same predicate as the page. A
        total derived from a different predicate than the rows is a number a
        caller cannot act on, and nothing downstream detects it — and here it is
        worse than in a plain listing: a total counted wider than the page keeps
        `truncated` true past the last entry, so a caller following
        `continue_from` never terminates.

        No unbounded form is offered, and an implementation SHALL enforce that
        rather than trusting its caller: `list_document_page` honours a negative
        `limit` because the unbounded listing above it needs one, so a future
        caller copying the neighbouring signature would otherwise get the whole
        carrier set without noticing. A `limit` of 0 is the quieter half of the
        same requirement — it returns no rows while the count still reports the
        whole set, so `truncated` stays true and `continue_from` never advances.
        Both are floored to at least one.

        Confinement to the casefile SHALL be enforced on every table the
        implementation reads, not on the one carrying the identifier alone. The
        casefile is the compartment, and a mention's casefile is a denormalised
        copy; a read that trusts that copy alone discloses another casefile's
        document metadata, and a citable passage id, the moment the copy is
        wrong.
        """
        ...

    def get_chunks(self, chunk_ids: list[str]) -> dict[str, Chunk]: ...

    def close(self) -> None: ...
