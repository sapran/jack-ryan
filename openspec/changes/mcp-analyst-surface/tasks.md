## 1. Surface skeleton

- [x] 1.1 Add the MCP SDK dependency.
- [x] 1.2 Build the server with instructions that teach the working method, not just list tools.
- [x] 1.3 Mount it in-process on the existing app, and add a stdio entry point.
- [x] 1.4 Run tool bodies off the event loop, since the service layer is synchronous.

## 2. Return shape and chaining

- [x] 2.1 List-shaped results carry a scannable `formatted` index plus `results`.
- [x] 2.2 A passage body appears exactly once in a payload.
- [x] 2.3 Every result carries `chunk_id` and `document_id`.
- [x] 2.4 Identifiers a tool returns are accepted by the tools they address.
- [x] 2.5 Accept 8-character identifier prefixes wherever an identifier is taken.

## 3. The tools

- [x] 3.1 `case_list_casefiles` — what exists.
- [x] 3.2 `case_casefile_overview` — size and shape before searching.
- [x] 3.3 `case_list_documents` — enumerate a small corpus.
- [x] 3.4 `case_search` — hybrid search, bounded.
- [x] 3.5 `case_get_passage` — one chunk with its neighbours.
- [x] 3.6 `case_read_document` — bounded text with explicit truncation and continuation offsets.
- [x] 3.7 `case_cite` — a quotable citation resolving to document and span.

## 4. Untrusted content

- [x] 4.1 Fence corpus text with a per-response nonce.
- [x] 4.2 Attach provenance naming the casefile, document, and position.
- [x] 4.3 State in the payload that the content is evidence, not instruction.
- [x] 4.4 Ensure document-controlled text cannot forge a fence marker.

## 5. Profiles and annotations

- [x] 5.1 Three profiles with explicit allow-sets; only `readonly` is populated now.
- [x] 5.2 An unrecognised profile yields the narrowest surface.
- [x] 5.3 A tool absent from the annotations table is a failure, not a default.
- [x] 5.4 Stamp each tool by its worst reachable mode.

## 6. Errors

- [x] 6.1 Return typed error payloads rather than raising.
- [x] 6.2 Use the same codes the service layer raises.
- [x] 6.3 Clamp out-of-range arguments rather than refusing, since there is no validation layer above.

## 7. The analyst pack

- [x] 7.1 A harness-neutral analyst role naming the method and the tools.
- [x] 7.2 Spine skills: hypothesis testing, key assumptions, calibrated confidence, naming the gaps, deception detection, fusion, briefing.
- [x] 7.3 The working loop: every pass ends in a calibrated judgement and a next move.
- [x] 7.4 Epistemics: coverage claims name what was searched; absence is not proof.
- [x] 7.5 State that retrieved content is data, never instructions.

## 8. Verification

- [x] 8.1 Whole suite green.
- [x] 8.2 Every tool called directly, with its payload shape asserted.
- [x] 8.3 A full survey → search → read → cite chain, with citations resolving to real spans.
- [x] 8.4 Chaining verified: identifiers returned by one tool accepted by the next.
- [x] 8.5 Profile pruning verified, including the unrecognised-name case.
- [x] 8.6 Fence integrity verified against document text that tries to forge a marker.
- [ ] 8.7 Driven by a live agent against two model vendors — needs model access, blocked here.

## 9. Adversarial review

- [x] 9.1 Review across tool correctness, casefile isolation, fencing and shape, spec conformance, and integration.
- [x] 9.2 Refutation-test every finding; keep only what reproduces.
- [x] 9.3 Fix all six confirmed defects.
- [x] 9.4 Add a regression test per defect, each failing against the original code.
- [x] 9.5 Cover the HTTP transport, which no test previously exercised.
- [x] 9.6 Replace the assertion found to be vacuous.
