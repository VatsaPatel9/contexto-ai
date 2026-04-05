"""Async OpenAI LLM client with streaming and blocking chat methods."""

from __future__ import annotations

import logging
from typing import AsyncGenerator

import openai

logger = logging.getLogger(__name__)


class LLMClient:
    """Thin async wrapper around the OpenAI chat completions API."""

    def __init__(self, api_key: str, model: str = "gpt-4o-mini") -> None:
        self.model = model
        self._client = openai.AsyncOpenAI(api_key=api_key)

    async def chat_stream(
        self, messages: list[dict]
    ) -> AsyncGenerator[str, None]:
        """Stream a chat completion and yield content delta strings.

        Yields individual content chunks as they arrive from the API.
        Handles API errors and timeouts gracefully by logging and
        yielding an error indicator.
        """
        try:
            stream = await self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                stream=True,
                temperature=0.7,
                max_tokens=2048,
            )
            async for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta and delta.content:
                    yield delta.content
        except openai.APITimeoutError:
            logger.error("OpenAI API timeout during streaming")
            yield "\n\n[I'm having trouble connecting right now. Please try again in a moment.]"
        except openai.APIError as exc:
            logger.error("OpenAI API error during streaming: %s", exc)
            yield "\n\n[An error occurred while generating a response. Please try again.]"
        except Exception as exc:
            logger.exception("Unexpected error during LLM streaming: %s", exc)
            yield "\n\n[Something went wrong. Please try again.]"

    async def chat(self, messages: list[dict]) -> str:
        """Run a blocking (non-streaming) chat completion and return the full content string."""
        try:
            response = await self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.7,
                max_tokens=2048,
            )
            return response.choices[0].message.content or ""
        except openai.APITimeoutError:
            logger.error("OpenAI API timeout during chat")
            return "[I'm having trouble connecting right now. Please try again in a moment.]"
        except openai.APIError as exc:
            logger.error("OpenAI API error during chat: %s", exc)
            return "[An error occurred while generating a response. Please try again.]"
        except Exception as exc:
            logger.exception("Unexpected error during LLM chat: %s", exc)
            return "[Something went wrong. Please try again.]"
