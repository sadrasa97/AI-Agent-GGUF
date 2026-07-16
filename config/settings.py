"""
Configuration settings for GGUF Code Agent.
"""
import json
import sys
from pathlib import Path

# Valid backend options
VALID_BACKENDS = ["gguf", "openrouter", "nvidia"]

# Valid UI themes
VALID_UI_THEMES = ["dark", "light"]

# Configuration directory
CONFIG_DIR = Path.home() / ".gguf_code_agent"


class Settings:
    """Application configuration settings."""

    # Default values
    DEFAULT_MODEL = "qwen3.5-2B-UD-Q4_K_XL.gguf"
    OUTPUT_FORMAT = "text"
    UI_THEME = "dark"
    MAX_OUTPUT_LENGTH = 2048

    def __init__(self):
        # Backend settings
        self.backend = "gguf"
        self.model_path = ""
        self.context_size = 4096
        self.threads = None
        self.gpu_layers = -1
        self.temperature = 0.7
        self.top_p = 0.9
        self.repeat_penalty = 1.1
        self.max_tokens = 2048
        self.verbose = False

        # OpenRouter settings
        self.openrouter_api_key = ""
        self.openrouter_model = ""
        self.openrouter_base_url = "https://openrouter.ai/api/v1"

        # NVIDIA settings
        self.nvidia_api_key = ""
        self.nvidia_model = ""
        self.nvidia_base_url = "https://integrate.api.nvidia.com/v1"

        # Workspace
        self.workspace = str(Path.cwd())

        # UI preferences
        self.ui_theme = self.UI_THEME
        self.max_output_length = self.MAX_OUTPUT_LENGTH
        self.show_code_editor = True

        # GGUF auto-download
        self.auto_download_default_gguf = False

        # Voice / ASR settings
        self.asr_backend = "local"                 # "local" | "api"
        self.qwen_voice_model_path = ""             # local dir for Qwen3-ASR
        self.asr_model_path = ""                    # fallback (e.g. whisper) model id/path
        self.asr_language = "Auto"
        self.asr_sample_rate = 16000
        self.asr_api_url = ""
        self.asr_api_key = ""

        # Model config (legacy)
        self.model_config = {
            'model': self.DEFAULT_MODEL,
            'output_format': self.OUTPUT_FORMAT,
            'ui_theme': self.UI_THEME,
            'max_output_length': self.MAX_OUTPUT_LENGTH
        }

    # ------------------------------------------------------------------
    # Derived / convenience properties
    # ------------------------------------------------------------------

    @property
    def workspace_path(self) -> Path:
        """Workspace directory as a Path object (used throughout the UI/agent code)."""
        return Path(self.workspace).expanduser()

    @property
    def model_name(self) -> str:
        """Human-friendly label for whichever backend/model is currently active."""
        if self.backend == "gguf":
            if self.model_path:
                return Path(self.model_path).name
            return self.DEFAULT_MODEL
        if self.backend == "openrouter":
            return self.openrouter_model or "openrouter (no model set)"
        if self.backend == "nvidia":
            return self.nvidia_model or "nvidia (no model set)"
        return "unknown"

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate_backend(self) -> str | None:
        """Return an error string if the current backend is misconfigured, else None."""
        if self.backend not in VALID_BACKENDS:
            return f"Unknown backend: {self.backend}"

        if self.backend == "gguf":
            if not self.model_path:
                return "No GGUF model path is set. Choose a model in Model Settings."
            if not Path(self.model_path).expanduser().is_file():
                return f"GGUF model file not found: {self.model_path}"

        elif self.backend == "openrouter":
            if not self.openrouter_api_key:
                return "OpenRouter API key is not set."
            if not self.openrouter_model:
                return "OpenRouter model is not set."

        elif self.backend == "nvidia":
            if not self.nvidia_api_key:
                return "NVIDIA NIM API key is not set."
            if not self.nvidia_model:
                return "NVIDIA NIM model is not set."

        return None

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    @classmethod
    def load(cls) -> "Settings":
        """Load settings from config file."""
        settings = cls()
        config_file = CONFIG_DIR / "config.json"

        if config_file.exists():
            try:
                data = json.loads(config_file.read_text(encoding="utf-8"))
                for key, value in data.items():
                    if hasattr(settings, key):
                        setattr(settings, key, value)
            except Exception:
                pass

        return settings

    def save(self) -> None:
        """Save settings to config file."""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        config_file = CONFIG_DIR / "config.json"

        # Convert settings to dict, excluding methods, properties, and private attributes.
        # Properties (workspace_path, model_name) are intentionally excluded since they're
        # derived, not stored, and validate_backend()/save() are methods, not data.
        skip = {"workspace_path", "model_name"}
        data = {}
        cls_ = type(self)
        for key in dir(self):
            if key.startswith('_') or key in skip:
                continue
            # Skip properties/methods defined on the class (only persist instance data)
            class_attr = getattr(cls_, key, None)
            if isinstance(class_attr, property):
                continue
            value = getattr(self, key)
            if callable(value):
                continue
            # Only save serializable types
            if isinstance(value, (str, int, float, bool, type(None))):
                data[key] = value

        config_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def normalize_ui_preferences(self) -> None:
        """Ensure UI preferences are valid."""
        if self.ui_theme not in VALID_UI_THEMES:
            self.ui_theme = "dark"


# Initialize settings instance
settings = Settings()