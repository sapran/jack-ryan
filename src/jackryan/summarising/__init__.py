"""Summarising: the port, and the implementation behind it."""

from ..config import Config
from .model import OpenAICompatSummariser
from .port import SummariserPort, SummariserUnavailable, SummaryError

__all__ = [
    "SummariserPort",
    "SummaryError",
    "SummariserUnavailable",
    "OpenAICompatSummariser",
    "build_summariser",
]


def build_summariser(config: Config) -> SummariserPort | None:
    """Construct the summariser the profile names, or nothing.

    Nothing is the default and is not a failure: an instance that names no summary
    model ingests exactly as it did before, with no endpoint to reach and no
    document text leaving the machine. A summary is something a corpus may hold,
    never a condition of holding one.

    Nothing is fetched and no request is made here. An instance that does name a
    model pays for the construction and not for the endpoint, because `check()` is
    where the endpoint is reached.
    """
    name = config.profile.summary_model.strip()
    if not name:
        return None
    base_url = config.profile.llm_url.strip()
    if not base_url:
        # Fatal at build time rather than once per document: a summariser with no
        # endpoint cannot produce anything, and 1,760 identical per-document
        # failures would report the same misconfiguration 1,760 times and fix it
        # none of them.
        raise SummariserUnavailable(
            f"profile sets summary_model={name!r} but leaves llm_url empty. Set "
            f"llm_url to the OpenAI-compatible endpoint that serves {name!r}, or "
            "clear summary_model to ingest without summaries."
        )
    return OpenAICompatSummariser(
        model_name=name,
        base_url=base_url,
        api_key=config.profile.api_key,
        concurrency=config.profile.summary_concurrency,
        timeout_seconds=config.profile.summary_timeout_seconds,
    )
