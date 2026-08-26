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

**The prototype is complete.** Documents go in; an AI analyst works them
through an MCP surface and answers with citations that resolve to a real
passage. That was the loop the whole build was staged around.

**M3 is under way.** The first slice — email, spreadsheets, archives, and the
document hierarchy that holds them together — is built. Still to come in M3:
scanned documents, better retrieval, summaries, and names extracted from the
text. Then **M4**, where the assistant writes back: tags, a running picture of
the investigation, and cited reports.

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

Supported formats today: PDF, DOCX, PPTX, HTML, Markdown, plain text, email
(EML, MBOX, MSG), spreadsheets (XLSX, CSV, TSV), and archives (ZIP, TAR).
Archives, mailboxes and messages are expanded through the same pipeline, so a
document three levels down is searched and cited like any other — and its
citation names the path you would follow to find it by hand. Scanned documents
come with the rest of M3.

## Working it with an AI

The instance serves an MCP surface — in-process at `/mcp`, or over stdio with
`jackryan serve-mcp`. Point any MCP-capable harness at it and initialise the
agent with [`analyst/role.md`](analyst/role.md), which carries the method and
the analytic spine. Corpus text reaching the agent is fenced and marked as
evidence rather than instruction.

Configuration is layered — a corpus-coupled `contract` plus swappable
infrastructure `profiles`. Copy `config.yaml.example` to `config.yaml` and
`.env.example` to `.env`; both are gitignored. With neither present the
instance runs on built-in defaults, fully offline.

## License

[AGPL-3.0-or-later](LICENSE). Running a modified Jack Ryan as a network
service obliges you to publish your changes — the tool and anything built on
it stay auditable, which matters for something handling sensitive material.
