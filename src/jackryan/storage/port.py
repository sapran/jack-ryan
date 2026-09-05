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

    @property
    def short_id(self) -> str:
        return self.id[:8]

    @property
    def is_expanded(self) -> bool:
        """Whether this document came out of another rather than off disk."""
        return self.parent_id is not None


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

    def upsert_document(self, document: Document) -> Document:
        """Store a document, reusing the identifier of one with the same bytes."""
        ...

    def get_document(self, document_id: str) -> Document | None: ...

    def find_document_by_hash(
        self, casefile_id: str, content_hash: str, identity_path: str = ""
    ) -> Document | None: ...

    def delete_document(self, document_id: str) -> bool: ...

    def list_children(self, document_id: str) -> list[Document]: ...

    def ancestors(self, document_id: str) -> list[Document]: ...

    def descendant_ids(self, document_id: str) -> list[str]: ...

    def find_documents_by_id_prefix(self, casefile_id: str, prefix: str) -> list[Document]: ...

    def list_documents(
        self, casefile_id: str, include_expanded: bool = False
    ) -> list[Document]: ...

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

    def get_document_chunks_around(
        self, document_id: str, ordinal: int, radius: int
    ) -> list[Chunk]: ...

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

    def get_chunks(self, chunk_ids: list[str]) -> dict[str, Chunk]: ...

    def close(self) -> None: ...
