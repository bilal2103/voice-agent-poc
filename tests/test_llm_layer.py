"""Covers the LLM layer in isolation: no network, no database."""

import pytest

from app.config import Settings
from app.LLM.base import LLMClient, LLMError, NullLLMClient
from app.LLM.CallSummarizer import CallSummarizer
from app.LLM.factory import build_llm_client
from app.LLM.OpenAIClient import OpenAIClient

TRANSCRIPT = "AI: Welcome to the clinic.\nUser: I'd like to register.\nAI: You're all set, Maria."


class RecordingClient(LLMClient):
    """Captures what the summarizer sends, so the prompt can be asserted."""

    def __init__(self, reply="A summary.", available=True, error=None):
        self.reply = reply
        self._available = available
        self.error = error
        self.calls = []

    @property
    def is_available(self) -> bool:
        return self._available

    async def complete(self, *, system, user, max_output_tokens=400, temperature=0.2):
        self.calls.append(
            {"system": system, "user": user, "max_output_tokens": max_output_tokens}
        )
        if self.error:
            raise self.error
        return self.reply


# --- the contract ---------------------------------------------------------


def test_null_client_reports_unavailable():
    assert NullLLMClient().is_available is False


@pytest.mark.asyncio
async def test_null_client_raises_rather_than_returning_nonsense():
    with pytest.raises(LLMError):
        await NullLLMClient().complete(system="s", user="u")


def test_factory_falls_back_to_null_without_an_api_key():
    client = build_llm_client(Settings(openai_api_key=""))
    assert isinstance(client, NullLLMClient)
    assert client.is_available is False


def test_factory_builds_openai_when_configured():
    client = build_llm_client(Settings(openai_api_key="sk-test", llm_model="gpt-4o-mini"))
    assert isinstance(client, OpenAIClient)
    assert client.is_available is True
    assert client.model == "gpt-4o-mini"


def test_openai_client_without_a_key_is_unavailable():
    assert OpenAIClient(api_key="", model="gpt-4o-mini").is_available is False


# --- the summarizer -------------------------------------------------------


@pytest.mark.asyncio
async def test_summarize_sends_the_transcript_and_returns_the_reply():
    client = RecordingClient(reply="Maria registered as a new patient.")
    summary = await CallSummarizer(client).summarize(TRANSCRIPT)

    assert summary == "Maria registered as a new patient."
    sent = client.calls[0]
    assert TRANSCRIPT in sent["user"]
    assert "summarise phone calls" in sent["system"]


@pytest.mark.asyncio
async def test_summary_prompt_forbids_clinical_inference_and_contact_details():
    client = RecordingClient()
    await CallSummarizer(client).summarize(TRANSCRIPT)

    system = client.calls[0]["system"]
    assert "Never infer a diagnosis" in system
    assert "listing their phone number, email, insurance ID or date of birth is not" in system


@pytest.mark.asyncio
@pytest.mark.parametrize("empty", ["", "   ", "\n"])
async def test_empty_transcripts_are_refused_without_calling_the_model(empty):
    client = RecordingClient()
    with pytest.raises(LLMError):
        await CallSummarizer(client).summarize(empty)
    assert client.calls == []


@pytest.mark.asyncio
async def test_long_transcripts_are_truncated_keeping_the_end():
    """The outcome of a call is at the end, so that is the part worth keeping."""
    client = RecordingClient()
    transcript = "START-MARKER " + ("filler " * 5000) + " END-MARKER"
    await CallSummarizer(client, max_transcript_chars=200).summarize(transcript)

    sent = client.calls[0]["user"]
    assert "END-MARKER" in sent
    assert "START-MARKER" not in sent
    assert "earlier part of the call omitted" in sent


@pytest.mark.asyncio
async def test_provider_errors_propagate_as_llm_error():
    client = RecordingClient(error=LLMError("rate limited"))
    with pytest.raises(LLMError):
        await CallSummarizer(client).summarize(TRANSCRIPT)


def test_summarizer_reports_availability_from_its_client():
    assert CallSummarizer(RecordingClient(available=False)).is_available is False
    assert CallSummarizer(RecordingClient(available=True)).is_available is True
