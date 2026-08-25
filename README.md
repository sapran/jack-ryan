# Jack Ryan

A self-hosted investigation workbench: a human analyst drops heterogeneous
document dumps into casefiles and works them — search, facet, tag, annotate,
pivot, report — side by side with an agentic AI assistant that has first-class
MCP access to everything ingested.

Named for the desk analyst who wins by actually reading the documents.

The evidence stays immutable, every claim the assistant makes traces back to a
source document, and the whole thing runs local-first — the corpus never leaves
the machine unless you point it at an endpoint yourself.

## Status

**M1 built.** The workbench now holds a corpus: point it at a folder and its
documents are extracted, chunked, embedded, and searchable by keyword and
meaning together.

Delivery is prototype-first. The prototype is M0–M2 and proves one loop: ingest
documents, then have the assistant work the corpus over MCP and answer with
resolvable citations. Next up is **M2** — the MCP surface and the analyst.

The design document and full staged plan: [`docs/design.md`](docs/design.md).

## Quick start

```bash
# With Docker
docker compose up -d --build
curl localhost:8500/health

# Or locally
uv venv --python 3.12 && uv pip install -e ".[dev]"
jackryan casefile create "Harbour Leases 2021"
jackryan ingest harbour-leases-2021 ~/dumps/harbour
jackryan search harbour-leases-2021 "who signed the lease"
```

Supported formats today: PDF, DOCX, PPTX, HTML, Markdown, and plain text.
Scanned documents, email archives, and spreadsheets come with M3.

Configuration is layered — a corpus-coupled `contract` plus swappable
infrastructure `profiles`. Copy `config.yaml.example` to `config.yaml` and
`.env.example` to `.env`; both are gitignored. With neither present the
instance runs on built-in defaults, fully offline.

## License

[AGPL-3.0-or-later](LICENSE). Running a modified Jack Ryan as a network
service obliges you to publish your changes — the tool and anything built on
it stay auditable, which matters for something handling sensitive material.
