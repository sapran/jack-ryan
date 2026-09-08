## 1. Reproduce before changing anything

- [ ] 1.1 Reproduce the interrupted-ingest blocker: interrupt between the document write and the location write, then ingest identical bytes from a second root; show the verdict becoming `complete` with the first root absent.
- [ ] 1.2 Reproduce the same-physical-file identity defect: ingest a folder, then its nested file directly, then the containing subfolder; show two recorded locations rendering as one path and a `new` outcome for step 2.
- [ ] 1.3 Write the deltas, scoped by falsification against every published requirement, and validate before implementation.

## 2. A location is a path

- [ ] 2.1 Schema rung 10: `document_observations` keyed `(document_id, location_path)`, cascading with its document; copy `document_locations` across, joining each pair and collapsing duplicate places to the earliest timestamp.
- [ ] 2.2 Leave `document_locations` untouched and unwritten, with the rung comment saying it is retained deliberately.
- [ ] 2.3 Add `document_observations` to the destructive-step guard's evidence tables, so a later rung cannot delete from it.

## 3. One write

- [ ] 3.1 Replace `upsert_document` with `store_document`, taking the observation as a required parameter and writing both in one transaction.
- [ ] 3.2 Remove `upsert_document` from the port and the store rather than deprecating it; migrate all three test callers.
- [ ] 3.3 Verify a failure partway leaves neither the document nor its observation.

## 4. Derived completeness

- [ ] 4.1 Derive the verdict from `min(first_seen_at) <= created_at`, in one place used by the service and by both listing surfaces.
- [ ] 4.2 Stop reading and writing `documents.locations_recorded`; record in the rung comment why the column stays.
- [ ] 4.3 Alias `MIN(first_seen_at)` on the listing query, and derive the marking threshold from the same rule rather than in each adapter.
- [ ] 4.4 Pin that a new document's `created_at` equals its first observation's `first_seen_at`, so a refactor calling the clock twice fails loudly.

## 5. Proof

- [ ] 5.1 A regression test for the retry transition, not only the immediate zero-observation state.
- [ ] 5.2 A regression test for one file reached through two roots, and for two roots holding one path each staying two locations.
- [ ] 5.3 A test that the port offers no way to store a document without its observation.
- [ ] 5.4 Mutation-prove every new guard: apply the defect, watch the named test go red with its own symptom, restore.
- [ ] 5.5 Verify through the real CLI and a real `serve-mcp` stdio process, on disposable data.
- [ ] 5.6 Carry a real pre-change store forward and show its records arriving in the new table with duplicates collapsed and no location invented.
- [ ] 5.7 Gates: pytest, gitleaks, Docker build, and `openspec validate --all --strict`.
- [ ] 5.8 Update the task record with the evidence, leaving task 5 awaiting independent PM acceptance.
