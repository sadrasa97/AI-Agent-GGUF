"""
LLM engine: thin wrapper around llama-cpp-python.
Handles model loading, prompt formatting, and streaming generation.
"""
from __future__ import annotations

import os
import sys
from typing import Iterator, Optional

from config.settings import Settings

# Silence llama.cpp noise unless verbose
os.environ.setdefault("LLAMA_LOG_LEVEL", "3")


class LLMEngine:
    """Loads a GGUF model and exposes a streaming completion interface."""

    # Qwen / ChatML style — works for Qwen, DeepSeek, Mistral, etc.
    SYSTEM_PROMPT = (
        "You are an expert software engineer and coding assistant. "
        "When asked to write code, produce ONLY clean, runnable code inside a "
        "single fenced code block with the correct language tag. "
        "After the code block, you may add a short explanation. "
        "Never truncate code. Always write complete, working implementations."
    )

    def __init__(self, settings: Settings):
        self.settings = settings
        self._llm = None
        self._load()

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def _load(self):
        try:
            from llama_cpp import Llama
        except ImportError:
            print(
                "❌  llama-cpp-python is not installed.\n"
                "    Run:  pip install llama-cpp-python\n"
                "    GPU:  pip install llama-cpp-python --extra-index-url "
                "https://abetlen.github.io/llama-cpp-python/whl/cu121",
                file=sys.stderr,
            )
            sys.exit(1)

        model_path = self.settings.model_path
        if not os.path.isfile(model_path):
            print(f"❌  Model file not found: {model_path}", file=sys.stderr)
            sys.exit(1)

        kwargs = dict(
            model_path=model_path,
            n_ctx=self.settings.context_size,
            n_gpu_layers=self.settings.gpu_layers,
            verbose=self.settings.verbose,
        )
        if self.settings.threads is not None:
            kwargs["n_threads"] = self.settings.threads

        print(f"⚙️  Loading model: {self.settings.model_name} …", flush=True)
        self._llm = Llama(**kwargs)
        print("✅  Model loaded.\n")

    # ------------------------------------------------------------------
    # Prompt building  (ChatML / Qwen format)
    # ------------------------------------------------------------------

    def _build_prompt(
        self,
        history: list[dict],
        workspace_context: Optional[str] = None,
    ) -> str:
        """Convert a history list into a ChatML prompt string."""
        parts = [f"<|im_start|>system\n{self.SYSTEM_PROMPT}<|im_end|>"]
        if workspace_context:
            parts.append(f"<|im_start|>system\n{workspace_context}<|im_end|>")
        for msg in history:
            role = msg["role"]   # "user" | "assistant"
            content = msg["content"]
            parts.append(f"<|im_start|>{role}\n{content}<|im_end|>")
        parts.append("<|im_start|>assistant\n")
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Completion
    # ------------------------------------------------------------------

    def complete(
        self,
        history: list[dict],
        workspace_context: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """Non-streaming completion — returns full string."""
        prompt = self._build_prompt(history, workspace_context=workspace_context)
        result = self._llm(
            prompt,
            max_tokens=max_tokens or self.settings.max_tokens,
            temperature=self.settings.temperature,
            top_p=self.settings.top_p,
            repeat_penalty=self.settings.repeat_penalty,
            stop=["<|im_end|>", "<|endoftext|>"],
            echo=False,
        )
        return result["choices"][0]["text"].strip()

    def stream(
        self,
        history: list[dict],
        workspace_context: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ) -> Iterator[str]:
        """Streaming completion — yields token strings one by one."""
        prompt = self._build_prompt(history, workspace_context=workspace_context)
        stream = self._llm(
            prompt,
            max_tokens=max_tokens or self.settings.max_tokens,
            temperature=self.settings.temperature,
            top_p=self.settings.top_p,
            repeat_penalty=self.settings.repeat_penalty,
            stop=["<|im_end|>", "<|endoftext|>"],
            echo=False,
            stream=True,
        )
        for chunk in stream:
            token = chunk["choices"][0]["text"]
            yield token
