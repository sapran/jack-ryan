## Why

A scanned Ukrainian or Russian document ingests today as punctuation. Not as a
failure — as a stored document, chunked and embedded, that an analyst can list
and will never find.

That is measured, not predicted. An image-only PDF carrying three lines of
Ukrainian and Russian was run through the shipped `DoclingExtractor` and yielded
nine characters: `'.\n\n:    .'`. The same probe against English recovered all
128 characters intact. `FormatRouter.extract` refuses a document only when
`.strip()` leaves nothing, and nine characters of punctuation is not nothing, so
the guard that exists to stop an empty document from looking ingested passes it.

The cause is that OCR is already running and has never been configured.
`DoclingExtractor` constructs a bare `DocumentConverter()`, and in the pinned
`docling==2.122.0` that means `do_ocr=True` with `ocr_options=OcrAutoOptions()`.
Three consequences, each verified against the installed package:

- **The engine depends on the host OS.** `OcrAutoModel` tries `ocrmac` on
  darwin, `nemotron` on linux, then rapidocr, then easyocr. Extracted text
  becomes the corpus, so the corpus depends on which machine ingested it. On
  this machine the log reads `Auto OCR model selected rapidocr with onnxruntime`;
  a machine with `ocrmac` present would silently use Apple Vision instead.
- **Language cannot be configured.** `OcrAutoModel` forwards only `mode` to the
  engine it builds and drops `lang` entirely, so `eng+ukr+rus` is unreachable
  through the path that ships.
- **A missing engine is a silent no-op.** With no engine importable,
  `OcrAutoModel.__call__` logs a warning and yields the pages unchanged. Every
  scan then ingests as an empty document with no error anywhere — the fail-open
  shape this project has already closed twice for the embedder.

This is the second slice of **M3** and pulls nothing forward: OCR, the VLM
escalation path, and the UK/RU extraction spike were all deferred behind the
prototype (`docs/design.md` § 10), and the prototype has shipped.

## What Changes

**Current behaviour.** Extraction is one pass with whatever docling defaults to.
Nothing records how a document's text was obtained, so text read off a noisy
scan is indistinguishable from text lifted from a PDF's text layer. Nothing
refuses a misconfigured OCR engine, because nothing configures one.

**Desired behaviour.** Extraction escalates deliberately through a quality gate,
records which rung produced the text, and refuses at startup to run with an
engine it cannot construct.

- **A three-rung quality gate.** A page-bearing document is read first with OCR
  off — fast, and exactly right for the born-digital majority. When what comes
  back is too thin for the number of pages, the gate escalates to OCR. When OCR
  is also too thin and the VLM rung is enabled, it escalates again. Each rung is
  attempted in order and the first that clears the floor wins.
- **OCR is configured, never inferred.** The engine and its recognition language
  are named in the profile. `auto` is refused: an engine chosen by host OS makes
  corpus content a property of the machine that ingested it.
- **`eslav` is the default recognition model**, which the spike below shows
  reads Ukrainian, Russian and English off one page with a single model.
- **BREAKING for extraction output.** A born-digital PDF is no longer OCR'd on
  the first pass, so its text may differ from what the same file produced
  before. No corpus outside development exists, and the corpus fingerprint does
  not cover the extractor by an existing deliberate decision, so this is not
  guarded by a refusal — it is stated here instead.
- **How a document's text was obtained is recorded and shown.** A document
  carries whether its text came from a text layer, from OCR, or from the VLM,
  and the agent surface reports it, because a quotation read by OCR is weaker
  evidence than one lifted from a text layer and an analyst must be able to tell
  them apart.
- **Images become documents.** PNG, JPEG, TIFF, BMP and WEBP route through the
  same gate. A photographed page is how a large share of real evidence arrives,
  and today no extractor accepts one.
- **The usable-text guard learns what usable means.** A document whose recovered
  text carries no letters or digits in any script is refused rather than stored,
  which is what nine characters of punctuation should have hit.
- **A configured engine that cannot be built is fatal at startup**, naming the
  setting and how to disarm it — not discovered on the first scan, deep inside
  an ingest.

**The UK/RU extraction spike, settled.** `docs/design.md` § 11 leaves the OCR
engine and language choice open until M3. It is decided here on evidence: the
same image-only PDF, three lines of pure Ukrainian, pure Russian and pure Latin,
scored by similarity to the ground truth.

| OCR language | Ukrainian | Russian | English |
|---|---|---|---|
| `auto` — what ships today | 0.11 | 0.11 | 1.00 |
| `eslav` | 0.86 | **0.87** | 1.00 |
| `cyrillic` | **0.88** | 0.74 | 1.00 |

One model covers all three languages, so no per-language routing is needed.
`eslav` is chosen: it wins Russian by a wide margin, where `cyrillic` substituted
Latin homoglyphs, and loses Ukrainian by 0.02. Read it narrowly — one synthetic
fixture, one font, a clean render. It settles which model can read these scripts
at all, and gives a directional quality signal. It is not a benchmark on real
scans, and this change does not claim one.

## Capabilities

### New Capabilities

- `extraction-quality-gate`: how a document that may need OCR is read — the
  escalation ladder and its floor, which rung produced the text, how the engine
  and language are configured, and what happens when they cannot be built.

### Modified Capabilities

- `document-ingestion`: what counts as usable text; that image formats are
  accepted; and that a document records how its text was obtained.
- `layered-configuration`: extraction settings are profile, not contract, and a
  profile naming an engine that cannot be constructed is fatal at load.
- `mcp-tool-surface`: a passage and a citation report how their text was
  obtained, so an agent can weigh OCR'd text accordingly.

## Impact

- `src/jackryan/ingestion/extractors.py` — `DoclingExtractor` gains the ladder;
  a new image extractor entry.
- `src/jackryan/ingestion/` — a new module holding the gate and the engine
  configuration, so the extractor stays a reader.
- `src/jackryan/config.py` — new `Profile` fields; validation at load.
- `src/jackryan/app.py` — the startup refusal, at the composition root beside
  the existing identity guard.
- `src/jackryan/storage/sqlite.py` — one new column on `documents`, with the
  schema step that adds it.
- `src/jackryan/interfaces/mcp/` — the new field on passage and citation shapes.
- `Dockerfile` — OCR weights under the existing model prefetch, so an offline
  image can OCR from its first run.
- **No new dependency.** `rapidocr` and the VLM stack are already installed by
  the pinned `docling==2.122.0`; only model weights are fetched at first use.
- **Corpus fingerprint unchanged**, consistent with the standing decision to keep
  the extractor out of it. Recording the rung per document is what makes that
  decision survivable: a later re-extraction can find exactly which documents
  were OCR'd.
