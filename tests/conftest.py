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

    def unreached(path):
        raise AssertionError(
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
def anyio_backend():
    """Async tests run on asyncio only; trio is not a target."""
    return "asyncio"
