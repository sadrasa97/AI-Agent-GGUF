"""Global settings dataclass passed through the whole agent.

Extended to support three interchangeable generation backends:
  - "gguf"        : local llama-cpp-python model (offline)
  - "openrouter"  : OpenRouter hosted models (https://openrouter.ai)
  - "nvidia"      : NVIDIA NIM / build.nvidia.com hosted models

Only one backend is "active" at a time (self.backend), but the
credentials/config for all three are kept around so the UI can let the
user flip between them without re-entering keys.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

CONFIG_DIR = Path.home() / ".gguf_code_agent"
CONFIG_FILE = CONFIG_DIR / "config.json"

VALID_BACKENDS = ("gguf", "openrouter", "nvidia")


@dataclass
class Settings:
    # ---- local GGUF backend ----
    model_path: str = ""
    auto_download_default_gguf: bool = True
    default_gguf_url: str = (
        "https://huggingface.co/unsloth/Qwen3.5-2B-GGUF/resolve/main/"
        "Qwen3.5-2B-UD-Q4_K_XL.gguf?download=true"
    )
    default_gguf_filename: str = "Qwen3.5-2B-UD-Q4_K_XL.gguf"
    context_size: int = 4096
    threads: Optional[int] = None
    gpu_layers: int = 0
    verbose: bool = False

    # ---- shared generation params ----
    temperature: float = 0.2
    max_tokens: int = 2048
    top_p: float = 0.95
    repeat_penalty: float = 1.1

    # ---- workspace ----
    workspace: str = "./workspace"

    # ---- active backend selector ----
    backend: str = "gguf"  # one of VALID_BACKENDS

    # ---- OpenRouter ----
    openrouter_api_key: str = ""
    openrouter_model: str = "qwen/qwen-2.5-coder-32b-instruct"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    # ---- NVIDIA NIM ----
    nvidia_api_key: str = ""
    nvidia_model: str = "meta/llama-3.1-70b-instruct"
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"

    @property
    def workspace_path(self) -> Path:
        p = Path(self.workspace).expanduser().resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def model_name(self) -> str:
        if self.backend == "gguf":
            return Path(self.model_path).stem if self.model_path else "(no model)"
        if self.backend == "openrouter":
            return self.openrouter_model
        if self.backend == "nvidia":
            return self.nvidia_model
        return "(unknown)"

    # ------------------------------------------------------------------
    # Persistence — so API keys / last-used model survive UI restarts
    # ------------------------------------------------------------------
    def save(self, path: Path = CONFIG_FILE) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(self)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path = CONFIG_FILE) -> "Settings":
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            valid_keys = {f for f in cls.__dataclass_fields__}
            data = {k: v for k, v in data.items() if k in valid_keys}
            return cls(**data)
        except Exception:
            return cls()

    def validate_backend(self) -> Optional[str]:
        """Return an error string if the active backend is misconfigured, else None."""
        if self.backend == "gguf":
            if not self.model_path or not os.path.isfile(self.model_path):
                return f"GGUF model file not found: {self.model_path}"
        elif self.backend == "openrouter":
            if not self.openrouter_api_key:
                return "OpenRouter API key is not set."
        elif self.backend == "nvidia":
            if not self.nvidia_api_key:
                return "NVIDIA API key is not set."
        else:
            return f"Unknown backend: {self.backend}"
        return None
