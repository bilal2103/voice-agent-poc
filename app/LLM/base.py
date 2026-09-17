"""Provider-agnostic contract for the LLM layer.

Everything above this layer depends on `LLMClient`, never on a vendor SDK, so
swapping OpenAI for another provider is one new subclass and a settings change.
"""

from abc import ABC, abstractmethod


class LLMError(Exception):
    """Raised when a completion could not be produced.

    Callers are expected to degrade gracefully rather than fail the request:
    nothing in this application is worth losing a call transcript over.
    """


class LLMClient(ABC):
    @abstractmethod
    async def complete(
        self,
        *,
        system: str,
        user: str,
        max_output_tokens: int = 400,
        temperature: float = 0.2,
    ) -> str:
        """Return the model's reply, or raise LLMError."""

    @property
    @abstractmethod
    def is_available(self) -> bool:
        """False when the client cannot produce completions, e.g. no API key."""


class NullLLMClient(LLMClient):
    """Stands in when no provider is configured.

    Lets the rest of the application run unchanged in development and tests -
    transcripts are still stored, summaries are simply marked as skipped.
    """

    @property
    def is_available(self) -> bool:
        return False

    async def complete(self, **_: object) -> str:
        raise LLMError("No LLM provider is configured")
