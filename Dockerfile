FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    JACKRYAN_DATA_DIR=/data

WORKDIR /app

# OpenCV's shared-library dependencies, which python:3.12-slim does not carry.
# Not optional and not only a build-time need: `opencv-python` arrives with the
# RapidOCR recognition engine, and `import cv2` happens every time recognition
# runs. Without these, OCR inside the container fails with
# `ImportError: libxcb.so.1` — which is why `--build-arg PREFETCH_MODELS=true`
# could not complete before they were added. Determined by installing them into
# the built image and importing cv2, not by guessing: libgl1 alone still leaves
# `libgthread-2.0.so.0` missing.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Dependency layer first so source edits do not invalidate the install.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

# Pre-fetch the extraction and embedding weights so a container is offline from
# its first run rather than downloading models mid-ingest. This is what makes
# the local-first promise true for a fresh container.
#
# Measured on arm64, 2026-08-27: 5.81GB without, 10.2GB with — so the weights
# add about 4.4GB, not the 2.5GB this comment used to claim. Most of the 5.81GB
# base is the CUDA stack that `docling` pulls in through torch and that an arm64
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
ARG PREFETCH_MODELS=false
ENV JACKRYAN_MODEL_CACHE=/opt/jackryan-models
RUN mkdir -p "$JACKRYAN_MODEL_CACHE" && \
    if [ "$PREFETCH_MODELS" = "true" ]; then \
      python -c "from docling.utils.model_downloader import download_models; download_models()" && \
      python -c "import os; from fastembed import TextEmbedding; TextEmbedding(model_name='intfloat/multilingual-e5-large', cache_dir=os.environ['JACKRYAN_MODEL_CACHE'])" && \
      python -c "from jackryan.config import Profile; from jackryan.ingestion.quality_gate import check_engine; check_engine(Profile.ocr_engine, Profile.ocr_language)"; \
    fi

RUN mkdir -p /data
VOLUME ["/data"]
EXPOSE 8500

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8500/health').status==200 else 1)"

CMD ["uvicorn", "jackryan.server:create_app", "--factory", "--host", "0.0.0.0", "--port", "8500"]
