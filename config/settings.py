"""Global settings dataclass passed through the whole agent."""
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class Settings:
    model_path: str
    context_size: int = 4096
    threads: Optional[int] = None
    gpu_layers: int = 0
    workspace: str = "./workspace"
    temperature: float = 0.2
    verbose: bool = False

    # generation limits
    max_tokens: int = 2048
    top_p: float = 0.95
    repeat_penalty: float = 1.1

    @property
    def workspace_path(self) -> Path:
        p = Path(self.workspace).expanduser().resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def model_name(self) -> str:
        return Path(self.model_path).stem
