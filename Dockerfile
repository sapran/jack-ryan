FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    JACKRYAN_DATA_DIR=/data

WORKDIR /app

# Dependency layer first so source edits do not invalidate the install.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

# Pre-fetch the extraction and embedding weights so a container is offline from
# its first run rather than downloading models mid-ingest. This is what makes
# the local-first promise true for a fresh container, and it adds roughly 2.5GB.
#
# Off by default so the CI gate can prove the image builds without pulling
# gigabytes of weights it never uses. A released image is built with it on:
#   docker build --build-arg PREFETCH_MODELS=true .
ARG PREFETCH_MODELS=false
ENV JACKRYAN_MODEL_CACHE=/opt/jackryan-models
RUN mkdir -p "$JACKRYAN_MODEL_CACHE" && \
    if [ "$PREFETCH_MODELS" = "true" ]; then \
      python -c "from docling.utils.model_downloader import download_models; download_models()" && \
      python -c "import os; from fastembed import TextEmbedding; TextEmbedding(model_name='intfloat/multilingual-e5-large', cache_dir=os.environ['JACKRYAN_MODEL_CACHE'])"; \
    fi

RUN mkdir -p /data
VOLUME ["/data"]
EXPOSE 8500

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8500/health').status==200 else 1)"

CMD ["uvicorn", "jackryan.server:create_app", "--factory", "--host", "0.0.0.0", "--port", "8500"]
