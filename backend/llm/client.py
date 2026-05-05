"""Async OpenAI LLM client with streaming and blocking chat methods."""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncGenerator, Optional

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

    async def chat_call(
        self,
        messages: list[dict],
        *,
        tools: Optional[list[dict]] = None,
        tool_choice: Optional[str] = None,
        temperature: float = 0.4,
        max_tokens: int = 1024,
    ) -> dict:
        """Single non-streaming completion that exposes tool-use details.

        Returns a structured dict so the caller can dispatch tool calls
        without coupling to the OpenAI SDK shape:

            {
              "content": str | None,                  # plain assistant text
              "tool_calls": [
                  {"id": str, "name": str, "arguments_json": str}, ...
              ],
              "finish_reason": str,                   # "stop" | "tool_calls" | ...
            }

        Used by the exam agent endpoint to drive a tool-call loop.
        """
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            kwargs["tools"] = tools
            if tool_choice:
                kwargs["tool_choice"] = tool_choice

        response = await self._client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        msg = choice.message

        out_tool_calls: list[dict] = []
        for tc in (msg.tool_calls or []):
            # ``tc.function.arguments`` is a JSON string. We pass it
            # through verbatim so the caller can ``json.loads`` once,
            # without re-encoding through dict round-trips.
            out_tool_calls.append({
                "id": tc.id,
                "name": tc.function.name if tc.function else None,
                "arguments_json": tc.function.arguments if tc.function else "{}",
            })

        return {
            "content": msg.content or None,
            "tool_calls": out_tool_calls,
            "finish_reason": choice.finish_reason,
        }

    async def chat_json(
        self,
        messages: list[dict],
        *,
        schema: dict[str, Any],
        schema_name: str,
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> dict[str, Any]:
        """Blocking chat call that forces a JSON-Schema-shaped response.

        Uses OpenAI's structured-output mode (``response_format`` with
        ``json_schema``). The model is constrained to emit JSON matching
        ``schema`` exactly, so the caller can ``json.loads`` the result
        without worrying about prose/fences/etc.

        ``temperature`` defaults lower than ``chat()`` because most callers
        of this method want determinism (exam questions, structured
        extraction) rather than creativity. ``max_tokens`` is bumped to
        4096 because exam-question generation can run long.

        Returns the parsed dict. Raises on parse / API error so the
        caller can surface a clean 5xx — *not* a quietly-malformed object.
        """
        response = await self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "schema": schema,
                    "strict": True,
                },
            },
        )
        content = response.choices[0].message.content or ""
        if not content:
            raise RuntimeError("LLM returned empty content for structured request")
        return json.loads(content)
