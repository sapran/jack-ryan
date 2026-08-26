## 1. The extraction seam

- [ ] 1.1 Grow `Extraction` with a `children` sequence of `(name, bytes)` and a `is_container` marker; verify existing extractors compile unchanged and the full suite still passes
- [ ] 1.2 Relax the "no usable text" refusal in `FormatRouter.extract` to allow a container with children and no text; verify a test asserts an empty-text non-container is still refused
- [ ] 1.3 Add `openpyxl` to the project dependencies and verify `uv pip install -e ".[dev]"` resolves offline-installable wheels
- [x] 1.4 Check `extract-msg`'s licence for compatibility with AGPL-3.0-or-later before adding it — GPLv3, admitted by AGPL-3.0's compatibility clause; `openpyxl` is MIT

## 2. Archive and directory containers

- [ ] 2.1 Implement `ZipExtractor` returning entries as children; verify a test ingests a ZIP of a Markdown file and finds both documents
- [ ] 2.2 Implement `TarExtractor` for tar, tar.gz, and tar.bz2; verify a test covers each compression
- [ ] 2.3 Refuse entries whose path escapes the extraction root, is absolute, or is a link; verify a test builds an archive with a `../` entry and asserts it is refused while its siblings ingest
- [ ] 2.4 Record a containment path for files found by the directory walk without creating a document for the directory; verify a test asserts a nested file's path carries its relative directories and that no directory appears in the document list

## 3. Mail

- [ ] 3.1 Implement `EmlExtractor` rendering sender, recipients, date, and subject above the body; verify a test asserts all four appear in the extracted text
- [ ] 3.2 Return message attachments as children; verify a test ingests an EML with an attached text file and asserts the attachment is a child document
- [ ] 3.3 Implement `MboxExtractor` returning messages as children; verify a test ingests a two-message mbox and asserts two child documents
- [ ] 3.4 Implement `MsgExtractor` on the same shape; verify a test covers headers and one attachment
- [ ] 3.5 Verify a malformed message fails as one entry without failing the mailbox — a test with one corrupt and one valid message asserts the valid one is stored

## 4. Spreadsheets

- [ ] 4.1 Implement `SpreadsheetExtractor` for XLSX rendering each sheet with its name and rows; verify a test asserts sheet names and row content are both present and attributable
- [ ] 4.2 Implement CSV and TSV extraction on the same rendering; verify a test covers quoting and an embedded delimiter
- [ ] 4.3 Verify a workbook holding an empty sheet and a populated one ingests with the populated sheet's content present

## 5. Hierarchy in the store

- [ ] 5.1 Add `parent_id` and `containment_path` to `documents`, index `parent_id`, and advance `SCHEMA_VERSION`; verify a test asserts a store built under the old version is refused rather than misread
- [ ] 5.2 Add `list_children` and `ancestors` to `StorePort` and the SQLite store; verify a test walks a three-level chain in both directions
- [ ] 5.3 Implement descendant deletion by recursive CTE routed through the existing chunk-delete path; verify a test deletes a container and asserts no orphaned FTS or vector rows remain, by ingesting again afterwards and confirming it succeeds
- [ ] 5.4 Make `list_documents` exclude expanded children by default with an option to include them, mark a container with its child count, and make `casefile_statistics` state what it counted; verify tests cover each

## 6. Expansion and its budget

- [ ] 6.1 Implement `ExpansionBudget` over depth, descendant count, and extracted bytes — defaults 8 / 50,000 / 20 GB — reporting which bound stopped it; verify unit tests exhaust each bound independently
- [ ] 6.2 Rework `IngestionService.ingest` into a breadth-first work queue carrying parent id, depth, and containment path; verify the existing ingestion tests pass unchanged
- [ ] 6.3 Materialise children into a per-ingest temporary directory used as the extraction root, removed when the ingest ends; verify a test asserts the directory is gone afterwards, including when the ingest failed
- [ ] 6.4 Derive an expanded document's identity from its extracted bytes plus its containment path; verify a test ingests an archive holding the same file at two paths and asserts two documents
- [ ] 6.5 Verify reingesting a container reuses every descendant identifier — a test ingests twice and asserts the id set is unchanged
- [ ] 6.6 Carry refusals and the exhausted bound in `IngestReport`; verify a test asserts a budget-stopped ingest reports itself incomplete, names the bound, and keeps what it already stored

## 7. Provenance

- [ ] 7.1 Carry the containment path into the provenance block and citations; verify a test asserts a nested passage's provenance names the path from the ingested file down
- [ ] 7.2 Sanitise every path element through the existing one-line collapse; verify a test names an archive entry with an embedded newline and asserts the provenance block's structure is intact

## 8. Adversarial verification

- [ ] 8.1 Build a synthetic mixed dump — an archive holding a mailbox, whose messages carry a spreadsheet and a document attachment, nested two levels — and verify it ingests with the full hierarchy and searchable text at every level
- [ ] 8.2 Verify a high-expansion archive is stopped by the byte budget rather than filling the disk, with a test that asserts the bound is reported
- [ ] 8.3 Re-read the diff adversarially for the M1 and M2 failure pattern — a rule enforced on the path built rather than the path every caller crosses — and fix what it finds
- [ ] 8.4 Run `pytest` and `openspec validate --all --strict` and verify both are clean before pushing
