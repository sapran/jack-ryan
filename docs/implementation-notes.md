# Implementation notes

Findings surfaced during work that were deliberately not fixed at the time, so
that a change stays the size it was scoped to be. Each line says what, where,
and why it was parked.

## Parked

- **Two tests share a glob of the process-global temporary directory, and one
  of them deletes what it finds there.** Both are in
  `tests/test_evaluate_retrieval.py`, and between them they make the suite fail
  intermittently *and* corrupt a concurrent run.

  `test_the_workspace_is_removed_when_the_run_ends:457` records
  `glob("$TMPDIR/jackryan-evaluate-*")`, runs the harness, and asserts
  `after == before`. Anything else creating a workspace in that window fails
  it.

  `test_the_workspace_is_kept_when_asked:467` does the same and then
  `shutil.rmtree`s every directory in `glob(...) - before`. That set is not
  "the workspace this test kept" — it is *every* matching directory that
  appeared meanwhile, including another process's live corpus. The victim then
  fails with `FileNotFoundError` on a corpus file inside a workspace it is
  still using.

  **Reproduced deterministically**: four concurrent runs of that one file gave
  `2 failed, 46 passed` in all four, with `assert 4 == 1` and
  `assert {...} == {...}` on the two tests above. **Pre-existing**: the same
  four-way run against `25eb9b8`, the commit before
  `follow-an-identifier-exhaustively`, fails identically, and the file was last
  touched in `6c12da4`. Sequentially the suite is green — 9 consecutive clean
  runs of the full suite on `develop` after the concurrent worktree that had
  been provoking it was removed.

  It first surfaced as two red runs while two review subagents held a worktree
  of this repository under `/private/tmp` and ran the harness from it. Any
  second checkout — a worktree, a reviewer's sandbox, a second omp session —
  triggers it, which is why it looks like flakiness rather than a defect.

  Parked because it is outside that change and the fix is a real one: give the
  harness a workspace root it is told about (a `tmp_path` subdirectory passed
  in, or an env override) and assert on that, so neither test can see or delete
  a directory belonging to anyone else. Retrying, loosening the count, or
  serialising the file would all hide it while leaving the `rmtree` free to
  destroy a concurrent run's data.

- **A `--mention` argument reaches all four extractors unbounded.**
  `SearchService.search` caps its `query` at `MAX_QUERY_CHARS = 500`, and
  neither it nor `mention_documents` caps `mention` — which is the one argument
  that drives regex work, since `_normalised_like_the_store` runs every shipped
  extractor's `find()` over the caller's whole string. Found by a security
  review of `follow-an-identifier-exhaustively`, which also established the
  severity is low: the 2026-09-01 review already bounded every quantifier in
  the four patterns at RFC limits, so there is no catastrophic backtracking to
  provoke. REST bounds it incidentally through URL length; the agent surface
  and the CLI do not. Parked because `search`'s own `mention` has had the same
  property since it shipped, so the fix belongs to a change that caps both
  rather than to the one that noticed.

- **The CLI prints corpus-derived filenames to the terminal unescaped.** Every
  CLI listing — `document list`, `mentions`, and now `mention-documents` —
  prints `filename` and `containment_path` raw, so an archive entry name
  carrying a newline forges a row in the printed table and one carrying an ESC
  sequence can rewrite what the analyst sees, including the header above it.
  Pre-existing and CLI-wide: the new command matches the surface it joins
  rather than lowering its bar. Worth recording beside it is that
  `interfaces/mcp/shapes.py`'s `one_line` is a whitespace collapse, not a
  sanitiser — `" ".join(text.split())` stops row forgery, which is what the
  agent surface needs, but leaves `\x00`, `\x07`, `\x08` and `\x1b` intact, so
  it must not be mistaken for terminal-safe if it is ever reused there. The fix
  is the one sanitiser at every corpus-text boundary that the byte-bound note
  below already argues for, and it wants its own change.

- **A docstring counts the port's methods, and the count is stale.**
  `services/windowing.py:207-210` says the `Windower` asks the store "one
  question out of the nineteen the port declares". `StorePort` declared 31
  before `follow-an-identifier-exhaustively` and 32 after, so the figure was
  already wrong by twelve and is not made wrong by that change. Parked rather
  than corrected because the file is untouched by it, and because a hand-written
  count in prose will go stale again — the fix worth having is to state the
  narrowness without a number.

- **The unbounded listing docstring overstates adapter migration.** `storage/sqlite.py:521` says every adapter uses `list_document_page`, but `cli.py:284` still calls `list_documents`, loading full extracted text for the selection. MCP and REST are paged; CLI is not. Parked because CLI pagination was not part of task 2's MCP/REST handoff; correct the claim or scope a CLI paging change separately.

- **Task 2 PM verification hit a converter-test setup failure outside the paging diff.** On `6b7f872`, `uv run --no-sync pytest -q` returned 758 passed, 3 skipped and one failure: `tests/test_legacy_office.py::test_a_timeout_kills_the_whole_converter_tree_not_just_the_launcher` could not read the stub's `grandchild.pid`, before reaching its process-tree assertions. The exact test passed when run alone (1 passed, exit 0); the full run remains failed and no root cause or regression attribution is established. Parked because converter behavior is outside task 2. The focused paging suite passed all 16 tests.

- **An OS metadata sidecar makes a folder ingest, and its casefile, read
  `incomplete` permanently.** `_initial_work` walks with `rglob("*")`, which
  matches dotfiles, so a `.DS_Store` that Finder wrote into any folder an
  operator opened — or an AppleDouble `._name` beside every file on a USB stick
  or SMB share, which is exactly where dumps arrive — is offered, has no
  extractor, and now lands in `IngestReport.skipped`. Confirmed by
  reproduction: a folder of one `lease.md` plus a synthetic `.DS_Store` gives
  `complete False`, `skipped ['.DS_Store']`, and a casefile verdict of
  `incomplete` that no later clean run can lift. On macOS this makes
  `incomplete` close to the default, which drains the verdict of the
  discriminating power the disclosure exists to give it. Before the
  `disclose-incomplete-ingestion` change these files were passed over in
  silence, so this is new behaviour and it is the change working as specified,
  not a defect in it — the file genuinely was offered and not ingested.
  **Not fixed here because the obvious fix is not obviously right for this
  tool.** Excluding a named sidecar list from what a walk offers would restore
  a silent skip for files that carry real forensic content: a `.DS_Store` holds
  directory listings, including names of files no longer present, which is
  occasionally the evidence. The alternatives are to exclude them and say so
  per document, or to carry the skipped *names* into the record so the agent
  surface can show what was skipped rather than only how many — both human
  surfaces already print the names, and only the agent sees a bare count. That
  is a decision about what counts as evidence, and it wants its own change.

- **The listing-versus-delivery reconciliation never reaches the mail
  extractors, and one of their silent drops loses an embedded message.**
  `_expand` reconciles against `Extraction.metadata["entries"]`, and the
  `isdigit` guard skips any extractor that does not publish it. Today that is
  every mail extractor: `MboxExtractor` publishes `messages`
  (`mail.py:119`), and `EmlExtractor`/`MsgExtractor` publish nothing relevant.
  `test_every_container_extractor_publishes_its_entry_count` now stops a *new*
  container format losing the reconciliation by omitting the key, and lists the
  three mail extractors as exempt with their reason — but exempt they remain.
  The concrete loss behind that exemption predates this change:
  `MsgExtractor.iter_children` skips any attachment whose `data` is not
  `bytes` (`mail.py:212-214`), which is precisely an embedded or forwarded
  message, since `extract_msg` returns an `MSGFile` from
  `EmbeddedMsgAttachment.data`. So an Outlook message carrying a forwarded
  message ingests, the forwarded message is never stored, and nothing is
  reported. The fix is for `MsgExtractor` either to deliver the embedded
  message as a `.msg` child or to append a refusal naming it, and for the mail
  extractors to publish a reconcilable count — a change to mail expansion, with
  its own fixtures, not a rider on a disclosure fix.

- **The per-entry ceiling lives in three copies inside the container
  extractors, and the shortfall it causes is disclosed only as a count.**
  `MAX_ENTRY_BYTES` is applied in each `iter_children` independently —
  `containers.py:206,213` (zip), `:335` (rar), `:913,920` (tar) — and each one
  `continue`s past an over-ceiling entry with no record of which entry or why.
  `TarExtractor.iter_children` also drops an entry whose `extractfile` returns
  `None`. The `disclose-incomplete-ingestion` change closes the *silence*: the
  service now reconciles `len(produced)` against the `entries` count all three
  extractors publish in `Extraction.metadata`, so a run reports "N of M listed
  entries were not delivered by the reader" and is no longer complete. What it
  does **not** report is which entry went missing or on which rule, because the
  service has no second definition of what is too large and deliberately does
  not acquire one. A declared-size refusal inside `extract()` was rejected
  rather than overlooked: `openspec/specs/container-extraction/spec.md:127-131`
  requires an oversized entry to be judged "by what was read rather than by the
  size the archive declares", because a declared size is chosen by whoever
  built the archive. The honest fix is to move the ceiling into
  `IngestionService._expand`, where `budget.take_child` already measures
  `len(child.data)` — one decision, in the layer that already reports refusals,
  able to name the entry. Parked because it changes zip, tar and RAR behaviour
  in one step and breaks `tests/test_rar_containers.py:438`, which pins the
  current per-extractor semantics; that wants its own change with its own
  argument, not a rider on a disclosure fix.
- **A bounded document page still materialises every returned document's full
  `extracted_text`.** The page query selects `d.*` and `_row_to_document` builds
  a whole `Document` per row, but nothing returns that text: the agent row and
  both human surfaces use only `len(document.extracted_text)`, as `characters`.
  Measured on 220 synthetic documents of distinct content, a page of 200 loaded
  9,506,920 characters (9.5 MB) to report 200 integers; the unbounded listing it
  replaces loaded 10,431,190. On the real corpus a page of five carried 2.9 M
  characters, so the 200-row ceiling is order 10**8 characters — hundreds of
  megabytes of Python strings — reachable in one model-issued
  `case_list_documents(casefile, expanded=true, limit=200)` or one
  `GET /api/casefiles/<ref>/documents?expanded=true&limit=200`, with no rate
  limit above either surface. The repository has already decided this question
  the other way once: `CasefileStatistics` sums characters in SQL precisely
  because loading every document's text to measure it costs the whole corpus in
  memory for one integer. **Parked because the fix needs a new domain field, not
  a new query.** Projecting `LENGTH(d.extracted_text) AS characters` requires
  `Document` to carry an optional `character_count` populated only when a query
  aliases it — the `child_count` precedent — plus both renderers reading it
  instead of `len(...)`. That touches the port's domain object and every surface
  that shows a document, which is a change that should be argued on its own
  rather than folded into a paging change. The interim `MAX_DOCUMENT_PAGE` is
  200 and is a row bound, not a byte bound. Note the in-code comment at the
  query claims only that the narrow id subquery keeps `extracted_text` out of
  the *sorter*, which is true and a different claim.

- **`one_line` strips whitespace only, so control characters and Unicode bidi
  overrides reach the agent's index and the analyst's terminal intact.** It
  collapses with `" ".join(text.split())`, and `str.split()` removes only
  whitespace: ESC, BEL and U+202E RIGHT-TO-LEFT OVERRIDE are not whitespace.
  Archive entry names are attacker-controlled in a real dump. Measured with an
  entry named `invoice\x1b[31m\u202egpj.exe\x07.txt`, all three survive into
  `formatted`, into a row's `filename`, and into `found_at` — so a crafted name
  can recolour or rewrite the terminal of the analyst reading the index, and the
  bidi override is the classic extension-spoofing trick that makes
  `…\u202egpj.exe.txt` render as though it ended in `.txt`. **Pre-existing**:
  `one_line`, `_render_document` and `formatted` all predate the paged listing,
  which only widened the surface slightly by echoing a resolved container's
  filename and containment path through the same helper. Parked rather than
  fixed here because the right fix is one sanitiser applied at every corpus-text
  boundary — the fence, the citation, the human renderers — and choosing between
  stripping and escaping is a change of its own. It is the finding worth landing
  next after the byte bound above.

- **A document reached by listing cannot be cited without a search.**
  `case_cite` needs a `chunk_id`, and no tool hands one back for a document
  reached through `case_list_documents`: `case_read_document` returns text and
  provenance but no chunk identifiers. So the container-navigation journey —
  list the intake, enter a container, read a child — has to fall back to
  `case_search` to obtain an id before it can cite what it just read. That
  partly defeats the point of the capability, whose premise is that a container
  is exactly where retrieval is least likely to surface the evidence. Parked
  because closing it means adding chunk identifiers to a read payload, which is
  a `mcp-tool-surface` contract change and needs its own delta. The journey test
  is named and documented for what it actually proves — reaching and *reading*
  without a search — after an earlier version claimed more.

  **Narrowed, not closed, by `follow-an-identifier-exhaustively`.**
  `case_mention_documents` hands back a `chunk_id` per document, so a document
  reached by *identifier* — the pivot out of `case_mentions` — is now citable
  with no search: `test_an_agent_cites_a_carrier_without_a_ranked_search`
  proves it with `case_search` removed from the server. The gap above is
  unchanged for `case_list_documents`, which is the container-navigation
  journey and the case this note was written about: a container's child that
  carries no extracted identifier is still reachable, readable and uncitable.

- **The offset repair skips a document that vanished mid-pass, and no field of
  its report can say so.** `repair_mention_offsets` lists a casefile's document
  ids, then re-reads each one under a separate lock; when the row has gone by
  then, `get_document` returns `None` and the loop `continue`s *before*
  `documents_examined` is incremented. So the count cannot overstate what was
  read, but it understates it invisibly, and a pass that missed documents reads
  exactly like one that had none to miss — while those documents' mentions keep
  counting one occurrence twice. Reachable only by a concurrent delete between
  the two locked reads, which the shipped deployment does allow: the store's
  lock is per-process and `docker-compose.yml` runs the `cli` service and the
  API against one file. The repository has already made this judgement the other
  way once, in `IngestReport.refusals` — *"Reported rather than dropped: silence
  here reads as 'everything was ingested'"*. Parked, not fixed: the published
  `mentions` requirement enumerates what the report carries — documents, chunks,
  unlocatable chunks, positions corrected — so a fifth counter is a delta to
  that requirement and belongs in a change that can argue for it. Found by the
  silent-failure review of `a-chunk-begins-where-its-text-does`.

- **The `repair` CLI branch never reads `args.repair_command`.** The parser
  declares it with `required=True`, and `main` branches on
  `args.command == "repair"` and then runs `repair_mention_offsets`
  unconditionally. Correct today, because argparse admits exactly one value —
  and latent: the day a second subcommand is added under `repair` (the group's
  own help, "recompute derived data an earlier ingest recorded wrongly", plainly
  anticipates one), invoking it will silently perform the mention-offset
  *write* and hand back a plausible four-field report for a pass nobody asked
  for. A write running under another command's name is the worst shape this can
  take. The neighbouring `document` branch, twelve lines above, does dispatch on
  its own discriminator. One line to close; parked because a code change now
  needs its own change directory.

- **`recompute_mention_offsets` takes an unscoped chunk-id mapping.** Its
  predicate is `WHERE chunk_id = ?` alone, so nothing in the store constrains
  the write to one casefile — the compartment is held only by
  `repair_mention_offsets` deriving the ids from documents of the casefile it
  resolved. Every other write on the port is keyed by an owning entity, and
  `replace_chunks` twenty lines above argues the point at length: it derives
  `document_id` and `casefile_id` from the parent chunk rather than trusting the
  caller, because a compartment breach must be *"unreachable rather than merely
  unused"* on a seam a second producer will arrive through. This new method is
  the same kind of seam, written the other way. Not reachable today: one caller,
  ids derived from a resolved casefile, and no adapter may reach the store. The
  fix is a `casefile_id` parameter in the predicate; parked because changing a
  port signature deserves an argued proposal rather than a drive-by.

- **The published `mentions` requirement "mentions are written in the same
  transaction that writes its chunks" now has a second writer, and nothing says
  the reading that reconciles them.** `recompute_mention_offsets` updates a
  mention row in a transaction that writes no chunk. The guarantee the
  requirement exists to protect is intact — its own rationale is entirely about
  `chunk_id` staying resolvable, the repair never creates, replaces or re-points
  a mention, and its UPDATE matches nothing once a chunk id has been replaced —
  so "written" plainly means "created" in context. Parked because that reading
  is currently left to the reader: one clause in the requirement ("a later pass
  that corrects the derived document position is not such a write") would make
  the capability self-consistent, and editing a published spec needs a change
  directory.

- **"The fold is on" and "the identity says the fold is on" are computed from
  different things.** `app.py` decides `folding` from the summariser *object*
  (`chunk_summaries and chosen_summariser is not None`); `CorpusIdentity.__str__`
  decides whether to append the `|summariser=` component from the summariser's
  *name* being truthy. A summariser that exists but reports `name = ""` therefore
  folds summaries into what is embedded while recording the identity of an
  unfolded corpus — which is the direction that must never happen, because that
  corpus then opens under a plain configuration with bare chunks compared against
  summary-plus-chunk vectors and nothing downstream able to detect it. The
  reverse direction, appending a component that should be absent, is guarded and
  tested. Whitespace-only is the same asymmetry once removed:
  `CorpusIdentity(Contract(), "model", " ")` renders `|summariser= `, which is
  truthy here but which `build_summariser` would have stripped to nothing — two
  spellings of "no summariser" reaching two identities. **Not reachable through
  shipped configuration**: `summarising/__init__.py` strips and rejects an empty
  `summary_model`, so only `build_context`'s `summariser=` injection seam can
  produce it, and only test doubles use that today. Found by the silent-failure
  review of `one-value-for-corpus-identity`. Parked rather than fixed: the honest
  repair is to make the two definitions agree — refuse at the composition root
  when folding is on and the summariser's name is empty — which is a new refusal
  on a startup path and belongs in a change that can argue for it.

- **One test stands between this codebase and a re-applied `ADD COLUMN`.** The
  re-read under the write lock in `migrations.migrate` — the line that makes the
  earlier unlocked read safe — is caught by exactly one test,
  `test_the_version_is_re_read_under_the_write_lock`
  (`tests/test_migrations.py`). Measured by deleting the re-read and running the
  whole suite: 709 passed, 1 failed. Skip or delete that test and the seam is
  unguarded with no second signal anywhere, on a race the code itself documents
  as real — `docker compose up` and `docker compose run cli` share a data
  directory and can both open a store on the first run after an upgrade. Found
  by the silent-failure review of `three-owners-in-the-store`. Parked rather than
  fixed: a second signal means either a second concurrency test, which is slow
  and flaky by nature, or a structural guard that makes double application
  impossible, which is a change to the ladder rather than to its coverage.

- **The race test's closing assertion reads stronger than it is.**
  `test_the_version_is_re_read_under_the_write_lock` ends with
  `assert "text_source" in columns_of(store)`, which does not distinguish who
  added the column — the competing migration or the outer one. The test's real
  teeth are `assert raced` plus the fact that a double-applied ladder raises
  `duplicate column name`. That is adequate, and the assertion is not wrong; it
  just certifies less than a reader would take it to. Same family as the window
  test's `narrowed` guard recorded above. Parked: tightening it means asserting
  which process stamped the version, which the store does not record.

- **A window test named for the budget passes whatever the budget is.**
  `test_widening_is_switched_off_by_a_budget_at_the_chunk_size`
  (`tests/test_section_windows.py`) builds a `SearchService` with
  `window_max_chars=1` and asserts nothing widened. Instrumented with the budget
  forced to 3000 instead, **it still passes**: the document is about 1,100
  characters in four chunks, the query matches all four, so `_keep_clear` and
  `_avoid` leave nothing to grow into at any budget. It is the `CLAUDE.md`
  failure — "test fixtures with single-passage documents cannot exercise a
  window" — in a slightly larger disguise, alive in the file that records the
  rule. Found by the silent-failure review of `one-owner-for-the-window-rule`.
  Parked rather than fixed: the honest repair is a fixture with an unmatched
  neighbour to widen into, which changes what several other tests in that file
  retrieve. `tests/test_windowing.py` now covers the same guard directly and
  proves it by counting the store lookups, so the gap is covered even though
  this test still says less than its name.

- **The window rule captures its store lookup at construction.**
  `SearchService.__init__` passes `store.get_document_chunks_around` — a bound
  method object — to `Windower`, where the old code resolved `self._store` on
  every call. Replacing the store on a live `SearchService`, or patching the
  method on the instance or the class, is now silently ignored. Nothing in
  `src/` or `tests/` does that, so it is inert; it is recorded because it is a
  trap of exactly the shape the same change reasoned about for
  `MAX_RESPONSE_CHARS` and guarded against there. The budget half of the same
  hazard *was* live and was fixed in that change: `_window_max_chars` is a
  property reading `Windower.budget` rather than a second copy. Parked: making
  the lookup late-bound means passing the port after all, which is the trade the
  change deliberately declined.

- **A window test's guard does not guard what its message claims.**
  `test_a_response_that_hits_its_bound_narrows_and_says_so`
  (`tests/test_section_windows.py`) opens with
  `assert narrowed, "the bound was never reached, so this test says nothing"`,
  which reads as proof that the response bound was applied. It is not: `narrowed`
  is also set when another result's passage cuts a window back, and this fixture
  produces such results whether the bound was reached or not. Measured while
  moving the window rule to its own module — with `MAX_RESPONSE_CHARS`
  re-exported so the monkeypatch bound to a name nothing reads, the guard passed
  and the test failed three assertions later, on
  `all(h.text == h.chunk.text for h in narrowed)`, which holds only because the
  bound dominates at 1,200 characters. The test is not wrong today; its guard is
  weaker than its message, so it protects the monkeypatch's target by accident
  rather than by design. Parked: tightening it means telling bound-narrowed from
  neighbour-narrowed, which is the same distinction the `case_get_passage` entry
  below says the payload cannot express, and belongs with it.

- **`.DS_Store` is not in `.gitignore`, in a public repository on macOS.** Six
  sit untracked in the working tree today — repository root, `.acordia/`,
  `openspec/`, `openspec/specs/`, `src/` and `src/jackryan/`. Nothing has
  leaked, and `gitleaks` would not flag one anyway: they carry no credential.
  What they carry is a directory listing, so a committed root `.DS_Store` would
  name the gitignored files beside it — `.env` and `config.yaml` among them,
  which is the infrastructure-fingerprint class `CLAUDE.md`'s public-repo rule
  forbids. The footgun is `git add -A`, which is what a hurried commit reaches
  for; every commit so far has staged explicit paths instead. Parked rather than
  fixed because a `.gitignore` line is its own commit, and this surfaced while
  archiving specs.

- **The two scratch-delegate paths rebuild their result differently, and one of
  them drops a field by omission.** `router._extract_as` returns
  `dataclasses.replace(delegated, extractor=...)`, carrying every field the
  delegate set. `legacy_office.extract` builds a fresh `Extraction`, which
  overrides `media_type` to the legacy type **deliberately** — that is what the
  evidence is, and the conversion is only how the text was obtained — and drops
  `is_container`, which then defaults to `False`, by omission rather than by
  decision. Latent only: both delegates are `DoclingExtractor` and
  `SpreadsheetExtractor`, neither of which is ever a container. Parked rather
  than fixed during `one-owner-for-a-file-signature`, because switching to
  `replace` would start carrying `is_container` from the delegate — a real
  behaviour change inside a change whose whole claim was that it had none.
  Whoever unifies them should decide `is_container` explicitly rather than
  inheriting it.

- **The CLI document renderer's four conditional fields are pinned by no CLI
  test.** `cli._render_document` adds `found_at` and `children` only when they
  say something, and `summary`/`summary_by` only when a summary exists. Deleting
  the `found_at` and `children` blocks outright leaves the suite green: the
  three `found_at` assertions in `tests/test_hierarchy_provenance.py` are on the
  **agent** surface, not the CLI renderer, and
  `test_the_two_human_surfaces_agree_on_every_shared_document_field` runs on a
  plain-folder corpus where none of the four triggers, so its CLI-side
  assertion pins "added nothing here" rather than the intended divergence.
  Pre-existing — those blocks were unpinned before the renderer was shared too —
  and found by the pre-merge review of `one-renderer-for-the-two-human-surfaces`.
  Closing it needs a container fixture in a test that otherwise has no use for
  one, which is why it is recorded rather than done: the honest fix is a
  CLI-level test of an expanded document, not a wider fixture for this one.

- **Mentions are write-only through the storage seam, and the obvious fix does
  not work.** A `Mention` enters the store as a parameter of `replace_chunks`
  and comes back only as aggregate counts through `mention_facets`. There is no
  per-row read, so `tests/test_mentions.py` reaches `context.store._db` through
  a raw-SQL helper at twelve call sites. The 2026-09-05 architecture review
  proposed closing this with `get_mentions(chunk_ids) -> dict[str, list[Mention]]`,
  mirroring `get_chunks`.

  **That was planned, scoped, and then dropped, because a chunk-keyed read
  cannot express what any of those tests assert.** All twelve reads are
  casefile-scoped, and every one of the six tests asserts a casefile-wide
  invariant — "no mention survived anywhere", "these rows are unchanged". A
  chunk-keyed read returns only mentions attached to chunks it was handed, so
  it is structurally blind to exactly the failure mode: after a casefile is
  deleted there are no chunk ids left to ask about, and
  `get_mentions([])` returns `{}` — the deletion test would pass with every
  mention still in the store. Two more of the six assert referential integrity
  (a mention naming a chunk that no longer exists), which the same shape makes
  vacuously true.

  So the addition would have had **no production caller and no test using it
  either**, on a port whose every other read method has a caller. The
  alternatives and why each was set aside: a casefile-keyed read converts four
  of six but is the unbounded read `mention_facets`' own docstring argues
  against, and still has no caller; the shape that would earn its place is a
  production consumer — passage-level mentions on the agent surface — which is a
  new capability rather than a refactor. Revisit when something actually needs
  to read a mention.

  **Something now does, and it is the aggregate shape rather than the proposed
  one.** `follow-an-identifier-exhaustively` added
  `StorePort.documents_with_mention`, which reads the `mentions` table and
  returns documents, occurrence counts and a passage id — a production caller
  reached from all four surfaces. So the port is no longer write-only for
  mentions. The chunk-keyed `get_mentions(chunk_ids)` still has no caller, and
  none of the twelve raw-SQL reads in `tests/test_mentions.py` changed: they
  assert casefile-wide invariants that an aggregate cannot express either, for
  the same structural reason recorded above. Revisit again only if something
  needs one chunk's mentions.

- **Every agent-surface failure now passes through one place, and that place
  emits nothing.** `returns_error_payload` (`interfaces/mcp/errors.py`) reduces
  a `JackRyanError` to `{"error": code, "message": text}`, discarding the type
  and the traceback, and there is no logging call anywhere in `src/jackryan` —
  `grep` for `import logging`, `getLogger` and `logger.` returns nothing, and
  `services/search.py:400` concedes it in a comment. This was tolerable as eight
  visible three-line blocks; it is more pointed now that the surface has exactly
  one funnel. An analyst asking why the assistant reported an empty casefile has
  no artifact to consult. Parked rather than fixed: giving this project a logger
  is its own change, with its own decisions about destination, level and what a
  public repo may write to disk. Raised by the silent-failure review of
  `one-error-translation-on-the-agent-surface`, which correctly noted the
  refactor created the funnel without filling it.

- **A lazily-discovered misconfiguration reaches the agent as ordinary data, and
  the two adapters disagree about it.** `RerankerUnavailable` is a `ConfigError`
  raised at query time from `services/search.py:366`, deliberately not caught
  there — the comment says an instance configured for a reranker it cannot load
  "must say so rather than serve the fused order as though nothing were wrong".
  On the agent surface it becomes `{"error": "config_error", ...}`, which only
  the model sees; whether a human ever learns of it depends on whether the model
  mentions it. On REST the identical exception is a **500**, because
  `server.py:32-37` has no `ConfigError` entry and the handler falls back. Same
  failure, same instant, two dispositions. Pre-existing — it sat inside
  `case_search`'s old `try` too — and unchanged by that refactor, which is why it
  was not fixed there. `CLAUDE.md`'s rule has two categories, fatal-at-startup
  and transient-at-runtime, and this is a third the codebase has not named:
  wrong configuration discovered lazily.

- **`case_get_passage` reports a detected corpus inconsistency as an ordinary
  un-widened passage.** `interfaces/mcp/server.py` falls back with
  `body = window.text if window else chunk.text`, and `_slice`
  (`services/windowing.py:171`) returns `None` for two unrelated reasons: a window
  that would not help, and a chunk whose stored text no longer matches its own
  offsets — which its docstring says detects a half-completed ingest leaving new
  text against old offsets. Both collapse to `window is None` and the payload
  carries nothing to tell them apart. The search path is honest about the
  analogous case, emitting `narrowed` and `ranking: rerank-unavailable`. Parked:
  distinguishing them means a new payload field on a published tool surface.

- **An unbuildable reranker is rebuilt on every search.** `reranking/model.py`
  caches only on success — `self._model` stays `None` when `_load` raises — so
  `check()` at `services/search.py:366` re-runs the import and the model build
  once per request, after both retrievers and fusion have already done their
  work. Harmless while no reranker is named by default, which is why it is
  parked; it becomes a per-query cost the day one is.

- **`mcp-tool-surface`'s "SHALL NOT raise" is still violated by the untyped
  conversions.** `int(limit)` in `case_search` and `int(offset)`/`int(limit)` in
  `case_read_document` raise `ValueError`, which `returns_error_payload`
  deliberately does not catch — widening it to `Exception` would dress a crash
  as an answer. So a non-numeric `limit` from an agent still escapes as a
  transport failure. Pre-existing and unchanged. Parked because the fix is a
  validation decision (clamp, refuse, or coerce) belonging to whichever change
  owns the surface's argument handling, not to a refactor of its error
  translation.

- **The pre-filter sniffs before `_check_readable`, and the fix so far is
  per-symptom rather than a moved gate — so the next thing on this path
  inherits the gap.** `services/ingestion.py:217` asks `extractor_for` — which
  now opens the file — before `_ingest_work` reaches the readability checks at
  `:339`. The root cause is that ordering, not any single symptom of it. The
  symlink symptom is closed at source (`sniff_suffix` declines a symlink before
  opening anything, so the guard no longer stands alone), but that is a patch
  on one case, not a moved check: `MAX_FILE_BYTES` still does not bound the
  sniff, and a zip's whole central directory is still parsed before any size
  check. Measured by review: an 18 MB archive of 200,000 entries costs ~7x its
  size in peak RSS, and `namelist()` correctly does not decompress, so the entry
  table is the cost rather than a classic bomb. `MemoryError` is caught by the
  net in `sniff_suffix`, so the run survives; what is left is transient memory
  pressure and, at multi-gigabyte sizes, an OOM kill no in-process handler can
  prevent. Bounded by file size, needs a hostile multi-gigabyte archive, and the
  analyst chooses the dump path — so it is parked rather than blocking. The
  fix is to run the symlink and size checks *before* the pre-filter, once, so
  every file on this path is covered rather than each symptom as it is found;
  it is a change to the service's ordering rather than to routing, and it wants
  its own change so the refusal semantics for every file are decided together.

- **`_unsafe_reason` misses backslash, NUL and Unicode traversal forms — and
  nothing escapes anyway.** Found by a security review of the RAR change, and
  measured rather than argued: 18 hostile entry names were driven through the
  guard and through materialisation, and `..\..\windows\system32\x.txt`,
  `C:\Windows\x.txt`, `a\x00b.txt`, `‥‥/x.txt` (U+2025), `．．/x.txt` (fullwidth)
  and `etc／passwd` (fullwidth solidus) are all admitted by the guard. **Every
  one of the 18 landed inside the extraction root regardless.** The containment
  is not this function: `services/ingestion.py:306-314` takes *only* the suffix
  from an entry's name and writes it under a generated ordinal, and a suffix
  cannot hold a path separator. The guard is defence in depth on top of that,
  and its gaps are reachable only if that materialisation is ever changed to use
  the entry's own name — which is the thing its comment argues against.
  Two consequences worth carrying: a NUL in the *suffix* reaches
  `Path.write_bytes` and raises `ValueError: embedded null byte`, which
  `_expand`'s broad `except` at `:325` turns into a refusal — so it costs that
  one archive's remaining entries rather than aborting the run; and the guard is
  shared by `ZipExtractor` and `TarExtractor`, so tightening it is a change to
  ZIP and tar behaviour and did not belong in a proposal about RAR. Parked, not
  fixed: the fix is `os.path.splitdrive`, an `ntpath` check, a NUL rejection and
  NFKC normalisation before the parts test, and it needs its own change with
  ZIP and tar fixtures.

- **An entry over the per-entry cap is dropped by all three container
  extractors with no refusal.** `iter_children` in `ZipExtractor`,
  `TarExtractor` and `RarExtractor` all `continue` past an entry exceeding
  `MAX_ENTRY_BYTES` (512 MiB) without recording anything, while `extract()` has
  already listed it — so the container's own searchable text names a document
  that never exists, and nothing says why. The published scenario "An oversized
  entry inside a container is refused"
  (`openspec/specs/document-ingestion/spec.md:141`) asserts it "is refused", and
  it has no test. Parked rather than fixed: the two passes would need to agree
  on a shared filter that can report, which changes ZIP and tar behaviour and
  did not belong in a proposal about RAR. The RAR path deliberately reproduces
  the existing behaviour rather than inventing a third one.

- **One file is resolved three or four times per ingest.** `_resolve` is reached
  from the pre-filter (`services/ingestion.py:217`), from `extract`, from
  `_expand`'s own `extractor_for` and from `iter_children` — measured at 3 for a
  content-routed document and 4 for a content-routed container, each a fresh
  open and, for a zip, a fresh central-directory parse. The pre-existing code
  already resolved as often by suffix, so this is not new; what is new is that
  each resolution can now do I/O. Bounded and acceptable at the real dump's
  scale (1,922 files, 64 unroutable, ~32 KB read each now that only OLE2 pays
  for the megabyte prefix). Parked: if it ever matters the fix is to carry the
  resolved `(extractor, suffix)` on `_Work` from the pre-filter, not to cache
  inside the router — a cache keyed on a path would have to decide when a file
  changed underneath it.

- **A delegate's exception text now reaches the unauthenticated REST ingest
  response for files that never reached a delegate before.** `_extract_as`
  wraps a delegate failure as `{name}, read as {suffix}: {type}: {message}`,
  which becomes `IngestOutcome.detail` and is returned by `server.py:247` — a
  route `summarising/model.py:30-32` already names as an unauthenticated
  disclosure channel. The filename half was already there via the
  `no extractor accepts {path.name}` refusal; the new half is content-derived
  text from docling, openpyxl, `extract-msg` or Pillow. The lineage string
  itself is safe and never reaches the agent surface at all — nothing under
  `interfaces/` reads `.extractor`, `.refusals` or `.detail`. Parked as
  informational: it belongs with whatever change decides what that route is
  allowed to say, not with routing.

- **A filename ending in a quote character defeats format routing entirely.**
  The routing half of this is **fixed** — see `## Fixed` below. What stays
  parked is the half the entry below owns: these five files were dropped from
  the 2026-09-02 reingest without appearing in its report at all, and a routing
  refusal is still invisible on every surface. Fixing routing narrowed the set
  of files that can vanish; it did not make a vanishing visible.

- **A routing refusal is invisible on every surface, so the ingest report
  overstates coverage.** `IngestReport` carries `refusals`
  (`services/ingestion.py:55`), populates it from four places (`:224`, `:296`,
  `:304`, `:328`), and defines `complete` as
  `self.exhausted_by is None and not self.refusals` (`:75`) — so the object knows
  it is incomplete. No surface says so. The CLI's human output iterates
  `report.outcomes` and prints `"{ingested} ingested, {failed} failed"`
  (`cli.py:253-259`); its `--json` branch emits `ingested`, `failed` and
  `outcomes[]` (`:236-252`); the REST route returns `ingested` and `failed`
  (`server.py:237-240`). `refusals` and `complete` appear in none of the three.

  Measured on the 2026-09-02 reingest, and the reconciliation is exact:
  **1,922 source files = 1,760 stored + 98 tried-and-failed + 64 refused by
  routing.** The report said `1760 ingested, 98 failed`, which invites the reader
  to conclude 1,858 files were considered. The 64 were dropped in silence — grep
  the whole run log for `.ics`, `.rar`, `.bat`, `.mp3`, `.p7s` or a quote-suffixed
  name and it returns nothing. They are: `.ics` 29, `.rar` 26, `.docx'` 4,
  `.bat` 2, `.mp3` 1, `.p7s` 1, `.doc'` 1. The 98 failures, by contrast, are each
  reported with a reason and are honest.

  Why this is worse than a missing log line. The MCP surface's own `INSTRUCTIONS`
  teach an agent that "a coverage claim names what was searched" and that
  "absence of evidence is not evidence of absence" — and the ingest report is the
  only place an operator learns what the corpus is made of. Twenty-six RAR
  archives are the sharp end: the container extractors cover ZIP, tar and
  mailboxes, RAR is not among them, so whatever those hold was never examined and
  a search for it returns an honest-looking empty result. `docs/design.md` § 5
  lists container recursion as "(ZIP, mailboxes, PST)", so RAR is a gap in the
  design rather than a regression, but the corpus does contain 26 of them.

  Parked, as three separable pieces: print `refusals` and `complete` on all three
  surfaces, which is small and closes the misrepresentation; add a RAR extractor,
  which is a dependency decision (`rarfile` needs an external `unrar`); and the
  quote-suffix routing bug above. The first is the one that matters, because
  without it every future corpus silently under-reports what it skipped.

- **A `.docx` can fail inside docling with a conversion error, and the message
  does not say what the document did wrong.** One personal-data form in the
  first real dump raises `could not extract … with docling: Conver…` where its
  three neighbours in the same dump raise the honest `produced no usable text`.
  One file in 1,599 supported ones, so it is rare rather than structural, and it
  is correctly reported as a failure rather than stored empty. Parked: worth a
  look only if a second instance appears, since one sample cannot tell a
  malformed document from an extractor bug.

- **Fifteen page-bearing PDFs escalated through the recognition ladder and still
  yielded nothing.** All from the first real dump, and the shape says what they
  are: single-surname filenames — personal identity documents that were
  photographed rather than scanned. One carries zero font objects and five
  embedded images, so it is image-only, rung one had nothing to find, and
  `rapidocr` under `eslav` returned nothing usable from the photograph. Others
  in the set do carry text structure (one has 36 font objects and no images) and
  still produced nothing, which is the more interesting half. The designed
  answer to the first half is rung three, and `vlm_model` is empty by default
  because it downloads weights and is much slower. Parked: this is the
  measurement that should decide whether rung three is worth recommending, and
  it needs the scanned-documents slice of M3 rather than a note.

- **`embed_url`, `llm_url` and `api_key` are read into `Profile` and consumed by
  nothing.** `grep` finds them only in `config.py`. They are reserved seams, and
  `config.yaml.example` describes the `remote` profile as though pointing them at
  an endpoint did something. Do not describe the `remote` profile as working
  until it is.

  **Re-measured 2026-09-01 (later the same day), and the earlier figures in this
  entry were wrong.** They claimed the local e5-large costs ~96 ms per chunk,
  inferred from a "1h06m" production ingest. Both numbers are wrong. Measured
  directly through `build_embedder`, on a contract-sized (2,000-char) Russian
  chunk: **414 ms per chunk**, and *batching buys nothing* — 433/427/416 ms at
  batch 1/8/32, because ONNX Runtime's CPU provider already saturates every core
  on one chunk. And the dump's own `documents.created_at` histogram shows **seven
  consecutive hours with no gap** — 5h52m, not 1h06m, for 1,502 documents. The
  two corrected figures reconcile exactly: 32,989 chunks x 414 ms = 3h47m of
  embedding, plus 2h04m of everything else, against 5h52m observed. So embedding
  is **65% of the ingest**. The old entry's *conclusion* — that embedding is the
  dominant cost and the seam is where to attack it — survives and gets stronger;
  its arithmetic did not. Anyone quoting 27 ms against 96 ms was comparing a
  measured number to an invented one.

  **`bge-m3` on the GPU boxes, measured from this Mac, not on-box.** A dedicated
  `bge-m3` FP16 unit on each box, reached over HTTP, returns
  **1024 dimensions at L2 norm 1.000000** — the same width *and* the same
  normalisation as e5-large, so a corpus holding both kinds of vector is
  undetectable by shape. Throughput, at 111 ms RTT: **batching beats concurrency
  and 32 concurrent single requests is worse than useless** — one request of 128
  inputs gives 32 chunks/s, four concurrent requests of 32 give 50 chunks/s, but
  32 concurrent single requests collapse to 6 chunks/s against 22 at eight. At 50
  chunks/s the embedding leg would fall from 3h47m to 11m, putting a full reingest
  at roughly 2h15m — extraction-bound, and extraction offload is the do-not-do
  recorded below.

  **The endpoint is bit-deterministic**, which matters for how identity would be
  built: six calls with the same input returned six byte-identical vectors
  (SHA-256 of the serialised floats). So the embedder's identity could be
  *behavioural* — a hash of a probe vector — rather than a declared model name.
  The difference is not cosmetic. A declared identity trusts the operator to
  describe their infrastructure honestly, and points `embed_url` at bge-m3 while
  `embed_model` still says `intfloat/multilingual-e5-large` opens a mixed corpus
  silently. A behavioural one verifies the weights instead of believing a label,
  and survives load-balancing across two boxes serving the same GGUF.

  **The real blocker is a published requirement, not the missing code.**
  `openspec/specs/hybrid-search/spec.md:16-17` says both retrievers "SHALL be
  available with no endpoint configured, so an instance can search its corpus
  offline", and `services/search.py:245` embeds the query on every search. A
  remotely-embedded corpus therefore cannot be *searched* while the endpoint is
  down, and the halves cannot be split — a bge-m3 query vector against e5-large
  passage vectors is meaningless, and e5 also prefixes its input (`"passage: "` /
  `"query: "`, `embedding/model.py:14-15`) where bge-m3 does not. So the seam
  tethers reads, not just writes, and taking it means knowingly withdrawing the
  offline-search guarantee. Parked on that, not on the implementation work.

  **Unexplored, and the option that would keep the guarantee:** the same
  OpenAI-compatible `EmbedderPort` pointed at `127.0.0.1` — `llama-server` with
  Metal on the development Mac, serving the same 1.1 GB `bge-m3-FP16.gguf`. One
  implementation, one different URL, endpoint shipped with the instance so
  offline still holds. llama.cpp is not installed here, so whether Metal on an
  M3 Max beats 414 ms of ONNX CPU is unmeasured — an open question, not a promise.

- **Re-running an ingest is idempotent in outcome and full price in cost.**
  `_ingest_work` calls `self._router.extract(work.path)` unconditionally
  (`services/ingestion.py:318`), then `_rebuild_chunks` re-chunks and
  **re-embeds** every document (`:381`) and `replace_chunks` wipes and rewrites
  the chunks, FTS entries and vectors. The outcome status distinguishes
  `reingested` from `ingested`, so nothing is silently wrong — but a second run
  over the same folder costs the same hours as the first, not a resumption. The
  1502-document dump took **5h52m** — corrected 2026-09-01 from the "1h06m"
  originally recorded here, which nothing supports: the `documents.created_at`
  histogram is seven consecutive hours with no gap, so it was one continuous run
  and the shorter figure was not a measurement of it. A re-run to pick up the 19
  extraction gaps after enabling a better rung costs those six hours again.
  Parked: skipping a document whose content hash and extractor version both match
  would make a re-run incremental, and it needs an extractor-version column to be
  safe. Worth more than it looks — at 65% of that cost being embedding (see the
  `embed_url` entry), an incremental re-run is the cheapest large win available
  without touching the embedder at all.

  **"Idempotent in outcome" is true of the counts and false of the bytes.**
  Established 2026-09-02 by reingesting the same 1,922-file folder on the same
  pinned `docling==2.122.0` and diffing the result against the previous corpus,
  matched on `content_hash` rather than filename. The document set is identical —
  1,760 documents, 0 hashes on either side alone — and every derived count is
  exact: **36,305 chunks against 36,305**, and all six extractors matching to the
  document (`docling` 1137, `spreadsheet` 227, `legacy-office+docling` 177,
  `image` 138, `legacy-office+spreadsheet` 79, passthrough 2). But **42 documents
  came back with more extracted text**, 1,248 characters in total, every delta a
  multiple of 16, and the diff says exactly what they are: `\n<!-- image -->\n`
  placeholders, 78 of them, that the earlier run did not emit for the same input.
  No document's *prose* changed; only docling's markers for where embedded images
  sit. The cause is not established — same version, same profile — so treat
  docling's picture detection as run-dependent rather than deterministic.

  Two consequences worth carrying. First, an incremental re-run keyed on
  `content_hash` (parked above) is *not* threatened by this: the hash is of the
  source bytes, which do not move. Second, `chunking-and-embedding`'s
  reproducibility requirement is unharmed — it says the same *text* and contract
  produce the same chunks, and the text is what varied, one level upstream. But it
  does mean a corpus rebuilt from the same folder is not byte-comparable to its
  predecessor, so a retrieval measurement taken across a reingest boundary is
  comparing two slightly different corpora. Small here: 78 placeholders in 61.5 M
  characters, and the chunk count did not move at all.

- **`CoreMLExecutionProvider` is available and is 4.5x *slower* than CPU.**
  Measured 2026-09-01 on an M3 Max, same `intfloat/multilingual-e5-large` weights
  through `fastembed`'s `providers=` argument: **1,866 ms per chunk on CoreML
  against 414 ms on CPU**, and 7.3 s of session load against 0.7 s. Onnxruntime
  says why on the way past: "number of partitions supported by CoreML: 146 number
  of nodes in the graph: 1237 number of nodes supported by CoreML: 786". A third
  of the graph stays on CPU, so the model is cut into 146 pieces and the
  round-trips between the two providers cost more than the acceleration returns.
  Recorded because the reverse is the intuition — the box has a GPU and a neural
  engine, `onnxruntime` lists the provider, and turning it on looks like free
  speed. It is not, and a future reader should find the measurement rather than
  repeat it. Not parked as work: there is nothing to do.

- **One of the two GPU boxes answers `curl` and refuses `httpx`, reproducibly.**
  `curl` returns HTTP 200 under both `-4` and `-6`; `httpx` raises
  `ConnectError: [Errno 9] Bad file descriptor` from `connect_tcp`, in a fresh
  process with no other traffic, against the hostname *and* against the bare
  address. Its twin, on the same port, from the same client, in the same
  process, works. Both resolve to a single A record with no AAAA, so this is
  *not* the dead-IPv6 case recorded further down for `huggingface_hub`.
  Unexplained. It matters only if something later depends on reaching both boxes
  from this Mac over `httpx`: the throughput figures in the `embed_url` entry were
  taken against the working box alone for that reason, and the "two boxes double
  it" claim is therefore *unverified from here* even though both services are up.

- **`uv sync` builds the environment on Python 3.14 while CI and the container are
  on 3.12.** There is no `.python-version` in the repository, `requires-python` is
  `>=3.12`, and uv resolves to the newest interpreter it can find — 3.14.7 here.
  `.github/workflows/tests.yml:26` pins `uv venv --python 3.12` and the Dockerfile
  is `FROM python:3.12-slim`, so a plain `uv sync` gives a developer an
  interpreter that neither gate uses. It resolved and installed cleanly, which is
  what makes it worth writing down: nothing failed, and the divergence is silent.
  Found rebuilding the environment before a full reingest 2026-09-01 and worked
  around with an explicit `uv sync --python 3.12`. Parked: a one-line
  `.python-version` would close it, and that is a repository change rather than a
  note, so it is not taken here.

  **And the interpreter drift is not cosmetic, because `fastembed`'s own
  requirements are keyed to it.** Its markers read
  `numpy>=1.26; python_version == "3.12"` against
  `numpy>=2.3.0; python_version >= "3.14"`, and
  `onnxruntime>=1.17.0,!=1.20.0,!=1.24.0,!=1.24.1` for 3.12 against
  `onnxruntime>=1.24.2` for 3.14. So letting uv pick the newer interpreter
  silently swaps the numeric stack underneath the embedder, which is the code
  that produces the vectors.

- **`uv.lock` is not a gate anywhere: neither CI nor the container reads it.**
  `.github/workflows/tests.yml:29` installs with `uv pip install -e ".[dev]"` —
  the pip-compatible interface, which resolves fresh from `pyproject.toml` and
  ignores the lockfile — with no `--locked` or `--frozen`, and the Dockerfile
  installs with plain `pip install --no-cache-dir .`. Only a developer running
  `uv sync` gets the locked set. So the lockfile pins one machine and the two
  gates resolve whatever is current on the day they run.

  That matters here rather than in general because of *what* is unpinned.
  `pyproject.toml:21-27` pins `docling` and `fastembed` exactly, with a comment
  explaining that fastembed 0.5.1 and 0.8.0 "embed the same model with different
  pooling, producing vectors of the same width that are not comparable" — "the
  one dependency change that can corrupt a corpus with no error anywhere". But
  the library that actually performs the matrix multiplications is
  `onnxruntime`, and nothing pins it: `>=1.17.0` with three exclusions admits
  everything from 1.17 upward. The corpus contract records
  `embed_library=fastembed==0.8.0` and is silent about it. So the documented
  hazard is guarded one level above where the arithmetic happens.

  Whether an onnxruntime minor actually moves the vectors is unmeasured, and it
  is the measurement that should decide what to do — a probe embedding whose
  hash is compared across two versions would settle it in minutes, and the
  endpoint determinism check in the `embed_url` entry is the same technique.
  Recorded for the corpus ingested 2026-09-02 so a later one can be compared:
  **Python 3.12.14, fastembed 0.8.0, onnxruntime 1.29.0, numpy 2.5.2,
  docling 2.122.0**. Parked: pinning onnxruntime, or adding it to the contract,
  or having CI install from the lock, are three different answers with different
  costs, and choosing needs the measurement first.

- **Chunk identifiers are regenerated on every ingest, so nothing may be keyed to
  them across one.** `_rebuild_chunks` assigns `uuid.uuid4().hex` per chunk
  (`services/ingestion.py:370`) while the *document* id is deliberately reused
  via `find_document_by_hash`. Document-keyed work therefore survives a reingest
  and chunk-keyed work does not. This decides the shape of two M3 features:
  per-chunk summaries and mention offsets must either be produced in the same
  pass that creates the chunks, or be keyed on `(document_id, ordinal)`. Nothing
  currently depends on chunk ids surviving, so this is a design constraint to
  respect rather than a defect to fix.

- **Per-chunk contextual summarisation would change vector semantics and corpus
  identity would not notice.** `docs/design.md` § 5 puts per-chunk contextual
  summaries in the *Enrich* stage, enabled "later for retrieval quality" — and a
  contextual summary improves retrieval by folding context into what gets
  embedded. `Contract` has no field for it, so turning it on would append vectors
  built one way to a corpus of vectors built another, both at the declared width,
  and `_verify_meta` would pass. That is precisely what `corpus_fingerprint` was
  written to prevent; its own docstring calls itself "the last place that can be
  caught". Parked with a condition attached: whichever change builds
  summarisation must add a contract field for it in the same change, or it ships
  a corpus of mixed semantics with no error.

- **~~A third reranker exists that the rerank measurement never saw.~~**
  Superseded on 2026-09-01 by measuring it — see the three-model reranking entry
  below. `bge-reranker-v2-m3` failed the same way as the other two, so this is
  recorded as closed rather than deleted: the next person to notice a multilingual
  reranker on those boxes should find the measurement, not repeat it.

- **Offloading docling to a GPU server is not worth it for born-digital files and
  is actively harmful for scans as that server is configured.** Measured against
  `docling-serve` 1.26.0 (CUDA image, `DOCLING_DEVICE=cuda`): the async endpoint
  reaches 4.64 files/s on DOCX against ~5 files/s in-process, and the *sync*
  endpoint manages 0.48 files/s and does not scale — identical throughput at
  parallelism 1, 4 and 12. Worse, its OCR cannot read Cyrillic: the same scan
  returns byte-identical output with **zero** Cyrillic characters under
  `easyocr`, `tesserocr` and `rapidocr` after clearing both `/v1/clear/results`
  and `/v1/clear/converters`, so `ocr_engine` and `ocr_lang` are ignored, while
  local `rapidocr`+`eslav` reads the same file correctly. `docs/design.md` § 5
  offers "optional out-of-process offload for throughput"; the measurement says
  the throughput is not there and the quality would regress. Parked as a
  do-not-do until the server's model cache carries non-Latin OCR models.

- **A transport-level failure reaching Hugging Face kills an ingest instead of
  falling back.** `fastembed`'s `download_model`
  (`common/model_management.py:444`) catches only `EnvironmentError`,
  `RepositoryNotFoundError` and `ValueError` before trying `url_source`, the
  GCS tarball. `huggingface_hub` 1.29 talks `httpx`, which raises
  `httpx.ConnectError` and does no Happy Eyeballs — so on a host whose IPv6 is
  advertised but dead it takes the AAAA record, fails with `[Errno 65] No route
  to host`, and the working GCS mirror is never attempted. `ModelEmbedder._load`
  then reports `could not load embedding model`, which names the model and hides
  the network. Found priming the cache on the development Mac 2026-08-31, worked
  around by fetching the weights with `curl -4` straight into the cache layout;
  fastembed's own first attempt is `local_files_only=True`, so a populated cache
  needs no network at all. Parked: the honest fix is for the embedder to say
  which host it could not reach, and it belongs with the prefetch story rather
  than in a slice of its own.

- **A FastAPI test client and the agent surface's servers, built in one test
  module, abort the interpreter at teardown.** On macOS the suite reports every
  test passing and the process then exits 134 with
  `libc++abi: recursive_mutex lock failed` — a green summary and a failing exit
  code, which is the worst shape a CI failure can take. Bisected: deselecting
  either the module's REST tests or its MCP tests makes it clean, and each half
  is used elsewhere in the suite without trouble. `tests/test_result_shape.py`
  therefore compares the REST shape through `serialize_hit` rather than over
  HTTP, and `tests/test_rest.py` covers the route. **That reduced it and did not
  remove it** — it was still seen once in six runs afterwards, so do not read the
  change as a fix.

  **CI is unaffected, and that was checked rather than assumed.** The suite was
  run three times inside the project's own image — Linux, the platform every
  workflow uses — and reported `422 passed, 2 skipped` with exit code 0 each
  time, with no abort. The message is libc++'s, which is macOS's C++ runtime;
  Linux uses libstdc++ and does not reproduce it. Parked: the cause is a native
  teardown race below Python — onnxruntime and torch are imported by every run
  through `docling` — and finding it properly means debugging something this
  project does not own. Worth knowing before writing another test module that
  mixes the two, and worth re-checking if the suite ever fails in CI with a green
  summary.

- **A window reaches at most three passages either side, whatever the budget
  says.** `WINDOW_MAX_CHUNKS_EITHER_SIDE` in `src/jackryan/services/windowing.py`
  caps how far a result may wander from what actually matched, and it is a
  constant rather than a setting. An operator who raises `window_max_chars` far
  above the chunk size therefore gets less than they asked for, silently. Found
  while building the window rule. Parked: the honest fix is to derive the reach
  from the budget and the chunk size together, which needs the contract in the
  search service, and that is a wider change than this slice.

- **The response character bound governs the context added, not the passages
  found.** `MAX_RESPONSE_CHARS` stops results being widened once the response is
  full, but the matched passages themselves are always returned — fifty results
  at the contract's chunk size still exceed it. That is deliberate, and it is
  written into the `hybrid-search` spec: dropping evidence to save characters is
  a worse failure than a long response. Recorded because the constant's name
  reads like a hard ceiling and is not one.

- **Reranking is built and no model is recommended — now measured three times.**
  Both cross-encoders the embedding library registers made retrieval measurably
  worse on the project's evaluation set, and both took Ukrainian to zero; the
  figures and the trace are in `docs/handover.md`. A third model,
  `BAAI/bge-reranker-v2-m3` — the multilingual flagship, which `fastembed` does
  not register — was measured on 2026-09-01 over an OpenAI-compatible
  `/v1/rerank` endpoint, with the port implemented in a throwaway script and
  `build_reranker` substituted for that process only. Same harness, same
  built-in query set, same embedder, control run reproducing the recorded
  baseline exactly. It reproduced the same failure: fused recall@1 **0.882 ->
  0.647** and MRR@10 **0.926 -> 0.778**, English improving **0.714 -> 0.857**
  while Russian fell **1.000 -> 0.600** and Ukrainian **1.000 -> 0.400**.
  English improving is the evidence the wiring worked, so this is the model and
  not the integration. Three of three cross-encoders now trade this corpus's
  languages for English. The seam is finished and the setting stays empty.
  Parked: the pattern is strong enough that the next attempt should be a
  multilingual reranker chosen on Slavic evaluation results rather than on
  reputation, and 17 queries over 15 synthetic documents is still too small to
  settle it either way.

- **Keyword ranking inside one casefile depends on what the other casefiles
  hold.** `search_keyword` in `src/jackryan/storage/retrieval.py` filters rows by
  `c.casefile_id`, but orders them by `bm25(chunks_fts)`, and FTS5 computes bm25
  over the whole index — every casefile in the store. Adding a second casefile
  therefore changes the term statistics and can reorder results inside the first,
  as measured while building the evaluation harness: the same corpus in a second
  casefile scored differently on every keyword metric. No content crosses the
  boundary — the compartment holds for what is returned — but the *order* of a
  casefile's own results is influenced by material it cannot see, which is a
  weak side channel as well as a reproducibility problem. Found while writing
  `scripts/evaluate_retrieval.py`. Parked: the remedies (a per-casefile FTS
  index, or ranking by a statistic computed within the compartment) are a change
  to the storage seam and to what `hybrid-search` guarantees, not a line in a
  retrieval-quality slice.

- **Originals are never archived, though `docs/design.md` § 5 says they are.**
  The Finalize step of the ingestion pipeline is documented as "originals
  archived content-addressed within the casefile". Nothing in
  `src/jackryan/services/ingestion.py` does that: a file ingested from disk is
  read at the analyst's own path and never copied, and a document expanded out
  of a container is written to a `mkdtemp` workspace that is `rmtree`'d in a
  `finally`. The consequence reaches further than the missing feature — every
  document that says "reingest" as its remedy, including the corpus-identity
  refusal and the schema-migration floor, assumes the operator still holds the
  originals, which is precisely what the design said the workbench would hold
  for them. Found while designing the migration ladder, where "reingest is the
  migration path" was one of the three candidate approaches and was weakened by
  exactly this. Parked: archiving originals is a capability with its own storage
  and identity questions, not a line in a migration change.

- **A reingest does not reproduce a document's identifiers, and nothing records
  where a casefile was ingested from.** Both surfaced while judging migration
  approaches. Recording an ingest root would make "reingest" an actionable
  instruction rather than a hopeful one, and deriving document identifiers from
  content plus containment path would let a rebuild reproduce the citations an
  analyst has already written down. Together they are the natural next change
  after this one, and both alter what identity means, so they belong in a change
  with its own delta spec rather than grafted onto this one.

- **`read_as: text-layer` is the strongest provenance the surface offers, and
  nothing checks the page it claims to come from.** Rung one reads the PDF's
  content stream. Text an adversary rendered invisibly — white on white, behind
  an image, at zero size — is in that stream, is never displayed, and reaches
  the agent labelled as having come off the page: the value that says "trust
  this more than OCR". Found by review of the `extraction-quality-gate` change.
  Parked: detecting it means rendering the page and comparing it with the
  stream, which is a different capability from the escalation ladder and would
  need its own evidence about false positives. Worth doing before this workbench
  is pointed at documents supplied by an opposing party.

- **The escalation floor is a whole-document average.** `chars_per_page` divides
  total recovered characters by page count, so whether page 40 gets recognised
  depends on how much text sits on pages 1-39 — and whoever supplies the
  document chooses that. A hundred-page report with one scanned insert clears
  the floor comfortably and the insert is never read. Parked: `design.md` names
  per-page rung selection as a non-goal for this change, and doing it properly
  means the rung becomes a property of the page rather than the document, which
  changes what `text_source` means. Real, and the reason to revisit it is a
  corpus where it bites.

- **The vision rung runs on an unpinned `transformers`, and it produces corpus
  text.** Observed during the same image build: the container resolved
  `transformers 5.16.1` where the development venv holds 5.8.1. It reaches the
  project only transitively, through `docling-slim[models-vlm-inline]`, so
  nothing pins it — yet when `vlm_model` is set it is the library that reads the
  page, and what it returns becomes the chunks. That is the same class of gap
  `fastembed` and `docling` are pinned exactly to close. Lower severity than the
  `fastembed` case for the same reason `docling` is kept out of the fingerprint:
  a change here produces visibly different *text*, not invisibly incomparable
  *vectors*. Parked: pinning a transitive dependency of a pinned package is
  worth doing deliberately, alongside the decision about whether the image
  should carry the vision stack at all.

- **The container pulls the whole NVIDIA CUDA stack onto arm64, where nothing
  can use it.** Observed building the image on Apple silicon: `torch` 427 MB,
  `nvidia_cudnn_cu13` 444 MB, `nvidia_cusparselt_cu13` 221 MB, plus
  `cuda_toolkit` — none of which an arm64 Linux container without an NVIDIA GPU
  will ever execute. It comes from the `docling==2.122.0` pin, which resolves to
  `docling-slim` with the `models-vlm-inline` extra. Pre-existing, not introduced
  by the quality gate — that change touched no dependency — but it is gigabytes
  of dead weight in an image whose whole promise is "one container, runs
  locally", and it is worth knowing before anyone measures the image and blames
  the model prefetch. Parked: fixing it means choosing narrower `docling-slim`
  extras or a CPU-only torch index, which changes what the vision rung can do
  and so belongs with a decision about whether the image should carry it at all.

- **Every ingest now prints RapidOCR's own log lines and a progress bar.**
  Verifying the recognition engine at the start of a run builds it, and the
  library logs at INFO and draws a `Loading weights:` bar straight to the
  terminal — including for a run that contains no page-bearing document at all.
  Observed on `jackryan ingest <casefile> <folder-of-markdown>`. Cosmetic, not a
  correctness problem, and the verification it comes from is deliberate. Parked
  because the fix is to decide a logging policy for third-party libraries at the
  CLI adapter, and this repository has none to slot into; muting loggers wholesale
  is how real warnings get lost, so it deserves its own change rather than a line
  smuggled into this one.

- **Nothing bounds how long an ingest may spend, and recognition makes that
  matter.** `ExpansionBudget` bounds nesting depth, descendant count and
  extracted bytes — not time. `docs/design.md` § 5 names "a per-document time
  budget" as part of the Finalize step; no such thing exists in
  `src/jackryan/`. Recognition raises the cost of a page from milliseconds to
  seconds, and the `extraction-quality-gate` change makes image files ingestable
  for the first time, so an archive of five hundred small photographs sits well
  inside the byte ceiling and costs roughly a quarter-hour of CPU. Not
  introduced by that change — the shipped extractor already ran recognition on
  every PDF by docling's default, and the change makes born-digital PDFs
  *cheaper* — but it widens the input surface that reaches it. Parked: a time or
  work budget is its own design (per document? per run? what happens to what was
  already stored when it expires?) and belongs with the retry ledger, not inside
  a change about extraction quality. docling's own `document_timeout` pipeline
  option is the likely lever.

- **Naming drift: the store still calls corpus identity `contract`.**
  `initialize(contract_fingerprint=...)`, the `store_meta` key, the refusal text
  and the `"contract"` field in `/health` and `jackryan status` all say
  *contract*, while the specs and docs say *corpus identity* and the value now
  includes a profile setting. An operator comparing a refusal against `/health`
  sees a key named `contract` holding something wider. Parked because renaming
  the `store_meta` key needs a migration or a documented legacy name, and the
  JSON field is a published surface — both bigger than the change that exposed
  it.

- **`scripts/verify_model_paths.py` — `check_real_embedder` bypasses the
  application's model-cache resolution.** It constructs `ModelEmbedder` directly
  with `cache_dir=<tempdir>/models`, instead of going through `build_embedder`,
  which honours `JACKRYAN_MODEL_CACHE`. The Dockerfile sets that variable and
  prefetches the weights into it. So in an image built with
  `--build-arg PREFETCH_MODELS=true` and run offline — the second run mode the
  script's own docstring recommends — this one check tries to download into an
  empty cache and records FAIL, directly beside the script's message that "a
  failure here is a real finding, not a flaky environment". The other two
  embedder loads go through `build_context` and are unaffected. It also means a
  full run fetches the model into three separate temp caches and deletes them.
  Parked: found by review of PR #11 on 2026-08-26; it is a defect in a
  verification script carried by that PR, not in the archive the PR is for, and
  it cannot produce a false PASS. Fix by building the embedder from a `Config`
  through `build_embedder`, and letting the cache outlive the temp workspace.

- **`check_real_embedder`'s own width comparison is dead code.** `ModelEmbedder`
  already raises `EmbeddingError` on a width mismatch, so the script's
  `if width != contract.embed_dimensions` branch is unreachable. This is
  cosmetic, not a hole: a mismatch is still caught and still fails the run with
  an accurate message, verified by forcing one. Noted so nobody "fixes" the
  guard by weakening the one in `ModelEmbedder`.

- **A LibreOffice conversion is a lossy round trip and nothing records that it
  happened, beyond `documents.extractor`.** A `.doc` is read as whatever
  LibreOffice's DOCX writer made of it, which is not necessarily what Word 97
  would have shown. `text_source` says `native` — truthfully, since no
  recognition ran — so an analyst weighing a converted quotation has only the
  `legacy-office+` prefix to tell them a converter stood between the file and
  the text. Parked: a fourth `text_source` value would be the honest fix, but
  that vocabulary is published in `extraction-quality-gate` and consumed by the
  MCP payloads, so widening it is its own change with its own spec delta.

- **Legacy template and show suffixes are not registered.** `.dot`, `.xlt`,
  `.pot` and `.pps` convert through exactly the same path and would each be one
  line in `LEGACY_SUFFIXES` and `_TARGET`. None appears in the dump this change
  was written against, so none could be demonstrated, and a suffix nobody can
  check is a claim nobody can check. Parked deliberately: add them when a dump
  contains one, not before.

- **`accepts()` is suffix-based, so a legacy file with no suffix at all is still
  invisible.** The container sniff runs inside `extract`, after the router has
  already selected on `Path.suffix`. A file named `Договор` with OLE2 bytes is
  dropped by the directory-walk pre-filter exactly as it was before this change.
  This is the same root cause as the parked apostrophe-filename finding above:
  content sniffing as a fallback when the suffix is unknown. Parked with it,
  because they want one fix, not two.

- **LibreOffice parses untrusted documents as root in the container.** The image
  now carries `libreoffice-writer libreoffice-calc libreoffice-impress` — a
  large, historically CVE-rich parser for OLE2, BIFF and RTF — and hands it files
  from an untrusted dump. Neither the `Dockerfile` nor `docker-compose.yml` sets
  `USER`, so it runs as root with the default seccomp profile, full network
  access, and `/data` — the whole corpus and the SQLite store — writable.
  `--headless` is a UI switch and suppresses dialogs; it restricts no file,
  network or process access, so it is not a mitigation. Parked, and stated
  plainly rather than fixed: this widens an existing exposure rather than opening
  a new one, because docling and the OCR stack already parse untrusted PDFs as
  root in the same image. Excluding the JRE and the desktop integration via
  `--no-install-recommends` is a real reduction. The fix is a non-root user for
  the image, which touches the volume permissions and the compose file and is its
  own change.

- **A converted file is read by the delegate with no ceiling of its own beyond a
  flat byte limit.** `MAX_CONVERTED_BYTES` refuses a conversion that writes more
  than 512 MB, which closes the unbounded case, but the number is the same as
  `MAX_FILE_BYTES` by intent rather than by measurement — nothing has established
  what expansion ratio real legacy files actually produce. Parked: the honest
  version measures the ratio across a corpus and sets the ceiling from it, which
  needs a corpus this project does not yet have.

- **The retrieval harness treats an absent baseline key as a mismatch for
  `corpus` only, and five other load-bearing keys are still skipped.**
  `conditions_match` in `scripts/evaluate_retrieval.py` compares eight keys and
  skips any the baseline does not record. `embed-input-is-corpus-coupled` closed
  that fail-open for `corpus`. Of the rest, `embedder` and `chunk_max_chars` are
  genuinely subsumed by corpus identity, and `window_max_chars` is genuinely
  readability-only — `measure()` scores `hit.chunk.text` and never reads the
  window — but `reranker`, `query_set`, `queries`, `documents` and `limit` all
  move the recorded figures and are all still skipped when absent. `reranker` is
  the sharpest: it is a query-time profile setting, so it is outside corpus
  identity by design, and this project's own measurement is that both available
  rerankers made retrieval worse and took Ukrainian to zero. Parked: making them
  required is one line, but it decides that every operator baseline recorded
  before the change becomes incomparable until re-recorded, which is a call
  about the harness's contract rather than a defect in this one.

- **An incomparable run exits 0, so a stricter comparability check can convert a
  detected regression into a green run.** `scripts/evaluate_retrieval.py` prints
  "Not compared against the baseline" and returns 0, while the adjacent
  no-metrics case returns 1 with an explicit comment that it must not pass by
  default because it is the one thing that can see retrieval regress. Same class
  of defect, opposite exit code. It matters now because
  `embed-input-is-corpus-coupled` made an absent `corpus` key route every such
  run down that branch: an operator holding a pre-change baseline had a regressed
  run return 1 and now gets 0 until they re-record. The repository's own baseline
  is annotated and pinned by a test, so the shipped gate cannot enter that state
  silently. Parked: whether "cannot be compared" should be an error or a report
  is the harness's contract, and changing it belongs with the decision, not
  inside a change that only added a key.
- **`CLAUDE.md` points at an `openspec/config.yaml` that does not exist.** Line
  50 reads "Config at `openspec/config.yaml`", and `openspec/` holds only
  `changes/` and `specs/`. The file is auto-loaded into every session in this
  repo, so the wrong path is read before anything else and a future session can
  spend time looking for a file that was never there. Nothing depends on it —
  the OpenSpec CLI finds its root without one — so the cost is confusion rather
  than breakage. Parked: found while writing `embed-input-is-corpus-coupled`,
  which had no business editing that line.

- **`test_a_timeout_kills_the_whole_converter_tree_not_just_the_launcher` is
  flaky — "roughly one run in four" understates it under load.** Re-measured
  2026-09-05 during a session running several review agents concurrently: it
  failed on two consecutive full-suite runs and then twice more *in isolation*,
  where it had passed in isolation minutes earlier on the same checkout. A
  reviewer independently called it "reproducible, not flaky". Both observations
  fit the recorded cause — the test reads the grandchild's pid file before the
  grandchild writes it, so machine load widens the window until the race looks
  deterministic. It is not: CI's pytest gate passed on the same commits, and the
  code under it is byte-identical to `develop`. The rate is a function of load,
  which makes "one in four" a number to distrust rather than to quote.** Found while running the suite for the
  `mentions-and-facets` change and parked, not fixed: that change touches
  neither the test nor the legacy-office converter, and the flake reproduces on
  `origin/develop` at the same rate, so it is pre-existing rather than a
  regression. It fails as `FileNotFoundError: … /grandchild.pid` — the test
  reads the grandchild's pid file before the grandchild has written it, so the
  race is in the test's own setup rather than in the process-tree kill it is
  checking. The fix is to wait for the file with a bounded poll instead of
  assuming it is there. It matters because the assertion it guards is a real
  one: a converter timeout must kill the whole tree, and a test that fails at
  random teaches the reader to re-run rather than to look.

- **An entry excluded by `MAX_ENTRY_BYTES` is listed by the container and then
  silently absent from its children.** `ingestion/containers.py` — all three
  extractors, `ZipExtractor`, `RarExtractor` and `TarExtractor`. The listing
  pass puts every safe entry into the container's own text and its `entries`
  count; `iter_children` then drops an over-large one with a bare `continue` and
  no refusal. So a container document asserts an entry that produced no child,
  and nothing in `report.refusals` says why — the same shape as the refusals
  this pipeline reports for an unsafe name or a non-regular file, but without
  the report. An analyst reading the listing has no way to tell "that entry is
  in there and was too big to read" from "that entry is in there and its
  extraction failed". Noticed while fixing the RAR review findings and parked:
  it is pre-existing, it belongs to all three container extractors rather than
  to RAR, and reporting it wants the refusal to be carried out of a generator —
  which the `Child` contract has no channel for, so it is a change to the
  container seam rather than a line in one extractor.

## Fixed

- **~~A filename ending in a quote character defeats format routing
  entirely.~~** Fixed by `content-routing` on 2026-09-02. Selection stays
  suffix-first; where the registry claims nothing, the file's bytes are read and
  a format they positively identify is routed to its extractor. The five real
  files now ingest — four as `content-routed+docling`, the OLE2 one as
  `content-routed+legacy-office+docling`, 357k characters between them — and
  their `.bat`, `.ics`, `.p7s` and `.mp3` siblings are still refused, because
  there is deliberately no text fallback: "decodes as UTF-8" is not a signature.

  Two things worth carrying forward. The fallback had to go at
  `FormatRouter.extractor_for`, not `.extract`: `services/ingestion.py:217`
  skips a file whose `extractor_for` is `None` before `extract` is ever called,
  so a fallback known only to `extract` would have been inert on every folder
  walk — the one case it exists for. A mutation test pins that shape, and a
  second pins that a file with a claimed suffix is never sniffed. And a
  content-routed file is copied into a scratch directory under the resolved
  suffix before the delegate sees it, because every extractor keys its media
  type off `path.suffix` and a `KeyError` there is not an `ExtractionError` —
  it would end the run rather than fail one document.

- **~~The store has no migration path.~~** Fixed by
  `corpus-identity-and-schema-migration` on 2026-08-28. The baseline is frozen
  at schema version 4 and an ordered ladder of additive steps carries a store
  forward, with `text_source` as the first rung so a brand-new store climbs the
  same step an old one does — a runner exercised only by a fixture rots between
  the day it is written and the day it is needed. A backup is taken through
  SQLite's own backup API first, and three mechanical tests enforce the
  additive rule, the frozen baseline and the FTS trigger's column list.

- **~~Corpus identity is an unescaped `|`-joined string.~~** Fixed by the same
  change: each component escapes backslash, pipe and control characters, and
  deliberately not `=`, since `embed_library` contains `==`. Every reachable
  identity is byte-identical afterwards, so no store was invalidated. The parked
  note overstated the reach — no collision is constructible through a config
  file, because only `embed_model` is free text; what was reachable was a
  deceptive identity naming an embedder the instance was not running.

- **~~The embedder's width is never checked against the contract's.~~** Compared
  now at the composition root before the store is constructed. Read the guard
  narrowly: `build_embedder` builds both implementations from the contract, so
  configuration cannot make them disagree. It covers the seam where an embedder
  is supplied directly, and becomes the guard it reads like the day one learns
  its width from the model it loaded.

- **~~`text_source` reaches the agent but not the human.~~** Now on the CLI, both
  REST document endpoints and `case_list_documents`, under the same key and
  vocabulary the agent sees, with an unrecognised value collapsing to
  `unrecorded` on all four alike.

- **~~The contract fingerprint does not cover the embedding library version.~~**
  Fixed by the `contract-covers-embedding-library` change on 2026-08-26: the
  contract declares `embed_library`, the fingerprint covers it, and a declared
  version that is not the installed one is fatal at both configuration load and
  embedder construction. See `docs/handover.md` for the decisions.

- **~~`scripts/verify_model_paths.py` — the end-to-end check is weaker than its
  comment claims.~~** Fixed in #10 on 2026-08-26, and resolved the other way
  round from what the note proposed: rather than strengthening the check to a
  paraphrase with no shared content word, the comment was corrected to say what
  the check actually establishes — that the vector leg ran and returned, with
  retrieval quality explicitly out of scope. The defect was that the comment
  lied, and it no longer does.

- **~~The fingerprint did not record which embedder built the vectors.~~** Fixed
  by the `corpus-identity-covers-the-embedder` change on 2026-08-26. Of the two
  candidate fixes recorded here, the second was taken: corpus identity is
  composed at the composition root from the contract plus the embedder actually
  constructed, rather than adding an `embedder` field to the contract. An
  `embedder` contract field would have put an infrastructure selection in the
  corpus-coupled layer *and* duplicated a setting that already exists in the
  profile — two copies that can disagree, which is the shape of the bug being
  closed. The noted downside of the chosen fix was dealt with rather than
  accepted: `/health` and `jackryan status` now report the enforced identity, so
  the value an operator sees is the value that refused them.

- **A first-observed name can describe a later reading.** Surfaced by review of
  `preserve-duplicate-locations` (2026-09-08) and accepted rather than fixed.
  Now that `filename` and `containment_path` are first-wins while `media_type`,
  `extractor`, `extracted_text` and the chunks stay last-wins, one row can carry
  two readings: identical bytes ingested as `report.docx` and later as
  `report.zip` — a DOCX *is* a zip — leave a row named `report.docx` whose media
  type is `application/zip` and whose text is an archive listing, so `case_cite`
  names a `.docx` for a passage a person opening it in Word will never find. The
  milder everyday shape is `.txt` then `.md`, which route to different
  extractors.
  Neither half can simply switch sides. The name must be stable or a citation
  moves, which is the defect that change exists to close; the text and its media
  type must describe what is stored beside them, which is the rule
  `storage-seam:190-192` states for derived values. So the row is legitimately
  mixed, and the honest fix is disclosure rather than reconciliation: report on
  the reingest that produced it, e.g. a `detail` reading "read as
  application/zip; first observed as report.docx". Parked because it needs its
  own change — `detail` is currently empty for every successful outcome and both
  human surfaces render it — and because it is orthogonal to preserving the
  locations.

- **CLI human output prints location paths raw.** Also from that review, and
  deliberately left alone. The ingest banner and `document show` interpolate a
  path whose second half is chosen by whoever laid out the dump, so a directory
  name containing a newline forges lines in the terminal. It is consistent with
  the surface as it already stands — `found_at` in `_render_document` and every
  `limitations` line are printed raw, and `one_line` is imported nowhere in
  `cli.py` — it never reaches a model, and the `--json` form is JSON-encoded.
  Collapsing only the two new sites would give this one surface two conventions.
  If the CLI is ever hardened, all three sites move together.

- **Two cleanup tests snapshot the machine-wide temp directory, so a second
  jackryan process makes them fail.**
  `test_the_expansion_workspace_is_removed_afterwards` (`jackryan-expand-*`) and
  the retrieval-evaluation workspace test (`jackryan-evaluate-*`) share the
  defect and the fix. Pre-existing; found while gating
  `preserve-duplicate-locations` (2026-09-08) and deliberately not fixed there,
  since that change never touches the workspace lifecycle. The test snapshots
  `tempfile.gettempdir()` — the shared system temp directory — before and after
  its own ingest and fails on any `jackryan-expand-*` that appeared in between.
  Any other jackryan process on the same machine therefore fails it: a second
  test run, a dev instance, or a verification script running alongside.
  Established rather than guessed. Making the swallowed error loud
  (`shutil.rmtree(workspace, ignore_errors=False)` in
  `services/ingestion.py:461`) produced no failure across five full suite runs,
  so the removal itself is reliable and the surviving directory was never this
  ingest's. Running a loop that merely creates and deletes `jackryan-expand-*`
  directories in the shared temp dir alongside the suite reproduces the failure
  on demand, with two leaked paths instead of one.
  Both are green when nothing else runs: 777 passed on `940e0d3` twice in
  succession, and five clean full runs in the instrumented copy. They failed
  only while parallel verification jobs of my own were running, and each such
  job leaves its directories behind for the *next* run to trip over, so a stale
  sweep is part of reproducing a clean result.
  The fix belongs to the test, not the service: have it learn the workspace path
  the ingest actually used — the service takes it from `tempfile.mkdtemp`, which
  a fixture can capture — and assert that one path is gone, rather than that no
  such directory appeared anywhere on the machine.
