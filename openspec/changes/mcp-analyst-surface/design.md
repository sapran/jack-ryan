## Context

M2 exposes the corpus to an agent. The shape was settled in `docs/design.md`;
this records the decisions taken while building it, and the one place where the
honest description of a control is weaker than it sounds.

## Decisions

### Seven tools, following the method rather than the schema

The surface is not a projection of the data model. It follows the working
order an analyst uses — inventory, survey, filter, pivot, read, cite — because
a tool list is the first thing an agent reads and it should suggest a method.

`case_list_casefiles` and `case_casefile_overview` establish what exists and
how big it is before anything is searched. `case_search` is the workhorse.
`case_get_passage` and `case_read_document` read, bounded, and read *last*.
`case_cite` turns a passage into something quotable. `case_list_documents`
covers the case where the corpus is small enough to enumerate.

### The return shape separates the index from the bodies

Every list-shaped result carries `formatted` — a compact, scannable index — and
`results`, where each passage body appears exactly once. An agent reads the
index to decide, and pays for prose only where it committed.

Every result carries `chunk_id` and `document_id`. Those are the chaining
identifiers: what a search returns is what the next call accepts, so the surface
composes without the agent having to reconstruct references.

### Fencing is honest about what it is

Corpus text is wrapped in a per-response nonce and carries a provenance block
saying where it came from and that it is evidence rather than instruction. The
nonce is per-response because a fixed marker appears in documents, and document
metadata is attacker-controlled in exactly the deployments this tool is for.

It is a convention the model is asked to honour. It is not a sandbox, and the
spec says so: a model that ignores the fence is not prevented from anything.
Claiming otherwise would be the more dangerous error, because it would stop
anyone from looking for the real control.

### Profiles fail to the narrowest surface

An unrecognised profile name yields `readonly`, never the widest set. A typo in
a deployment's configuration should cost tools, not grant them. The allow-set is
explicit rather than derived, so a tool added later is hidden by default and has
to be admitted deliberately.

### Annotations live in one table

Each tool is stamped by its worst reachable mode in a single table rather than
at each definition. Thirty scattered decorators drift; one table is reviewable
in a glance, and a tool missing from it is a failure rather than a default.

### Errors are payloads, not exceptions

A tool returns `{"error": code, "message": ...}` rather than raising. An agent
handles a returned value; a transport error is something it can only retry. The
codes are the same typed codes the service layer raises, so the vocabulary is
identical across every surface.

## Risks / Trade-offs

- **Fencing is advisory.** Stated above and in the spec. The genuine controls
  are that this profile is read-only and that the service layer, not the
  adapter, decides what is permitted.
- **Tool names are a contract.** Renaming one breaks saved prompts and the
  shipped skills.
- **The bounded read can hide relevant text.** Truncation is explicit in the
  payload — `truncated`, with the offsets to continue from — so an agent can
  tell the difference between a document that ends and a read that stopped.

## What could not be verified here

The acceptance criterion names two model vendors. The build environment reaches
no model provider, so the surface is verified by driving it directly — every
tool called, every payload shape asserted, a full survey-search-read-cite chain
exercised — rather than by an agent choosing to call it. Whether the tool
descriptions actually elicit the right calls from a model is the one thing only
a live agent can settle, and it is left as an unchecked task.

## What adversarial review caught

Six defects survived refutation. Three are worth recording, because each is a
gap between what was tested and what was claimed.

**The surface answered nothing over HTTP.** Starlette does not run a mounted
sub-app's lifespan, and the MCP session manager is started by exactly that
lifespan — so every HTTP request returned 500 while all sixteen surface tests
passed, because every one of them called `call_tool` in process. The mount was
verified to exist and never verified to work. The parent lifespan now drives the
sub-app's, and a test performs a real HTTP initialize.

**The index the agent is told to read first was the one field that trusted its
input.** It interpolated filenames raw into a newline-joined block, so a
filename containing a newline forged extra rows indistinguishable from real
ones — and it appended raw passage prose outside the fence that every other
text-bearing path applied. Both in the same six lines. Document-derived values
now pass through a whitespace collapse, and the index carries metadata only.

**Chunk lookup was the one reference type with no service.** Because the
adapter reached into the store directly, it also implemented the casefile check
itself, which the boundary forbids — and it accepted only full identifiers,
while the index printed 8-character ones, so an agent following the shipped
method got `not_found` blamed on the casefile boundary. Resolution moved into
the service layer, where prefix handling and the ambiguity refusal already
existed for documents.

The remaining two: an explicit `limit=0` clamped upward to the maximum rather
than down, and the overview loaded every document body to print two integers.

One test was found to be vacuous rather than wrong — it compared the fenced
string against the index, which by construction could never match. It now
compares the unfenced body.

## Migration Plan

None. The surface is additive; nothing that exists changes shape.

## Open Questions

- Whether `case_read_document` should return extracted text or a rendering with
  structure preserved. It returns extracted text, which is what chunks and
  citations are offsets into; a structured rendering would need its own offset
  space and is worth having only once there is a reader UI to use it.
