"""The real summariser: an OpenAI-compatible chat-completions endpoint.

`llm_url`, `api_key` and now `summary_model` have been declared profile settings
since M1 with nothing reading them. This is the first code on the runtime path
that sends document text off the instance, which is why it does nothing unless a
model is named and why the endpoint is always one the operator wrote down.

`httpx` is a runtime dependency for this module alone, and for one reason: a
summary per chunk is roughly 36,000 requests for the corpus that exists, and
without a pooled client that is 36,000 TCP and TLS handshakes. One client per
summariser instance, reused for every request, is what that dependency buys.
"""

from __future__ import annotations

import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Sequence
from urllib.parse import urlsplit, urlunsplit

from .port import SummariserUnavailable, SummaryError


def _redacted(url: str) -> str:
    """An endpoint safe to name in an error message.

    Scheme, host, port and path only. Userinfo and query string are dropped,
    because several OpenAI-compatible gateways carry the credential in one of
    them — `https://svc:TOKEN@host/v1`, or `?api-key=...` — and a summariser
    failure becomes an `IngestOutcome.detail`, which the REST ingest route
    returns in its response body with no authentication in front of it.

    A malformed URL is reported as unparseable rather than passed through: this
    function's whole purpose is that its output is safe, so failing closed here
    is the only honest behaviour.
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return "<unparseable llm_url>"
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    return urlunsplit((parts.scheme, host, parts.path, "", ""))


SUMMARY_DOCUMENT_CHARS = 20_000
SUMMARY_MAX_TOKENS = 200
SUMMARY_TEMPERATURE = 0.0

SUMMARY_PROMPT = """<document>
{document}
</document>

Here is the chunk we want to situate within the whole document:
<chunk>
{chunk}
</chunk>

Give a short standalone context that situates this chunk within the document, to improve search
retrieval of the chunk. Answer only with the context and nothing else. Answer in the language of the
chunk."""

DOCUMENT_PROMPT = """Below are ordered notes describing consecutive parts of one document.
Write a single short summary of the document as a whole. Answer only with the summary. Answer in the
language of the notes.

{notes}"""

SUMMARY_ENABLE_THINKING = False
"""Whether the endpoint is asked to let the model think before answering.

False, and sent explicitly rather than left to the endpoint's default. A
reasoning model with thinking on spends its token budget on a trace that is
discarded — `content` arrives empty or cut mid-word while `reasoning_content`
holds the tokens — and this task has no use for one: the request is for a short
standalone context, and measured against a local Qwen3 endpoint the answer is
about twenty-four tokens.

Sent as `chat_template_kwargs`, which llama.cpp, vLLM and SGLang accept. An
endpoint that ignores the key leaves a reasoning model thinking, which surfaces
as an empty context and fails the document loudly rather than folding a
truncated one in. An endpoint that rejects the key fails in `check`, naming the
setting, before any document is read. All three outcomes are safe; only the
first is useful.

Hashed into the recipe below because it changes what the model produces. Left
out, a corpus summarised with thinking on and one summarised with it off would
share an identity while holding vectors built from different text — which is
the failure corpus identity exists to prevent.
"""

# What is hashed is exactly what determines the embedded text: the prompt, how
# much of the document reaches it, the sampling parameters, and whether the model
# is asked to think first. Editing any one of
# them changes `RECIPE_FINGERPRINT`, and therefore corpus identity, with nobody
# having to remember to bump a version — a hand-maintained version number would be
# a second copy of the recipe, and two copies can disagree.
#
# `DOCUMENT_PROMPT` is deliberately outside `_RECIPE`. The per-document summary is
# stored and never embedded, so changing how it is written moves no vector and must
# not refuse a corpus. If a later change ever embeds the document summary anywhere,
# that prompt has to move inside `_RECIPE` in the same change.
_RECIPE = "|".join((
    SUMMARY_PROMPT,
    f"document_chars={SUMMARY_DOCUMENT_CHARS}",
    f"max_tokens={SUMMARY_MAX_TOKENS}",
    f"temperature={SUMMARY_TEMPERATURE}",
    f"enable_thinking={SUMMARY_ENABLE_THINKING}",
))
RECIPE_FINGERPRINT = hashlib.sha256(_RECIPE.encode("utf-8")).hexdigest()[:12]

# What `check` sends. Deliberately not part of the recipe: it produces no stored
# text, so changing it cannot invalidate a corpus.
_PROBE_PROMPT = "ok"


class OpenAICompatSummariser:
    def __init__(
        self,
        model_name: str,
        base_url: str,
        api_key: str = "",
        concurrency: int = 8,
        timeout_seconds: int = 60,
    ) -> None:
        self._model_name = model_name
        # The model alone would not say what the vectors were built from. See the
        # comment on `_RECIPE`: the recipe is in the name because it is in the
        # corpus identity, and it is in the corpus identity because it is in the
        # embedded text.
        self.name = f"{model_name}/{RECIPE_FINGERPRINT}"
        self._base_url = base_url.rstrip("/")
        # Composed once and posted to as an absolute URL rather than leaning on
        # the client's own base-url joining, whose trailing-slash handling is a
        # property of the library version rather than of this file.
        self._completions_url = f"{self._base_url}/chat/completions"
        # What an error message is allowed to name. Some OpenAI-compatible
        # gateways carry the credential in the URL — as userinfo, a path token or
        # a query parameter — and a failure detail travels out through the REST
        # ingest response, which has no authentication in front of it. So the
        # messages name this and never `_completions_url`.
        self._safe_url = _redacted(self._completions_url)
        self._api_key = api_key
        self._concurrency = concurrency
        self._timeout_seconds = timeout_seconds
        # Nothing built and no request made, mirroring the
        # `CrossEncoderReranker.__init__`/`check()` split: `jackryan status` on an
        # instance that names a summariser it will not use pays for neither.
        self._client = None
        # `self._client` is shared mutable state, and REST reaches an ingest
        # through a thread pool over one shared `Context`, so two concurrent
        # ingests can enter `_connect` at once. Without this each would build its
        # own client: one is orphaned unclosed, and `httpx.Limits` is per client,
        # so the connection ceiling the comment below describes would silently
        # double. A `threading` primitive rather than an asyncio one, for the
        # reason `storage-seam` gives for the store's.
        self._lock = threading.Lock()

    def check(self) -> None:
        client = self._connect()
        try:
            # One token is enough. This asks whether the endpoint answers, whether
            # it accepts the credential, whether it knows the model name, and
            # whether it replies in the shape this code parses. It deliberately
            # does not require non-empty content: an endpoint stopped at one token
            # can legitimately return none, and refusing the run for that would
            # fail on a healthy summariser.
            self._content(self._post(client, _PROBE_PROMPT, 1))
        except SummaryError as exc:
            raise SummariserUnavailable(
                f"profile names summary_model={self._model_name!r} at "
                f"llm_url={self._safe_url!r}, which could not be reached: {exc}. "
                "Ingestion is not run with a summariser the instance cannot reach, "
                "because a document embedded without its context inside a folded "
                "corpus is silently incomparable with every other document."
            ) from exc

    def _connect(self):
        """Build the pooled client on first use, or fail naming the setting."""
        with self._lock:
            return self._build_client()

    def _build_client(self):
        if self._client is not None:
            return self._client

        try:
            import httpx
        except Exception as exc:
            raise SummariserUnavailable(
                f"profile names summary_model={self._model_name!r}, but the HTTP client "
                f"could not be imported: {type(exc).__name__}: {exc}"
            ) from exc

        headers = {"Content-Type": "application/json"}
        key = self._api_key.strip()
        if key:
            # Omitted entirely rather than sent empty when no key is configured: a
            # local endpoint rejecting a malformed Authorization header would fail
            # for a reason that has nothing to do with the summariser.
            headers["Authorization"] = f"Bearer {key}"

        # The pool is sized to the workers that will use it. httpx keeps 20
        # connections alive by default, so a profile asking for more concurrency
        # than that would re-handshake on every request past the twentieth — which
        # is the cost this client exists to avoid.
        workers = self._workers()
        self._client = httpx.Client(
            timeout=float(self._timeout_seconds),
            headers=headers,
            limits=httpx.Limits(
                max_connections=workers, max_keepalive_connections=workers
            ),
            # Every one of these three is a default today and is pinned anyway,
            # because this client carries evidence and a bearer token.
            #
            # `trust_env=False` is the one that is not merely defensive. Left
            # true, `HTTPS_PROXY` in the ingesting process's environment routes
            # every summary request — up to 20,000 characters of a document each,
            # plus the credential — through a host that appears nowhere in
            # `config.yaml`. This module's docstring says the endpoint is one the
            # operator wrote down; this is what makes that true.
            trust_env=False,
            # A 3xx would otherwise replay the Authorization header to whatever
            # the Location header names. Off, a redirect is a non-2xx and fails.
            follow_redirects=False,
            verify=True,
        )
        return self._client

    def _workers(self) -> int:
        # The profile validates `summary_concurrency` as positive; the floor is for
        # a direct construction, because `ThreadPoolExecutor`'s own ValueError on a
        # zero names nothing an operator could act on.
        return max(1, self._concurrency)

    def _post(self, client, prompt: str, max_tokens: int):
        body = {
            "model": self._model_name,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": SUMMARY_TEMPERATURE,
            "max_tokens": max_tokens,
            # Part of the hashed recipe. An endpoint that does not know this key
            # ignores it, which leaves a reasoning model thinking and surfaces
            # below as an empty context rather than as a truncated fold.
            "chat_template_kwargs": {"enable_thinking": SUMMARY_ENABLE_THINKING},
        }
        try:
            response = client.post(self._completions_url, json=body)
        except Exception as exc:
            raise SummaryError(
                f"summariser {self.name!r} could not reach {self._safe_url}: "
                f"{type(exc).__name__}: {exc}"
            ) from exc
        if not 200 <= response.status_code < 300:
            # The body is where an OpenAI-compatible endpoint says which of the
            # request it objected to, so a truncated slice of it goes in the
            # message rather than the status code alone.
            raise SummaryError(
                f"summariser {self.name!r} was refused by {self._safe_url}: "
                f"HTTP {response.status_code}: {response.text[:500]!r}"
            )
        try:
            return response.json()
        except Exception as exc:
            raise SummaryError(
                f"summariser {self.name!r} returned a body that is not JSON: "
                f"{type(exc).__name__}: {exc}"
            ) from exc

    def _content(self, payload) -> str:
        """The assistant's text, stripped, or a `SummaryError` naming the shape."""
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            # A body that parses as JSON and is not a completion: an error object,
            # a streamed delta shape, or a proxy's own envelope. Named as malformed
            # rather than allowed to become an empty summary, which with folding on
            # would embed the bare chunk.
            raise SummaryError(
                f"summariser {self.name!r} returned a body with no completion in it: "
                f"{type(exc).__name__}: {exc}"
            ) from exc
        if not isinstance(content, str):
            raise SummaryError(
                f"summariser {self.name!r} returned content of type "
                f"{type(content).__name__} rather than text"
            )
        return content.strip()

    def _empty_context(self, payload, subject: str) -> SummaryError:
        """The error for a completion that parsed but carried no text.

        Built here rather than raised in `_content`, because `check` calls
        `_content` with a one-token budget and an endpoint stopped at one token
        may legitimately return nothing. Only a real summary is required to be
        non-empty, so the requirement lives with the callers that need it.

        Names which of the two causes it is, because the remedy differs and an
        empty string does not distinguish them. The request already asks for
        thinking to be off, so a reasoning trace here means the endpoint ignored
        that key — which is the common case against a local reasoning model and
        the one an operator can act on.
        """
        choice = payload.get("choices", [{}])[0] if isinstance(payload, dict) else {}
        reasoning = (choice.get("message") or {}).get("reasoning_content") or ""
        if reasoning:
            return SummaryError(
                f"summariser {self.name!r} returned no context for {subject}, having "
                f"spent {len(reasoning)} characters of reasoning instead. The request "
                "asks for thinking to be disabled, so this endpoint ignored "
                "`chat_template_kwargs.enable_thinking`. Serve the model with thinking "
                "off, or name a model that does not think."
            )
        return SummaryError(
            f"summariser {self.name!r} returned an empty context for {subject} "
            f"(finish_reason={choice.get('finish_reason')!r}). An empty context is not "
            "a cheap fold: with chunk_summaries on it embeds the bare chunk, putting "
            "one document inside the corpus built from a different kind of input."
        )

    def summarise_chunks(
        self, document_text: str, chunk_texts: Sequence[str]
    ) -> list[str]:
        if not chunk_texts:
            return []
        client = self._connect()
        # Hashed into the recipe, so moving this limit changes corpus identity.
        document = document_text[:SUMMARY_DOCUMENT_CHARS]
        with ThreadPoolExecutor(max_workers=self._workers()) as pool:
            # Submitted in input order and read back in input order. Reassembling by
            # completion order would pair each chunk with whichever summary finished
            # first, and the fold would then embed one chunk's context above another
            # chunk's text: both well-formed, both the declared width, and nothing
            # stored afterwards able to show it.
            #
            # One future per input, read positionally, and a failure raises out of
            # `result()` rather than being dropped — so the returned list is one
            # summary per chunk by construction. That is the port's promise; there is
            # no count to reconcile afterwards because there is no path that can
            # produce a short list.
            futures = [
                pool.submit(self._chunk_summary, client, document, text)
                for text in chunk_texts
            ]
            return [future.result() for future in futures]

    def _chunk_summary(self, client, document: str, chunk: str) -> str:
        payload = self._post(
            client,
            SUMMARY_PROMPT.format(document=document, chunk=chunk),
            SUMMARY_MAX_TOKENS,
        )
        summary = self._content(payload)
        if not summary:
            raise self._empty_context(payload, f"a chunk of {len(chunk)} characters")
        return summary

    def summarise_document(self, chunk_summaries: Sequence[str]) -> str:
        if not chunk_summaries:
            return ""
        client = self._connect()
        payload = self._post(
            client,
            DOCUMENT_PROMPT.format(notes=_numbered_notes(chunk_summaries)),
            SUMMARY_MAX_TOKENS,
        )
        summary = self._content(payload)
        if not summary:
            raise self._empty_context(
                payload, f"a document of {len(chunk_summaries)} notes"
            )
        return summary


def _numbered_notes(
    chunk_summaries: Sequence[str], budget: int = SUMMARY_DOCUMENT_CHARS
) -> str:
    """The notes, numbered and in order, inside a character budget.

    The budget is `SUMMARY_DOCUMENT_CHARS` reused rather than a second constant,
    because both bound the same thing: how much of one document may reach one
    prompt. The reuse is safe in the direction that matters — this prompt is not
    part of the hashed recipe, so the shared constant carries no second meaning
    into corpus identity.

    A bound is needed rather than optional. Every note is model-written prose, so
    a 36,000-chunk document would otherwise build a request body several times
    the size of the document it describes. The resulting summary then describes as
    much of the document as fitted, which is the same trade the per-chunk prompt
    already makes when it truncates the document.
    """
    lines: list[str] = []
    used = 0
    for position, summary in enumerate(chunk_summaries, start=1):
        remaining = budget - used
        if remaining <= 0:
            break
        line = f"{position}. {summary.strip()}"
        if len(line) > remaining:
            # Truncated rather than dropped, so a document whose first note alone
            # exceeds the budget still reaches the endpoint with something to
            # summarise instead of an empty note list.
            lines.append(line[:remaining])
            break
        lines.append(line)
        used += len(line) + 1
    return "\n".join(lines)
