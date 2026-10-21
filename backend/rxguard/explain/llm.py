"""LLM providers for the explainer (NFR-09: free tiers; NFR-10: switchable in config).

Every provider takes a system and a user prompt and returns the model's raw text, which must be
the JSON object described in explainer.SYSTEM_PROMPT. Plain HTTP through httpx, so no vendor SDKs.

  gemini   Google AI Studio free tier      env GEMINI_API_KEY
  groq     Groq free tier (OpenAI-style)   env GROQ_API_KEY
  ollama   local model, no key             env OLLAMA_HOST (default http://localhost:11434)

The "extractive" mode in explainer.py needs no LLM at all and is the automatic fallback.
"""
from __future__ import annotations

import os
from typing import Protocol

import httpx


class LLMError(Exception):
    pass


class LLM(Protocol):
    name: str
    model: str

    def complete(self, system: str, user: str) -> str: ...


class GeminiLLM:
    name = "gemini"
    URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    def __init__(self, model: str, api_key: str, timeout: float = 20):
        self.model, self.api_key, self.timeout = model, api_key, timeout

    def complete(self, system: str, user: str) -> str:
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
        }
        try:
            r = httpx.post(self.URL.format(model=self.model), json=body, timeout=self.timeout,
                           headers={"x-goog-api-key": self.api_key})
            r.raise_for_status()
            return r.json()["candidates"][0]["content"]["parts"][0]["text"]
        except (httpx.HTTPError, KeyError, IndexError) as e:
            raise LLMError(f"gemini: {e}") from e


class OpenAICompatLLM:
    """Groq (and any OpenAI-compatible chat endpoint)."""

    def __init__(self, name: str, base_url: str, model: str, api_key: str, timeout: float = 20):
        self.name, self.base_url, self.model, self.api_key, self.timeout = name, base_url, model, api_key, timeout

    def complete(self, system: str, user: str) -> str:
        body = {"model": self.model, "temperature": 0, "response_format": {"type": "json_object"},
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        try:
            r = httpx.post(f"{self.base_url}/chat/completions", json=body, timeout=self.timeout,
                           headers={"Authorization": f"Bearer {self.api_key}"})
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError) as e:
            raise LLMError(f"{self.name}: {e}") from e


class OllamaLLM:
    name = "ollama"

    def __init__(self, model: str, host: str = "http://localhost:11434", timeout: float = 60):
        self.model, self.host, self.timeout = model, host.rstrip("/"), timeout

    def complete(self, system: str, user: str) -> str:
        body = {"model": self.model, "stream": False, "format": "json", "options": {"temperature": 0},
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        try:
            r = httpx.post(f"{self.host}/api/chat", json=body, timeout=self.timeout)
            r.raise_for_status()
            return r.json()["message"]["content"]
        except (httpx.HTTPError, KeyError) as e:
            raise LLMError(f"ollama: {e}") from e


def make_llm(provider: str, models: dict[str, str], timeout: float = 20) -> LLM | None:
    """Build the configured provider. "auto" picks Gemini, then Groq, by which API key is set.
    Returns None for "extractive" (or "auto" with no key): the explainer then runs without an LLM."""
    provider = provider.lower()
    if provider == "auto":
        provider = "gemini" if os.getenv("GEMINI_API_KEY") else "groq" if os.getenv("GROQ_API_KEY") else "extractive"
    if provider == "extractive":
        return None
    if provider == "gemini":
        key = os.getenv("GEMINI_API_KEY")
        if not key:
            raise LLMError("GEMINI_API_KEY is not set")
        return GeminiLLM(models.get("gemini", "gemini-2.5-flash"), key, timeout)
    if provider == "groq":
        key = os.getenv("GROQ_API_KEY")
        if not key:
            raise LLMError("GROQ_API_KEY is not set")
        return OpenAICompatLLM("groq", "https://api.groq.com/openai/v1",
                               models.get("groq", "llama-3.3-70b-versatile"), key, timeout)
    if provider == "ollama":
        return OllamaLLM(models.get("ollama", "llama3.1:8b"),
                         os.getenv("OLLAMA_HOST", "http://localhost:11434"), max(timeout, 60))
    raise LLMError(f"unknown LLM provider: {provider}")
