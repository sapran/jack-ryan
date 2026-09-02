FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    JACKRYAN_DATA_DIR=/data

WORKDIR /app

# Two unrelated system dependencies, in one layer.
#
# OpenCV's shared libraries, which python:3.12-slim does not carry. Not
# optional and not only a build-time need: `opencv-python` arrives with the
# RapidOCR recognition engine, and `import cv2` happens every time recognition
# runs. Without these, OCR inside the container fails with
# `ImportError: libxcb.so.1` — which is why `--build-arg PREFETCH_MODELS=true`
# could not complete before they were added. Determined by installing them into
# the built image and importing cv2, not by guessing: libgl1 alone still leaves
# `libgthread-2.0.so.0` missing.
#
# LibreOffice, which is how the legacy binary Office formats are read: a `.doc`,
# `.xls` or `.ppt` is converted to its modern sibling and handed to the reader
# that already owns that suffix. Three component packages rather than the
# `libreoffice` metapackage, and `--no-install-recommends` throughout, so the
# JRE and the desktop integration are not pulled in. Without it the container
# still runs and every other format still ingests — a legacy file simply fails
# with a message naming the remedy.
#
# libarchive, which is how RAR archives are read. `libarchive-c` is a ctypes
# binding and carries no library of its own, so without this the import
# succeeds and the first symbol lookup fails. Two packages from `main`
# (libxml2 arrives with it), against 117 for `unar` or a non-free component for
# any unRAR-derived reader. Same posture as LibreOffice above: without it the
# container still runs and every other format still ingests.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libgl1 libglib2.0-0 \
        libarchive13t64 \
        libreoffice-writer libreoffice-calc libreoffice-impress \
    && rm -rf /var/lib/apt/lists/*

# Dependency layer first so source edits do not invalidate the install.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

# Pre-fetch the extraction and embedding weights so a container is offline from
# its first run rather than downloading models mid-ingest. This is what makes
# the local-first promise true for a fresh container.
#
# Measured on arm64, 2026-09-01, from `docker images --format '{{.Size}}'`:
# 6.49GB without weights, 10.7GB with. Both figures rose when LibreOffice joined
# the system layer — from 5.81GB and 10.2GB measured on 2026-08-27 — so that
# capability costs about 0.68GB. Re-measured rather than adjusted by arithmetic,
# which is why the two deltas do not match exactly. Most of the base is still
# the CUDA stack that `docling` pulls in through torch and that an arm64
# container cannot use; see docs/implementation-notes.md.
#
# Off by default so the CI gate can prove the image builds without pulling
# gigabytes of weights it never uses. A released image is built with it on:
#   docker build --build-arg PREFETCH_MODELS=true .
#
# The third line warms the recognition engine by *building* it, through the same
# function an ingest run calls. Two reasons it is not a plain download: docling's
# download_models does not fetch RapidOCR's recognition weights, which are chosen
# per language and come from a different host (modelscope.cn, not Hugging Face);
# and building the engine is the only thing that proves the image can. It warms
# the profile defaults, so an instance configured for another recognition
# language still downloads on its first ingest.
#
# A reranker is fetched only when one is named. No reranker ships by default —
# see `config.yaml.example` — so this adds nothing to the ordinary image, and an
# operator who names one gets its weights here rather than mid-query.
ARG PREFETCH_MODELS=false
ARG PREFETCH_RERANKER=""
ENV JACKRYAN_MODEL_CACHE=/opt/jackryan-models
RUN mkdir -p "$JACKRYAN_MODEL_CACHE" && \
    if [ "$PREFETCH_MODELS" = "true" ]; then \
      python -c "from docling.utils.model_downloader import download_models; download_models()" && \
      python -c "import os; from fastembed import TextEmbedding; TextEmbedding(model_name='intfloat/multilingual-e5-large', cache_dir=os.environ['JACKRYAN_MODEL_CACHE'])" && \
      python -c "from jackryan.config import Profile; from jackryan.ingestion.quality_gate import check_engine; check_engine(Profile.ocr_engine, Profile.ocr_language)"; \
    fi && \
    if [ -n "$PREFETCH_RERANKER" ]; then \
      python -c "import os,sys; from fastembed.rerank.cross_encoder import TextCrossEncoder; TextCrossEncoder(model_name=sys.argv[1], cache_dir=os.environ['JACKRYAN_MODEL_CACHE'])" "$PREFETCH_RERANKER"; \
    fi

RUN mkdir -p /data
VOLUME ["/data"]
EXPOSE 8500

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8500/health').status==200 else 1)"

CMD ["uvicorn", "jackryan.server:create_app", "--factory", "--host", "0.0.0.0", "--port", "8500"]
