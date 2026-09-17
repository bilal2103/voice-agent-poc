"""OpenAI implementation of the LLM contract."""

import logging

from openai import APIError, AsyncOpenAI, APITimeoutError, RateLimitError

from app.LLM.base import LLMClient, LLMError

logger = logging.getLogger(__name__)


class OpenAIClient(LLMClient):
    def __init__(
        self,
        api_key: str,
        model: str,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.model = model
        self._timeout = timeout_seconds
        self._client = AsyncOpenAI(api_key=api_key, timeout=timeout_seconds) if api_key else None

    @property
    def is_available(self) -> bool:
        return self._client is not None

    async def complete(
        self,
        *,
        system: str,
        user: str,
        max_output_tokens: int = 400,
        temperature: float = 0.2,
    ) -> str:
        if self._client is None:
            raise LLMError("OPENAI_API_KEY is not set")

        try:
            response = await self._client.chat.completions.create(
                model=self.model,
                temperature=temperature,
                max_tokens=max_output_tokens,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
        except APITimeoutError as exc:
            raise LLMError(f"OpenAI timed out after {self._timeout}s") from exc
        except RateLimitError as exc:
            raise LLMError("OpenAI rate limit reached") from exc
        except APIError as exc:
            raise LLMError(f"OpenAI request failed: {exc}") from exc

        choice = response.choices[0] if response.choices else None
        content = (choice.message.content or "").strip() if choice else ""
        if not content:
            raise LLMError("OpenAI returned an empty completion")
        return content
