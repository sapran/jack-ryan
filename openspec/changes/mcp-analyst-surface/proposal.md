## Why

Everything built so far exists to be worked by an analyst who is not going to
read ten thousand documents. M2 is where that finally happens: the assistant
reaches the corpus, and answers with citations that resolve to a real passage.

It is the milestone the prototype was staged around. M0 made the instance run
and M1 gave it a corpus, but neither is testable against the actual claim —
that an analyst plus an AI can work a document dump and produce something
trustworthy. After M2 that claim is either demonstrated or refuted.

## What Changes

**Current behavior.** The corpus is reachable by a human through the CLI and
REST. An agent has no way in.

**Desired behavior.** An analyst points any MCP-capable harness at the instance
and works the casefile through it — surveying, searching, pivoting, reading, and
citing — with the assistant's every factual claim resolving to a document, a
chunk, and a span.

- Add an **MCP surface** of read-only `case_*` tools, mounted in-process and
  also reachable over stdio.
- Adopt a **return shape** that separates a scannable index from the passage
  bodies, and carries identifiers that chain one call into the next.
- Add the **untrusted-content boundary**: corpus text is fenced with a
  per-response nonce and carries provenance, because a document can contain text
  that looks like an instruction.
- Add **surface profiles** — `readonly`, `analyst`, `admin` — which prune the
  advertised tools and fail to the narrowest set on anything unrecognised.
- Add an **annotations table** stamping every tool by its worst reachable mode,
  in one place rather than per tool.
- Ship the **analyst pack**: a harness-neutral role definition on the
  structured-analytic spine, so an agent arrives knowing the method rather than
  improvising it.

Only `readonly` is populated in this milestone. Attributed writes, the operating
picture, the roster split into legs, and reports are M4.

## Capabilities

### New Capabilities

- `mcp-tool-surface` — the `case_*` tools, their return shape, chaining
  identifiers, and bounds.
- `untrusted-content-boundary` — how corpus text crosses into an agent's
  context, and what is said about it when it does.
- `mcp-surface-profiles` — which tools a profile advertises, and what happens to
  an unrecognised one.
- `analyst-pack` — the role and skills shipped for an agent to load.

### Modified Capabilities

- `service-adapter-boundary` — MCP becomes a third adapter, and the reason the
  boundary was drawn strictly stops being hypothetical: this adapter genuinely
  has no validation layer of its own.

## Impact

- **New**: `src/jackryan/interfaces/mcp/` (server, tools, shapes, fencing,
  profiles, annotations, errors), `analyst/` (role and skills), and their tests.
- **Modified**: `server.py` mounts the surface; the CLI gains a command to serve
  it over stdio; configuration gains the profile selector.
- **Dependencies**: the MCP SDK.

## Risks

**A read-only surface still moves corpus text into a model's context.** That is
the point, and it is also the exposure: a document can contain text shaped like
an instruction. Fencing and provenance are the mitigation, and they are a
convention the model can ignore, not a sandbox. Said plainly in the spec rather
than implied.

**The tool surface is a contract.** Once an analyst's saved prompts and the
shipped skills name these tools, renaming one breaks them. The names are chosen
to be worth keeping.
