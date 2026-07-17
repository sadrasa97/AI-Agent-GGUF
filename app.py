"""
Nova Code Agent — State-of-the-Art AI Coding IDE (PySide6 / Qt6)

A next-generation desktop IDE with multi-backend AI support, real-time collaboration
features, and a deeply integrated agentic workflow.

Run:
    python app.py
    python app.py --workspace ./my_project
    python app.py --backend openrouter --openrouter-key sk-or-...
    python app.py --backend nvidia --nvidia-key nvapi-...
    python app.py --backend gguf --model /path/to/model.gguf
    python app.py --agent-mode  # Start in agent mode by default

Settings persist in ~/.nova_code_agent/config.json
"""
from __future__ import annotations

import argparse
import json
import sys
import os
from pathlib import Path
from typing import Optional

# Keep terminal output clean from known non-fatal Qt font fallback warnings.
os.environ.setdefault("QT_LOGGING_RULES", "qt.text.font.db=false;qt.qpa.fonts=false")

# --- Pre-import conflict resolution ---
try:
    from six.moves import _thread  # noqa: F401
    import dateutil.tz  # noqa: F401
except Exception:
    pass

from PySide6.QtWidgets import QApplication, QSplashScreen
from PySide6.QtGui import QPalette, QColor, QIcon, QPixmap, QPainter, QFont, QLinearGradient
from PySide6.QtCore import Qt, QTimer, QThread, Signal

from config.settings import Settings, VALID_BACKENDS, CONFIG_DIR
from ui_qt.main_window import MainWindow


RECENT_WORKSPACES_FILE = CONFIG_DIR / "recent_workspaces.json"
PROJECT_MARKERS = (
    ".git", "pyproject.toml", "requirements.txt", "package.json", "Cargo.toml",
    "go.mod", "CMakeLists.txt", "README.md", "readme.md", "setup.py", "setup.cfg",
    "poetry.lock", "Pipfile", "Makefile", "Dockerfile", ".nova", "nova.json",
)
APP_LOGO_FILE = "nova_logo.png"
SPLASH_FILE = "nova_splash.png"
EMPTY_WORKSPACE_DIR = CONFIG_DIR / "__no_project__"


class StartupWorker(QThread):
    """Background worker to initialize heavy resources during splash screen."""
    progress = Signal(int, str)
    finished_loading = Signal()

    def run(self):
        steps = [
            (20, "Loading configuration..."),
            (40, "Initializing AI backends..."),
            (60, "Preparing workspace context..."),
            (80, "Setting up syntax engines..."),
            (100, "Ready"),
        ]
        for pct, msg in steps:
            self.progress.emit(pct, msg)
            self.msleep(180)
        self.finished_loading.emit()


def _load_app_icon() -> Optional[QIcon]:
    logo_path = Path(__file__).resolve().parent / APP_LOGO_FILE
    if not logo_path.exists():
        # Fallback: generate a minimal icon programmatically
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        gradient = QLinearGradient(0, 0, 64, 64)
        gradient.setColorAt(0, QColor(108, 140, 255))
        gradient.setColorAt(1, QColor(80, 200, 180))
        painter.setBrush(gradient)
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(8, 8, 48, 48, 12, 12)
        painter.setPen(QColor(255, 255, 255))
        painter.setFont(QFont("JetBrains Mono", 24, QFont.Bold))
        painter.drawText(pixmap.rect(), Qt.AlignCenter, "N")
        painter.end()
        return QIcon(pixmap)
    icon = QIcon(str(logo_path))
    return icon if not icon.isNull() else None


def _looks_like_project_root(path: Path) -> bool:
    if not path.exists() or not path.is_dir():
        return False
    for marker in PROJECT_MARKERS:
        if (path / marker).exists():
            return True
    return False


def detect_project_root(start: Path) -> Path:
    """Intelligently walk up parents to find the project root."""
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
    return cleaned[:20]


def save_recent_workspaces(items: list[str]) -> None:
    RECENT_WORKSPACES_FILE.parent.mkdir(parents=True, exist_ok=True)
    RECENT_WORKSPACES_FILE.write_text(json.dumps(items[:20], indent=2), encoding="utf-8")


def remember_workspace(path: Path) -> None:
    chosen = str(path.expanduser().resolve())
    existing = load_recent_workspaces()
    deduped = [chosen] + [p for p in existing if p != chosen]
    save_recent_workspaces(deduped)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Nova Code Agent — State-of-the-Art AI Coding IDE",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    %(prog)s                          # Start with no folder opened
  %(prog)s ./my_project            # Open specific folder
  %(prog)s --backend gguf -m model.gguf
  %(prog)s --backend openrouter --openrouter-key sk-or-...
  %(prog)s --agent-mode            # Start in agent mode
        """,
    )
    parser.add_argument("target", nargs="?", default=None, help="Project path (folder or file)")
    parser.add_argument("--workspace", "-w", default=None, help="Workspace directory")
    parser.add_argument("--backend", choices=VALID_BACKENDS, default=None, help="Active generation backend")
    
    # GGUF
    parser.add_argument("--model", "-m", default=None, help="Path to local GGUF model")
    parser.add_argument("--ctx", type=int, default=None, help="Context window size")
    parser.add_argument("--threads", type=int, default=None, help="CPU threads")
    parser.add_argument("--gpu-layers", type=int, default=None, help="GPU layers to offload")
    
    # API Backends
    parser.add_argument("--openrouter-key", default=None, help="OpenRouter API key")
    parser.add_argument("--openrouter-model", default=None, help="OpenRouter model ID")
    parser.add_argument("--nvidia-key", default=None, help="NVIDIA NIM API key")
    parser.add_argument("--nvidia-model", default=None, help="NVIDIA NIM model ID")
    
    # Experience
    parser.add_argument("--temp", type=float, default=None, help="Sampling temperature")
    parser.add_argument("--agent-mode", action="store_true", help="Start in agent mode")
    parser.add_argument("--no-splash", action="store_true", help="Skip splash screen")
    parser.add_argument("--theme", choices=["dark", "light", "system"], default=None, help="UI theme")
    
    return parser.parse_args()


def build_settings(args: argparse.Namespace) -> Settings:
    settings = Settings.load()
    settings.normalize_ui_preferences()

    # Workspace resolution
    explicit_workspace: Optional[Path] = None
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
        settings.workspace = str(EMPTY_WORKSPACE_DIR.resolve())

    # Backend & model settings
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
    if args.theme:
        settings.ui_theme = args.theme
    if args.agent_mode:
        settings.default_chat_mode = "Agent"

    # Auto-detect GGUF model
    if settings.backend == "gguf" and not settings.model_path:
        workspace_candidate = Path(settings.workspace).expanduser().resolve()
        model_dir = workspace_candidate / "models"
        if model_dir.exists() and model_dir.is_dir():
            models = sorted(model_dir.glob("*.gguf"))
            if models:
                settings.model_path = str(models[0].resolve())

    Path(settings.workspace).mkdir(parents=True, exist_ok=True)
    return settings


def apply_dark_palette(app: QApplication):
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(22, 22, 26))
    palette.setColor(QPalette.WindowText, QColor(212, 212, 216))
    palette.setColor(QPalette.Base, QColor(30, 30, 34))
    palette.setColor(QPalette.AlternateBase, QColor(37, 37, 42))
    palette.setColor(QPalette.ToolTipBase, QColor(45, 45, 50))
    palette.setColor(QPalette.ToolTipText, QColor(212, 212, 216))
    palette.setColor(QPalette.Text, QColor(212, 212, 216))
    palette.setColor(QPalette.Button, QColor(52, 52, 58))
    palette.setColor(QPalette.ButtonText, QColor(212, 212, 216))
    palette.setColor(QPalette.BrightText, QColor(255, 80, 80))
    palette.setColor(QPalette.Highlight, QColor(108, 140, 255))
    palette.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
    palette.setColor(QPalette.Link, QColor(108, 140, 255))
    palette.setColor(QPalette.LinkVisited, QColor(180, 140, 255))
    app.setPalette(palette)


def apply_light_palette(app: QApplication):
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(250, 250, 252))
    palette.setColor(QPalette.WindowText, QColor(31, 31, 35))
    palette.setColor(QPalette.Base, QColor(255, 255, 255))
    palette.setColor(QPalette.AlternateBase, QColor(245, 245, 248))
    palette.setColor(QPalette.ToolTipBase, QColor(255, 255, 255))
    palette.setColor(QPalette.ToolTipText, QColor(31, 31, 35))
    palette.setColor(QPalette.Text, QColor(31, 31, 35))
    palette.setColor(QPalette.Button, QColor(240, 240, 244))
    palette.setColor(QPalette.ButtonText, QColor(31, 31, 35))
    palette.setColor(QPalette.BrightText, QColor(200, 40, 40))
    palette.setColor(QPalette.Highlight, QColor(0, 112, 224))
    palette.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
    palette.setColor(QPalette.Link, QColor(0, 112, 224))
    palette.setColor(QPalette.LinkVisited, QColor(120, 80, 200))
    app.setPalette(palette)


def main():
    args = parse_args()

    app = QApplication(sys.argv)
    app.setApplicationName("Nova Code Agent")
    app.setApplicationDisplayName("Nova Code Agent")
    app.setOrganizationName("NovaAI")

    settings = build_settings(args)
    
    # Apply theme
    if settings.ui_theme == "light":
        apply_light_palette(app)
    else:
        apply_dark_palette(app)

    app_icon = _load_app_icon()
    if app_icon is not None:
        app.setWindowIcon(app_icon)

    workspace_path = Path(settings.workspace).expanduser().resolve()
    workspace_path.mkdir(parents=True, exist_ok=True)
    if workspace_path != EMPTY_WORKSPACE_DIR.resolve():
        remember_workspace(workspace_path)

    # Splash screen
    splash = None
    if not args.no_splash:
        splash_pixmap = QPixmap(500, 300)
        splash_pixmap.fill(Qt.transparent)
        painter = QPainter(splash_pixmap)
        gradient = QLinearGradient(0, 0, 500, 300)
        gradient.setColorAt(0, QColor(22, 22, 26))
        gradient.setColorAt(1, QColor(35, 35, 42))
        painter.fillRect(splash_pixmap.rect(), gradient)
        painter.setPen(QColor(108, 140, 255))
        painter.setFont(QFont("JetBrains Mono", 28, QFont.Bold))
        painter.drawText(splash_pixmap.rect().adjusted(0, -40, 0, 0), Qt.AlignCenter, "NOVA")
        painter.setPen(QColor(160, 160, 170))
        painter.setFont(QFont("Inter", 12))
        painter.drawText(splash_pixmap.rect().adjusted(0, 20, 0, 0), Qt.AlignCenter, "AI Coding Agent")
        painter.end()
        splash = QSplashScreen(splash_pixmap, Qt.WindowStaysOnTopHint)
        splash.show()
        app.processEvents()

    # Main window
    window = MainWindow(settings)
    if app_icon is not None:
        window.setWindowIcon(app_icon)

    # Startup sequence
    def finish_startup():
        if splash:
            splash.finish(window)
        window.showMaximized()
        window.raise_()
        window.activateWindow()

    if splash:
        startup = StartupWorker()
        startup.progress.connect(lambda pct, msg: splash.showMessage(
            f"  {msg}", Qt.AlignBottom | Qt.AlignLeft, QColor(160, 160, 170)
        ))
        startup.finished_loading.connect(finish_startup)
        startup.start()
    else:
        window.showMaximized()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()