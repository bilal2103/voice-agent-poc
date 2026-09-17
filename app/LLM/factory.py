"""Builds the configured LLM client. The one place a provider is named."""

import logging
from functools import lru_cache

from app.config import Settings, get_settings
from app.LLM.base import LLMClient, NullLLMClient
from app.LLM.CallSummarizer import CallSummarizer
from app.LLM.OpenAIClient import OpenAIClient

logger = logging.getLogger(__name__)


def build_llm_client(settings: Settings) -> LLMClient:
    if not settings.openai_api_key:
        logger.warning(
            "OPENAI_API_KEY is not set; call transcripts will be stored but not summarised"
        )
        return NullLLMClient()
    return OpenAIClient(
        api_key=settings.openai_api_key,
        model=settings.llm_model,
        timeout_seconds=settings.llm_timeout_seconds,
    )


@lru_cache
def get_call_summarizer() -> CallSummarizer:
    """Cached: the underlying SDK client holds a connection pool."""
    settings = get_settings()
    return CallSummarizer(
        client=build_llm_client(settings),
        max_transcript_chars=settings.llm_max_transcript_chars,
        max_output_tokens=settings.llm_max_output_tokens,
    )
