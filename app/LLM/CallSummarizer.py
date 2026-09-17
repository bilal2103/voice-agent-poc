"""Turns a call transcript into a short summary.

Owns the prompt and the transcript handling; knows nothing about HTTP, the
database, or which provider is behind `LLMClient`.
"""

import logging

from app.LLM.base import LLMClient, LLMError

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You summarise phone calls to a healthcare clinic's patient intake line.

Write 2 to 4 short sentences covering:
- Why the caller rang, in their terms.
- What was done: a patient registered, details updated, or neither.
- Anything left unresolved, such as a field the caller could not confirm, a request the agent could not handle, or a call that ended early.

Rules:
- Report only what the transcript shows. Never infer a diagnosis, a reason for a visit, or anything clinical.
- Do not repeat the caller's full contact details back. Naming the caller is fine; listing their phone number, email, insurance ID or date of birth is not.
- Write plainly, in the past tense. No bullet points, no headings, no preamble.
- If the transcript is too short or garbled to tell what happened, say exactly that."""


class CallSummarizer:
    def __init__(
        self,
        client: LLMClient,
        max_transcript_chars: int = 24000,
        max_output_tokens: int = 400,
    ) -> None:
        self.client = client
        self.max_transcript_chars = max_transcript_chars
        self.max_output_tokens = max_output_tokens

    @property
    def is_available(self) -> bool:
        return self.client.is_available

    def _prepare(self, transcript: str) -> str:
        """Keeps the tail of a long transcript - the outcome matters most."""
        text = transcript.strip()
        if len(text) <= self.max_transcript_chars:
            return text
        kept = text[-self.max_transcript_chars :]
        logger.info(
            "transcript truncated for summarisation: %d -> %d chars",
            len(text),
            len(kept),
        )
        return f"[earlier part of the call omitted]\n{kept}"

    async def summarize(self, transcript: str) -> str:
        """Returns the summary, or raises LLMError."""
        if not transcript or not transcript.strip():
            raise LLMError("Transcript is empty")

        return await self.client.complete(
            system=SYSTEM_PROMPT,
            user=f"Transcript:\n\n{self._prepare(transcript)}",
            max_output_tokens=self.max_output_tokens,
            temperature=0.2,
        )
