# hybrid-search Specification

## MODIFIED Requirements

### Requirement: A result's text is a bounded window around the matched chunk

The text a result carries SHALL be a window that contains the matched chunk and
MAY extend beyond it, so that a passage arrives with the sentences that give it
meaning rather than cut at a chunk boundary.

The window SHALL be taken from the document's extracted text as one contiguous
span. It SHALL NOT be assembled by joining chunk texts: chunks overlap by
configuration, so joining them repeats text.

A chunk's offsets SHALL be treated as selecting its stored text up to
surrounding whitespace, and not exactly. A chunk's offsets now name the trimmed
span, but rows written before that was true name the window the text was trimmed
from, and one store may hold both. Every comparison between a chunk's stored
text and the extracted text at its offsets SHALL therefore trim before
comparing; an exact comparison would treat every earlier row as inconsistent and
withdraw its window.

A window that adds nothing but whitespace to the passage SHALL NOT be reported
as a window. A window identical to the passage is not a window, and neither is
one that differs from it by a blank line: reported as widened, it makes "was
this widened" answer yes for something with nothing in it to read, and names two
spans in provenance that a reader cannot tell apart. This SHALL be decided by
comparing the text rather than the span, because the two are not the same test —
a section's last passage is followed by the paragraph break its own span no
longer covers, so the span differs while the text does not.

The window SHALL be bounded by a character budget, SHALL NOT cross a document
boundary, and SHALL NOT extend past a heading boundary in a document that has
headings. Where a document has no headings — a scan, a plain text file — the
budget alone SHALL bound it.

The matched chunk SHALL remain the unit that is addressed and cited. Widening
what is read SHALL NOT widen what is quoted: identifiers, the passage tool and
the citation tool SHALL continue to resolve the chunk, and a citation's span
SHALL continue to be the chunk's span.

Widening SHALL NOT repeat text another result in the same response already
carries. A window that would reach into another result's span SHALL be pulled
back, and where it cannot be pulled back without cutting into the matched chunk
it SHALL be given up in favour of the chunk alone.

Two matched chunks may still share text with each other, and that is not this
stage's doing: chunks overlap by the width the contract declares, so two adjacent
passages returned as two results carry that overlap however narrow they are made.
What SHALL NOT happen is a widened window carrying a stretch of text another
result already carried, which costs the caller its budget twice and invites one
passage to be counted as two pieces of evidence.

#### Scenario: A result's text extends beyond the matched chunk

- **WHEN** a search matches a chunk in the middle of a section that fits the budget
- **THEN** the returned text contains the chunk's text and extends beyond it, as one contiguous span of the document

#### Scenario: The window does not cross a heading boundary

- **WHEN** a matched chunk sits at the end of a section
- **THEN** the returned text stops at the section boundary rather than running into the next

#### Scenario: The matched chunk is still what is cited

- **WHEN** a citation is requested for a result whose text was widened
- **THEN** the citation names the matched chunk's span, and quotes the chunk

#### Scenario: Widening does not repeat what another result carries

- **WHEN** two results match chunks close enough that widening one would reach into the other
- **THEN** the later result is narrowed, and no text beyond the overlap the contract gives adjacent chunks appears twice in the response

#### Scenario: A widening that adds only whitespace is not a window

- **WHEN** the only room a passage has to grow into is the blank line that follows it
- **THEN** no window is reported, and the result carries the passage alone
