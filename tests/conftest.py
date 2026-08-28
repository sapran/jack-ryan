from __future__ import annotations

import pytest

from jackryan.app import Context, build_context
from jackryan.config import Config, Contract, Profile
from jackryan.embedding.deterministic import DeterministicEmbedder
from jackryan.ingestion.quality_gate import QualityGate
from jackryan.services.casefiles import CasefileService

# Small but real: chunks stay readable in failures, and the vector width is
# wide enough that unrelated text does not collide by accident.
TEST_DIMENSIONS = 256


@pytest.fixture
def config(tmp_path) -> Config:
    return Config(
        contract=Contract(
            chunk_max_chars=400,
            chunk_overlap_chars=50,
            embed_model="deterministic-test",
            embed_dimensions=TEST_DIMENSIONS,
        ),
        profile=Profile(name="test", embedder="deterministic"),
        data_dir=tmp_path / "data",
    )


@pytest.fixture
def gate() -> QualityGate:
    """A quality gate whose rungs are stand-ins, for the same reason as the embedder.

    No test in this suite ingests a PDF or an image, so no rung should ever run.
    The readers raise rather than return, so a test that starts to depend on
    real recognition fails loudly here instead of quietly downloading a model.
    """

    class RungWasReached(BaseException):
        """Deliberately not an `Exception`.

        `_GatedReader._read_pages` wraps `Exception` into `ExtractionError`, and
        the ingest service turns that into an ordinary "failed" outcome for one
        document. An `AssertionError` raised here would therefore be swallowed
        twice and surface as a per-file failure a test could pass straight over
        — the fixture's stated safety would not hold. Deriving from
        `BaseException` puts it past both handlers.
        """

    def unreached(path):
        raise RungWasReached(
            f"a rung reader ran for {path}: the suite is not meant to reach recognition"
        )

    return QualityGate(
        ocr_engine="rapidocr",
        ocr_language="eslav",
        min_chars_per_page=100,
        readers={"text-layer": unreached, "ocr": unreached},
    )


@pytest.fixture
def context(config: Config, gate: QualityGate) -> Context:
    """A fully wired instance, assembled the way production assembles one.

    The embedder is the deterministic implementation and the gate's rungs are
    stand-ins, so the suite never downloads a model, but every other part is the
    real thing.
    """
    ctx = build_context(config, embedder=DeterministicEmbedder(TEST_DIMENSIONS), gate=gate)
    yield ctx
    ctx.close()


@pytest.fixture
def service(context: Context) -> CasefileService:
    return context.casefiles


@pytest.fixture
def corpus(tmp_path):
    """A small synthetic corpus. No real case material ever enters the repo."""
    folder = tmp_path / "corpus"
    folder.mkdir()
    (folder / "lease.md").write_text(
        "# Harbour Lease\n\n"
        "Northgate Holdings was awarded the harbour lease in March 2021 "
        "by the port authority board.\n",
        encoding="utf-8",
    )
    (folder / "minutes.md").write_text(
        "# Board Minutes\n\n"
        "The board discussed dredging contracts and deferred the tariff decision.\n",
        encoding="utf-8",
    )
    (folder / "notes.txt").write_text(
        "Unrelated kitchen notes about baking bread and grinding coffee.\n",
        encoding="utf-8",
    )
    return folder


@pytest.fixture
def sectioned_corpus(tmp_path):
    """A corpus whose documents hold several passages under real headings.

    The `corpus` fixture above is one passage per document. That is enough for
    most tests and useless for any test about windows: a window over a
    single-passage document is the document, so nothing is ever widened and a
    test asserting something about widening passes without exercising it.

    `sections.md` has sections far longer than a chunk, so a passage has room to
    grow. `terse.md` has sections shorter than one, so a passage straddles a
    heading — which is the case a window built from recorded heading trails alone
    gets wrong.
    """
    folder = tmp_path / "sectioned"
    folder.mkdir()
    long_alpha = " ".join(
        f"Alpha sentence {n} concerns the dredging survey." for n in range(1, 21)
    )
    long_beta = " ".join(
        f"Beta sentence {n} concerns the tariff schedule." for n in range(1, 21)
    )
    (folder / "sections.md").write_text(
        f"# Survey\n\n## Alpha\n\n{long_alpha}\n\n"
        f"## Beta\n\n{long_beta} A cormorant sat on the mooring buoy.\n",
        encoding="utf-8",
    )
    # A long section followed by a short one, so the section's last passage runs
    # past the heading between them. A window grown from the middle of the long
    # section reaches that passage's end, and would cross the heading with it —
    # which is the case a window built from recorded heading trails alone gets
    # wrong, because the straddling passage carries the trail of where it began.
    # Long enough for several passages, so the marked one has a same-section
    # neighbour on each side and therefore room to grow.
    alpha = " ".join(
        f"Watch line {n} of the long section."
        if n != 30
        else "Watch line 30 records a kingfisher on the pontoon."
        for n in range(1, 45)
    )
    (folder / "straddle.md").write_text(
        f"# Watch\n\n## Long\n\n{alpha}\n\n## Short\n\nA pelican was recorded here.\n",
        encoding="utf-8",
    )
    return folder


@pytest.fixture
def anyio_backend():
    """Async tests run on asyncio only; trio is not a target."""
    return "asyncio"
