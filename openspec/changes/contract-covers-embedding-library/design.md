## Context

`Contract.fingerprint()` joins four declared values into a string the store
records at creation and re-checks at every boot. The check is exact and the
refusal is total, which is what makes it useful: it is the one guard standing
between a configuration edit and a corpus whose vectors no longer mean what the
index says they mean.

Two facts shape the design. First, the embedding library is *not* currently a
declared value, yet it determines the vectors as directly as the model name
does — `fastembed` changed `intfloat/multilingual-e5-large` from CLS to mean
pooling between 0.5.1 and 0.8.0. Second, every existing guard downstream checks
width: `ModelEmbedder._embed` raises on a wrong width, and the SQLite store
raises again. A pooling change passes both, because the width is unchanged. The
corpus ends up internally inconsistent with no error anywhere.

The contract loader already has the behaviour this needs: unknown keys, unknown
profiles and unresolved `${VAR}` placeholders are fatal at load with a named
cause. The new validation belongs in that family, not in a new mechanism.

## Goals / Non-Goals

**Goals:**

- The fingerprint changes when the embedding library version changes, so a
  corpus built under one version is refused under another.
- The declared version cannot drift from the installed one without a loud,
  named failure — the declaration must be a fact, not an aspiration.
- The failure appears both at configuration load and at embedder load, so it
  cannot be reached by a path that skips the composition root.
- A rebuild cannot silently move `fastembed` or `docling`.

**Non-Goals:**

- Migrating existing corpora. There is no corpus outside development, and a
  migration path would be more code than reingesting.
- Making pooling strategy independently configurable. See the decision below.
- Putting the extraction library in the fingerprint. See the decision below.
- Detecting a library that changes vectors *without* changing its version
  number. Nothing can detect that, and pretending otherwise would be worse
  than the current gap.

## Decisions

### The version is declared in the contract, not read from the installed package

The obvious alternative is to read the installed distribution version at
fingerprint time — always accurate, nothing to keep in sync. It is rejected for
two reasons.

It makes the fingerprint unreproducible from configuration. Today the contract
is a written statement of the rules a corpus was built under; you can read
`config.yaml` and know the fingerprint. Reading the environment instead means
the same config yields different fingerprints on different machines, and the
one artefact that is supposed to be a stable written record becomes a property
of whatever happens to be installed.

It also makes the guard fire on upgrades that change nothing. A patch release
of `fastembed` that fixes an unrelated bug would change the fingerprint and lock
the operator out of a corpus whose vectors are still perfectly valid, with no
way to say "this bump is safe" short of editing code. Refusing a corpus is the
most expensive action this system takes; it should follow a deliberate written
change, not a `pip install`.

Declaring the version and *verifying* it against the installed package gets
both properties: the fingerprint stays a written fact, and the written fact
cannot be false. The verification is what makes the declaration trustworthy —
without it, this change would move the silent divergence up one level instead
of removing it.

### The check runs at configuration load and again at embedder construction

Config load is where the operator's mistake surfaces earliest and where the
sibling failures already live. But the CLI calls services directly and tests
construct embedders without a full boot, so config load alone is a rule
enforced where it was built rather than where every caller crosses. The
embedder's own load path is the point all vector production goes through, so
the assertion is repeated there.

This is the M1/M2/M3 failure pattern the repository has now hit three times, and
the fix is the one that has worked each time: put the rule on the seam every
path crosses, not only on the convenient one.

### Pooling does not become its own contract field

The handover asked whether pooling belongs in the contract, since pooling is
what actually changed. It does not, for a plain reason: a contract field implies
the operator can set it, and through `fastembed`'s default path they cannot —
selecting pooling requires `add_custom_model`, which the project does not use.
A field that cannot be honoured is a lie in configuration shape.

The library version is the honest proxy. It is the thing the operator can
actually pin, and it determines the pooling they get.

### The extraction library is deliberately excluded

`docling` is corpus-coupled in the same formal sense — its output becomes the
chunks — and the handover flags it as the same class of gap. It is nonetheless
excluded from the fingerprint, because the failure differs in kind.

A `docling` change produces different *text*, and that text is then chunked and
embedded consistently with itself. The corpus becomes heterogeneous — some
documents extracted one way, some another — but every vector still matches the
text it was made from, and the difference is visible on inspection. A pooling
change produces vectors that do not match the vectors beside them while the text
is identical, and nothing can see it.

Putting `docling` in the fingerprint would force a full reingest on every bump
of a fast-moving dependency, in exchange for catching a condition an operator
can already see. It is pinned exactly instead, so the bump is at least a
deliberate act. If per-document extraction provenance is wanted later, that is a
different and better mechanism than corpus-wide refusal.

### Format of the declared value

`embed_library` is a single string of the form `<distribution>==<version>`, for
example `fastembed==0.8.0`. One field rather than two keeps the contract's
"every declared value is consumed" property simple to assert, and the string is
what an operator would type into a requirements file, so it reads as a fact
about the environment rather than an internal encoding.

## Risks / Trade-offs

- **Every existing corpus is refused after this change.** This is intended and
  is the whole point, but it is a breaking change for anyone who built one. The
  mitigation is timing: no corpus outside development is known to exist. Later,
  the same change costs a full reingest.
- **An operator upgrading `fastembed` now hits a fatal error at startup.** That
  is the designed behaviour and it is loud and named, but it converts a silent
  degradation into a visible outage. That trade is correct here — the project's
  own rule is that wrong configuration at startup should be loud and fatal —
  but it means the error text has to say plainly how to proceed: change the
  contract value and reingest, or reinstall the declared version.
- **The declared-versus-installed check reads installed distribution metadata,**
  which is one more thing that can be absent — an editable install or an unusual
  packaging layout could make the version unreadable. Treating "unreadable" as a
  failure is right (it is a configuration the project cannot verify), but it
  must be distinguishable in the message from an outright mismatch.
- **This does not make retrieval quality measurable.** It stops one specific
  silent corruption. The corpus built during the 6/6 verification run is
  mean-pooled and, after this change, will be refused until reingested — which
  is the correct outcome and worth stating in the handover rather than
  discovering later.
