"""
Nova Code Agent — VS Code-style desktop IDE (PySide6 / Qt6)

Run:
    python app.py
    python app.py --workspace ./my_project
    python app.py --backend openrouter --openrouter-key sk-or-...
    python app.py --backend nvidia --nvidia-key nvapi-...
    python app.py --backend gguf --model /path/to/model.gguf

Settings (API keys, last-used model, workspace) persist between runs in
~/.gguf_code_agent/config.json — command-line flags override persisted
values for this session and are re-saved on exit.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# --- Pre-import modules that conflict with PySide6's shiboken import hook ---
# PySide6 registers a "feature_imported" hook (shibokensupport) that intercepts
# `six.moves` imports.  When dateutil (via pandas → sklearn → transformers) later
# does `from six.moves import _thread`, the hook crashes because six's
# _SixMetaPathImporter has no `_path` attribute.  This corrupts Python's import
# state and causes subsequent `from transformers.generation import GenerationMixin`
# to fail.  Pre-loading these modules before PySide6 avoids the conflict entirely.
try:
    from six.moves import _thread  # noqa: F401
    import dateutil.tz  # noqa: F401
except Exception:
    pass

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPalette, QColor, QIcon
from PySide6.QtCore import Qt

from config.settings import Settings, VALID_BACKENDS, CONFIG_DIR
from ui_qt.main_window import MainWindow


RECENT_WORKSPACES_FILE = CONFIG_DIR / "recent_workspaces.json"
PROJECT_MARKERS = (
    ".git", "pyproject.toml", "requirements.txt", "package.json", "Cargo.toml",
    "go.mod", "CMakeLists.txt", "README.md", "readme.md",
)
APP_LOGO_FILE = "ChatGPT Image Jul 15, 2026, 11_59_51 AM.png"


def _load_app_icon() -> QIcon | None:
    logo_path = Path(__file__).resolve().parent / APP_LOGO_FILE
    if not logo_path.exists():
        return None

    icon = QIcon(str(logo_path))
    if icon.isNull():
        return None
    return icon


def _looks_like_project_root(path: Path) -> bool:
    if not path.exists() or not path.is_dir():
        return False
    for marker in PROJECT_MARKERS:
        if (path / marker).exists():
            return True
    return False


def detect_project_root(start: Path) -> Path:
    """Walk up parents and return the first directory that looks like a project root."""
    current = start.resolve()
    if current.is_file():
        current = current.parent
    for parent in (current, *current.parents):
        if _looks_like_project_root(parent):
            return parent
    return current


def load_recent_workspaces() -> list[str]:
    if not RECENT_WORKSPACES_FILE.exists():
        return []
    try:
        data = json.loads(RECENT_WORKSPACES_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in data:
        if not isinstance(item, str):
            continue
        p = Path(item).expanduser().resolve()
        key = str(p)
        if not p.exists() or not p.is_dir() or key in seen:
            continue
        seen.add(key)
        cleaned.append(key)
    return cleaned[:15]


def save_recent_workspaces(items: list[str]) -> None:
    RECENT_WORKSPACES_FILE.parent.mkdir(parents=True, exist_ok=True)
    RECENT_WORKSPACES_FILE.write_text(json.dumps(items[:15], indent=2), encoding="utf-8")


def remember_workspace(path: Path) -> None:
    chosen = str(path.expanduser().resolve())
    existing = load_recent_workspaces()
    deduped = [chosen] + [p for p in existing if p != chosen]
    save_recent_workspaces(deduped)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Nova Code Agent — desktop IDE (PySide6/Qt6) with local GGUF, "
                    "OpenRouter, and NVIDIA NIM backend support.",
    )
    parser.add_argument("--workspace", "-w", default=None, help="Workspace directory")
    parser.add_argument("target", nargs="?", default=None,
                        help="Optional project path (folder or file).")
    parser.add_argument("--backend", choices=VALID_BACKENDS, default=None,
                         help="Active generation backend")

    # gguf
    parser.add_argument("--model", "-m", default=None, help="Path to local GGUF model file")
    parser.add_argument("--ctx", type=int, default=None, help="Context window size")
    parser.add_argument("--threads", type=int, default=None, help="CPU threads")
    parser.add_argument("--gpu-layers", type=int, default=None, help="GPU layers to offload")

    # openrouter
    parser.add_argument("--openrouter-key", default=None, help="OpenRouter API key")
    parser.add_argument("--openrouter-model", default=None, help="OpenRouter model id")

    # nvidia
    parser.add_argument("--nvidia-key", default=None, help="NVIDIA NIM API key")
    parser.add_argument("--nvidia-model", default=None, help="NVIDIA NIM model id")

    parser.add_argument("--temp", type=float, default=None, help="Sampling temperature")
    return parser.parse_args()


def build_settings(args: argparse.Namespace) -> Settings:
    settings = Settings.load()
    settings.normalize_ui_preferences()

    explicit_workspace: Path | None = None
    if args.workspace:
        explicit_workspace = Path(args.workspace).expanduser().resolve()
    elif args.target:
        target = Path(args.target).expanduser().resolve()
        if target.exists() and target.is_file():
            explicit_workspace = detect_project_root(target.parent)
        elif target.exists() and target.is_dir():
            explicit_workspace = detect_project_root(target)

    if explicit_workspace:
        settings.workspace = str(explicit_workspace)
    else:
        # If no path was provided, prefer a project-like root from the current folder.
        settings.workspace = str(detect_project_root(Path.cwd()))
    if args.backend:
        settings.backend = args.backend
    if args.model:
        settings.model_path = args.model
    if args.ctx:
        settings.context_size = args.ctx
    if args.threads is not None:
        settings.threads = args.threads
    if args.gpu_layers is not None:
        settings.gpu_layers = args.gpu_layers
    if args.openrouter_key:
        settings.openrouter_api_key = args.openrouter_key
    if args.openrouter_model:
        settings.openrouter_model = args.openrouter_model
    if args.nvidia_key:
        settings.nvidia_api_key = args.nvidia_key
    if args.nvidia_model:
        settings.nvidia_model = args.nvidia_model
    if args.temp is not None:
        settings.temperature = args.temp

    # Auto-pick a local GGUF model if backend is gguf and no explicit path exists.
    if settings.backend == "gguf" and not settings.model_path:
        workspace_candidate = Path(settings.workspace).expanduser().resolve()
        model_dir = workspace_candidate / "workspace" / "models"
        if model_dir.exists() and model_dir.is_dir():
            models = sorted(model_dir.glob("*.gguf"))
            if models:
                settings.model_path = str(models[0].resolve())

    Path(settings.workspace).mkdir(parents=True, exist_ok=True)
    return settings


def apply_dark_palette(app: QApplication):
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(30, 30, 30))
    palette.setColor(QPalette.WindowText, QColor(204, 204, 204))
    palette.setColor(QPalette.Base, QColor(30, 30, 30))
    palette.setColor(QPalette.AlternateBase, QColor(37, 37, 38))
    palette.setColor(QPalette.ToolTipBase, QColor(45, 45, 45))
    palette.setColor(QPalette.ToolTipText, QColor(204, 204, 204))
    palette.setColor(QPalette.Text, QColor(204, 204, 204))
    palette.setColor(QPalette.Button, QColor(60, 60, 60))
    palette.setColor(QPalette.ButtonText, QColor(204, 204, 204))
    palette.setColor(QPalette.BrightText, QColor(255, 0, 0))
    palette.setColor(QPalette.Highlight, QColor(9, 71, 113))
    palette.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
    app.setPalette(palette)


def main():
    args = parse_args()
    settings = build_settings(args)

    app = QApplication(sys.argv)
    app.setApplicationName("Nova Code Agent")
    app_icon = _load_app_icon()
    if app_icon is not None:
        app.setWindowIcon(app_icon)
    apply_dark_palette(app)

    workspace_path = Path(settings.workspace).expanduser().resolve()
    workspace_path.mkdir(parents=True, exist_ok=True)
    remember_workspace(workspace_path)

    window = MainWindow(settings)
    if app_icon is not None:
        window.setWindowIcon(app_icon)
    window.showMaximized()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
