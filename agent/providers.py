"""
Unified LLM provider layer.

Every provider exposes the same interface:

    provider.stream(history, workspace_context=None, max_tokens=None) -> Iterator[str]
    provider.complete(history, workspace_context=None, max_tokens=None) -> str

`history` is a list of {"role": "user"|"assistant", "content": str} dicts.
This lets the REPL / Qt UI swap backends (local GGUF vs OpenRouter vs
NVIDIA NIM) transparently at runtime.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Iterator, Optional

import requests

from config.settings import Settings

SYSTEM_PROMPT = (
    "You are an expert software engineer and coding assistant embedded in a "
    "VS Code-like desktop IDE. When asked to write code, produce clean, "
    "runnable code inside a single fenced code block with the correct "
    "language tag. After the code block, you may add a short explanation. "
    "Never truncate code. Always write complete, working implementations."
)


class ProviderError(RuntimeError):
    pass


# ──────────────────────────────────────────────────────────────────────
# Base class
# ──────────────────────────────────────────────────────────────────────
class BaseProvider:
    name = "base"

    def __init__(self, settings: Settings):
        self.settings = settings

    def _messages(self, history: list[dict], workspace_context: Optional[str]) -> list[dict]:
        msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
        if workspace_context:
            msgs.append({"role": "system", "content": workspace_context})
        msgs.extend(history)
        return msgs

    def stream(self, history, workspace_context=None, max_tokens=None) -> Iterator[str]:
        raise NotImplementedError

    def complete(self, history, workspace_context=None, max_tokens=None) -> str:
        return "".join(self.stream(history, workspace_context, max_tokens))

    def close(self):
        pass


# ──────────────────────────────────────────────────────────────────────
# Local GGUF backend (llama-cpp-python)
# ──────────────────────────────────────────────────────────────────────
class GGUFProvider(BaseProvider):
    name = "gguf"

    def __init__(self, settings: Settings):
        super().__init__(settings)
        self._llm = None
        self._load()

    def _load(self):
        try:
            from llama_cpp import Llama
        except ImportError as exc:
            msg = str(exc)
            if "_multiarray_umath" in msg or "numpy C-extensions" in msg or "DLL load failed" in msg:
                raise ProviderError(
                    "GGUF backend dependencies are broken in this Python environment.\n"
                    f"Import error: {msg}\n"
                    "Most common cause: corrupted/incompatible NumPy wheel in the active venv.\n"
                    "Repair with:\n"
                    "  python -m pip uninstall -y numpy\n"
                    "  python -m pip install --no-cache-dir --force-reinstall numpy==1.26.4\n"
                    "Then retry sending your message."
                ) from exc
            raise ProviderError(
                "llama-cpp-python is not installed in the active Python environment.\n"
                "Run:  pip install llama-cpp-python\n"
                "GPU:  pip install llama-cpp-python --extra-index-url "
                "https://abetlen.github.io/llama-cpp-python/whl/cu121"
            ) from exc

        model_path = self.settings.model_path
        if not model_path or not os.path.isfile(model_path):
            raise ProviderError(f"Model file not found: {model_path}")

        kwargs = dict(
            model_path=model_path,
            n_ctx=self.settings.context_size,
            n_gpu_layers=self.settings.gpu_layers,
            verbose=self.settings.verbose,
        )
        if self.settings.threads is not None:
            kwargs["n_threads"] = self.settings.threads

        self._llm = Llama(**kwargs)

    def _build_prompt(self, history: list[dict], workspace_context: Optional[str]) -> str:
        parts = [f"<|im_start|>system\n{SYSTEM_PROMPT}<|im_end|>"]
        if workspace_context:
            parts.append(f"<|im_start|>system\n{workspace_context}<|im_end|>")
        for msg in history:
            parts.append(f"<|im_start|>{msg['role']}\n{msg['content']}<|im_end|>")
        parts.append("<|im_start|>assistant\n")
        return "\n".join(parts)

    def stream(self, history, workspace_context=None, max_tokens=None) -> Iterator[str]:
        prompt = self._build_prompt(history, workspace_context)
        out = self._llm(
            prompt,
            max_tokens=max_tokens or self.settings.max_tokens,
            temperature=self.settings.temperature,
            top_p=self.settings.top_p,
            repeat_penalty=self.settings.repeat_penalty,
            stop=["<|im_end|>", "<|endoftext|>"],
            echo=False,
            stream=True,
        )
        for chunk in out:
            yield chunk["choices"][0]["text"]


# ──────────────────────────────────────────────────────────────────────
# Shared OpenAI-compatible HTTP streaming (OpenRouter + NVIDIA NIM both
# implement the OpenAI Chat Completions schema over SSE)
# ──────────────────────────────────────────────────────────────────────
class _OpenAICompatibleProvider(BaseProvider):
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    extra_headers: dict = {}

    def stream(self, history, workspace_context=None, max_tokens=None) -> Iterator[str]:
        if not self.api_key:
            raise ProviderError(f"{self.name}: API key not configured.")

        url = f"{self.base_url.rstrip('/')}/chat/completions"
        payload = {
            "model": self.model,
            "messages": self._messages(history, workspace_context),
            "temperature": self.settings.temperature,
            "top_p": self.settings.top_p,
            "max_tokens": max_tokens or self.settings.max_tokens,
            "stream": True,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        headers.update(self.extra_headers)

        try:
            with requests.post(url, headers=headers, json=payload, stream=True, timeout=120) as resp:
                if resp.status_code != 200:
                    detail = resp.text[:500]
                    raise ProviderError(f"{self.name} API error {resp.status_code}: {detail}")
                for raw_line in resp.iter_lines(decode_unicode=True):
                    if not raw_line:
                        continue
                    line = raw_line.strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[len("data:"):].strip()
                    if data == "[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    choices = obj.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    token = delta.get("content")
                    if token:
                        yield token
        except requests.exceptions.RequestException as exc:
            raise ProviderError(f"{self.name} request failed: {exc}") from exc


class OpenRouterProvider(_OpenAICompatibleProvider):
    name = "openrouter"

    def __init__(self, settings: Settings):
        super().__init__(settings)
        self.base_url = settings.openrouter_base_url
        self.api_key = settings.openrouter_api_key
        self.model = settings.openrouter_model
        # OpenRouter wants these for attribution / rate-limit tiers (optional but recommended)
        self.extra_headers = {
            "HTTP-Referer": "https://github.com/local/gguf-code-agent",
            "X-Title": "GGUF Code Agent",
        }


class NvidiaProvider(_OpenAICompatibleProvider):
    name = "nvidia"

    def __init__(self, settings: Settings):
        super().__init__(settings)
        self.base_url = settings.nvidia_base_url
        self.api_key = settings.nvidia_api_key
        self.model = settings.nvidia_model
        self.extra_headers = {}


# ──────────────────────────────────────────────────────────────────────
# Factory
# ──────────────────────────────────────────────────────────────────────
def create_provider(settings: Settings) -> BaseProvider:
    err = settings.validate_backend()
    if err:
        raise ProviderError(err)

    if settings.backend == "gguf":
        return GGUFProvider(settings)
    if settings.backend == "openrouter":
        return OpenRouterProvider(settings)
    if settings.backend == "nvidia":
        return NvidiaProvider(settings)
    raise ProviderError(f"Unknown backend: {settings.backend}")
