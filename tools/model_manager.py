from typing import Dict, Any
import os
import json
from pathlib import Path

from config.settings import settings


class ModelManager:
    """Manages model configuration and loading."""

    def __init__(self):
        self.models = {}

    def load_model(self, model_name: str) -> Dict[str, Any]:
        """Load a specific model from the workspace."""
        if not os.path.exists(model_name):
            raise FileNotFoundError(f"Model '{model_name}' not found in workspace")

        config_path = os.path.join(os.path.dirname(model_name), 'config.json')

        with open(config_path, 'r', encoding='utf-8') as f:
            model_config = json.load(f)

        return {
            **settings.model_config,
            **model_config
        }

    def get_model(self, name: str) -> Dict[str, Any]:
        """Get a specific model configuration."""
        if name not in self.models:
            self.models[name] = self.load_model(name)

        return self.models[name]


# Initialize model manager instance
model_manager = ModelManager()


def ensure_default_gguf_model(settings) -> tuple[str, bool]:
    """
    Make sure a usable GGUF model file exists for the given Settings instance.
    Returns (model_path, downloaded) where downloaded=True only if a new file
    had to be fetched/created during this call.

    Resolution order:
      1. settings.model_path if it already points to an existing file.
      2. First *.gguf file found under <workspace>/workspace/models/.
      3. Otherwise raise FileNotFoundError with actionable instructions
         (auto-download is not implemented yet).
    """
    current = (getattr(settings, "model_path", "") or "").strip()
    if current and Path(current).expanduser().is_file():
        return current, False

    models_dir = Path(settings.workspace) / "workspace" / "models"
    models_dir.mkdir(parents=True, exist_ok=True)

    existing = sorted(models_dir.glob("*.gguf"))
    if existing:
        return str(existing[0].resolve()), False

    raise FileNotFoundError(
        f"No .gguf model found in {models_dir}.\n"
        "Auto-download isn't implemented yet — download a GGUF model manually "
        "and place it in this folder, or set the path directly in Model Settings."
    )