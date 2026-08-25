# Jack Ryan

A self-hosted investigation workbench: a human analyst drops heterogeneous
document dumps into casefiles and works them — search, facet, tag, annotate,
pivot, report — side by side with an agentic AI assistant that has first-class
MCP access to everything ingested.

Named for the desk analyst who wins by actually reading the documents.

**Status: design phase.** The design document and implementation plan live in
[`docs/design.md`](docs/design.md). No code yet; milestone M0 (bootstrap) is
next.

Lineage: [Aleph/OpenAleph](https://github.com/alephdata/aleph) and
[Datashare](https://github.com/ICIJ/datashare) define the genre;
[lib.ai](https://github.com/sapran/lib.ai) defines the ingestion/retrieval/MCP
machinery; [aleph-mcp](https://github.com/sapran/aleph-mcp) and
[datashare-mcp](https://github.com/sapran/datashare-mcp) define the
agent-safety conventions. Jack Ryan borrows patterns from all of them and
depends on none of them.
