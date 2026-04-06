"""Thin OpenAI chat client with low temperature and grounded system defaults."""

from __future__ import annotations

import os
from typing import Any, Literal, Sequence

from openai import APIError, APITimeoutError, OpenAI, RateLimitError

DEFAULT_TEMPERATURE = 0.2
DEFAULT_MODEL = "gpt-4o"

DEFAULT_SYSTEM_INSTRUCTIONS = (
    "You are a careful assistant for job applications. "
    "Use only facts supported by the user-provided documents and job description. "
    "If something is unknown or not stated in the materials, say so explicitly. "
    "Do not invent employers, titles, dates, metrics, degrees, or skills."
)

_GENERATION_MODE_STANDARD_SUFFIX = (
    "If minor gaps exist, you may ask one clarification question or proceed conservatively."
)

_GENERATION_MODE_EXECUTIVE_SUFFIX = (
    "You may strategically frame experience and emphasize transferable skills. "
    "Do not fabricate facts, but you may infer positioning based on strong adjacent evidence."
)


class OpenAIClientError(Exception):
    """Raised when the OpenAI API returns an error or an empty response."""


class OpenAIClient:
    """
    Chat completions with strict default temperature and system instructions.

    API key: constructor argument or environment variable ``OPENAI_API_KEY``.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        model: str = DEFAULT_MODEL,
        temperature: float = DEFAULT_TEMPERATURE,
        system_instructions: str = DEFAULT_SYSTEM_INSTRUCTIONS,
        timeout: float = 120.0,
    ) -> None:
        key = api_key or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise OpenAIClientError(
                "Missing API key: pass api_key=... or set OPENAI_API_KEY."
            )
        if not (0.0 <= temperature <= 2.0):
            raise ValueError("temperature must be between 0.0 and 2.0.")

        self._client = OpenAI(api_key=key, timeout=timeout)
        self.model = model
        self.default_temperature = temperature
        self.system_instructions = system_instructions

    def chat(
        self,
        messages: Sequence[dict[str, Any]],
        *,
        system: str | None = None,
        temperature: float | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        """
        Run a chat completion. Inserts a ``system`` message unless ``system=""``.

        ``messages`` should be OpenAI-style role/content dicts (typically user/assistant).
        """
        sys_text = self.system_instructions if system is None else system
        payload: list[dict[str, Any]] = []
        if sys_text is not None and sys_text.strip():
            payload.append({"role": "system", "content": sys_text.strip()})
        payload.extend(list(messages))

        temp = self.default_temperature if temperature is None else temperature
        if not (0.0 <= temp <= 2.0):
            raise ValueError("temperature must be between 0.0 and 2.0.")

        kwargs: dict[str, Any] = {
            "model": model or self.model,
            "messages": payload,
            "temperature": temp,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if response_format is not None:
            kwargs["response_format"] = response_format

        try:
            response = self._client.chat.completions.create(**kwargs)
        except (APIError, APITimeoutError, RateLimitError) as e:
            raise OpenAIClientError(str(e)) from e

        choice = response.choices[0].message
        content = choice.content
        if content is None:
            raise OpenAIClientError("Empty response content from model.")
        return content

    def complete(
        self,
        user_message: str,
        *,
        system: str | None = None,
        mode: Literal["strict", "standard", "executive"] = "standard",
        temperature: float | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        """Single user message → assistant reply."""
        base = self.system_instructions if system is None else system
        if mode == "strict":
            merged_system: str | None = base
        elif mode == "standard":
            merged_system = f"{base}\n\n{_GENERATION_MODE_STANDARD_SUFFIX}"
        else:
            merged_system = f"{base}\n\n{_GENERATION_MODE_EXECUTIVE_SUFFIX}"
        return self.chat(
            [{"role": "user", "content": user_message}],
            system=merged_system,
            temperature=temperature,
            model=model,
            max_tokens=max_tokens,
            response_format=response_format,
        )
