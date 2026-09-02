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
# libarchive, which is how RAR archives are read — built from source rather
# than installed from `main`, which is the one departure from this file's
# otherwise-apt-only policy and needs its reason recorded.
#
# `libarchive-c` is a ctypes binding carrying no library of its own, so a
# system library is required: without one the import succeeds and the first
# symbol lookup fails. Trixie ships 3.7.4, whose RAR5 reader carries
# CVE-2026-14164, a double free reachable by a crafted archive. Debian marks it
# vulnerable with no security update planned for trixie, so pinning the apt
# package or upgrading it never resolves this — and the crash is `SIGABRT`,
# which no `except` catches and which would take the API server down, because
# ingestion runs in a thread pool inside it. The alternative to building was
# mixing in a package from sid, which pulls a newer libc into a stable image.
#
# The code enforces the same floor (`MIN_LIBARCHIVE`), so an image built
# without this step does not silently read archives with a vulnerable parser —
# it reports the reader as unavailable and every other format still ingests.
ARG LIBARCHIVE_VERSION=3.8.9
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libgl1 libglib2.0-0 \
        libreoffice-writer libreoffice-calc libreoffice-impress \
    && apt-get install -y --no-install-recommends \
        curl ca-certificates build-essential pkg-config \
        libxml2-dev liblzma-dev libbz2-dev zlib1g-dev libzstd-dev liblz4-dev \
    && curl -fsSL "https://github.com/libarchive/libarchive/releases/download/v${LIBARCHIVE_VERSION}/libarchive-${LIBARCHIVE_VERSION}.tar.xz" \
        -o /tmp/libarchive.tar.xz \
    && tar -xJf /tmp/libarchive.tar.xz -C /tmp \
    && cd "/tmp/libarchive-${LIBARCHIVE_VERSION}" \
    && ./configure --prefix=/usr/local --disable-static --without-openssl \
    && make -j"$(nproc)" && make install \
    && ldconfig \
    && cd / && rm -rf /tmp/libarchive* \
    && apt-get purge -y --auto-remove \
        curl build-essential pkg-config \
        libxml2-dev liblzma-dev libbz2-dev zlib1g-dev libzstd-dev liblz4-dev \
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
