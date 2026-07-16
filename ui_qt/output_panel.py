"""Bottom integrated terminal panel with selectable shell (PowerShell / CMD)."""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
import sys

from PySide6.QtCore import QProcess, Qt
from PySide6.QtGui import QFont, QTextCursor, QAction
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QToolButton,
    QMenu,
    QPushButton,
    QPlainTextEdit,
    QLineEdit,
)

from config.settings import Settings
from agent.providers import create_provider, ProviderError
from tools.code_tools import build_workspace_context


AI_PREFIX = "/ai "


class TerminalOutputEdit(QPlainTextEdit):
    """A minimal terminal-like text area that accepts direct typing at the end."""

    def __init__(self, submit_callback, parent=None):
        super().__init__(parent)
        self._submit_callback = submit_callback
        self._buffer = ""

    def keyPressEvent(self, event):
        key = event.key()
        text = event.text()

        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.setTextCursor(cursor)

        if key in (Qt.Key_Return, Qt.Key_Enter):
            self.appendPlainText("")
            cmd = self._buffer.strip()
            self._buffer = ""
            if cmd:
                self._submit_callback(cmd)
            return

        if key == Qt.Key_Backspace:
            if self._buffer:
                self._buffer = self._buffer[:-1]
                super().keyPressEvent(event)
            return

        if text and text.isprintable():
            self._buffer += text
            super().keyPressEvent(event)
            return

        # Ignore navigation/editing keys to keep terminal output immutable.
        if key in {
            Qt.Key_Left,
            Qt.Key_Right,
            Qt.Key_Up,
            Qt.Key_Down,
            Qt.Key_Home,
            Qt.Key_End,
            Qt.Key_PageUp,
            Qt.Key_PageDown,
            Qt.Key_Delete,
        }:
            return

        super().keyPressEvent(event)


class OutputPanel(QWidget):
    SHELLS: dict[str, tuple[str, list[str]]] = {
        "PowerShell": ("powershell.exe", ["-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass"]),
        "Command Prompt": ("cmd.exe", ["/Q", "/K"]),
    }

    def __init__(self, workspace_path: Path, settings: Settings, parent=None):
        super().__init__(parent)
        self.workspace_path = Path(workspace_path).resolve()
        self.settings = settings
        self._intentional_restart = False
        self.process = QProcess(self)
        self.process.readyReadStandardOutput.connect(self._on_stdout)
        self.process.readyReadStandardError.connect(self._on_stderr)
        self.process.finished.connect(self._on_finished)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

        self._current_shell = next(iter(self.SHELLS.keys()))

        top = QHBoxLayout()
        top.setSpacing(4)
        top.addWidget(QLabel("TERMINAL"))
        top.addStretch()

        # Compact shell picker: a small toolbutton with a dropdown menu instead of a
        # full-width QComboBox, so the header bar stays thin and more room is left
        # for the terminal itself (and, above it, the chat dock reaching full height).
        self.shell_btn = QToolButton()
        self.shell_btn.setPopupMode(QToolButton.InstantPopup)
        self.shell_btn.setText(self._current_shell)
        self.shell_btn.setToolTip("Choose shell (PowerShell / Command Prompt)")
        self.shell_btn.setStyleSheet(
            "QToolButton { padding: 3px 8px; border-radius: 6px; }"
            "QToolButton::menu-indicator { image: none; }"
        )
        shell_menu = QMenu(self.shell_btn)
        for shell_name in self.SHELLS:
            action = QAction(shell_name, self)
            action.triggered.connect(lambda _checked=False, s=shell_name: self._on_shell_selected(s))
            shell_menu.addAction(action)
        self.shell_btn.setMenu(shell_menu)
        top.addWidget(self.shell_btn)

        self.clear_btn = QToolButton()
        self.clear_btn.setText("Clear")
        self.clear_btn.clicked.connect(lambda: self.output.clear())
        top.addWidget(self.clear_btn)

        self.restart_btn = QToolButton()
        self.restart_btn.setText("⟳")
        self.restart_btn.setToolTip("Restart terminal")
        self.restart_btn.clicked.connect(lambda: self._restart_terminal(self._current_shell))
        top.addWidget(self.restart_btn)
        root.addLayout(top)

        self.output = TerminalOutputEdit(self.execute_command)
        font = QFont("Consolas, Menlo, monospace")
        font.setPointSize(10)
        self.output.setFont(font)
        self.output.setStyleSheet(
            "QPlainTextEdit { background:#1e1e1e; color:#d4d4d4; border:none; padding:6px; }"
        )
        root.addWidget(self.output, stretch=1)

        bottom = QHBoxLayout()
        self.input_line = QLineEdit()
        self.input_line.setPlaceholderText("Type command and press Enter")
        self.input_line.returnPressed.connect(self._send_input_command)
        bottom.addWidget(self.input_line, stretch=1)

        self.run_btn = QPushButton("Run")
        self.run_btn.clicked.connect(self._send_input_command)
        bottom.addWidget(self.run_btn)
        root.addLayout(bottom)

        self._restart_terminal(self._current_shell)

    def _on_shell_selected(self, shell_name: str):
        self._current_shell = shell_name
        self.shell_btn.setText(shell_name)
        self._restart_terminal(shell_name)

    def set_working_directory(self, path: Path):
        self.workspace_path = Path(path).resolve()
        if self.process.state() == QProcess.Running:
            self._send_cd(self.workspace_path)

    def execute_command(self, command: str):
        if not command.strip():
            return
        if command.strip().lower().startswith(AI_PREFIX):
            self._handle_ai_task(command)
            return
        if self.process.state() != QProcess.Running:
            self._restart_terminal(self._current_shell)
        if self.process.state() != QProcess.Running:
            self.output.appendPlainText("[terminal] shell is not running.")
            return
        self.process.write((command + "\n").encode("utf-8"))

    def _handle_ai_task(self, command: str):
        task_prompt = command.strip()[len(AI_PREFIX):].strip()
        if not task_prompt:
            self.output.appendPlainText("[ai] usage: /ai <task description>")
            return

        if self.settings.backend == "gguf" and not self.settings.model_path:
            self.output.appendPlainText("[ai] GGUF model path is empty. Set model in Settings first.")
            return

        self.output.appendPlainText(f"[ai] task: {task_prompt}")
        self.output.appendPlainText("[ai] generating code...")

        wrapped_prompt = (
            "Write a complete Python solution for this task. "
            "Return exactly one runnable Python code block. "
            "Do not include any text outside the code block.\n\n"
            f"Task: {task_prompt}"
        )
        history = [{"role": "user", "content": wrapped_prompt}]
        workspace_context = build_workspace_context(
            self.workspace_path,
            user_text=task_prompt,
            max_files=80,
            max_bytes=6000,
            max_depth=4,
        )

        try:
            provider = create_provider(self.settings)
        except ProviderError as exc:
            self.output.appendPlainText(f"[ai] error: {exc}")
            return

        response = ""
        try:
            for tok in provider.stream(history, workspace_context=workspace_context):
                response += tok
        except ProviderError as exc:
            self.output.appendPlainText(f"[ai] provider error: {exc}")
            provider.close()
            return
        except Exception as exc:  # noqa: BLE001
            self.output.appendPlainText(f"[ai] unexpected error: {exc}")
            provider.close()
            return
        finally:
            provider.close()

        code = self._extract_python_code(response)
        if not code:
            self.output.appendPlainText("[ai] no python code block was generated.")
            if response.strip():
                self.output.appendPlainText("[ai] raw response:")
                self.output.appendPlainText(response.strip())
            return

        path = self._next_task_file()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(code, encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            self.output.appendPlainText(f"[ai] save error: {exc}")
            return

        self.output.appendPlainText(f"[ai] saved: {path}")
        self.output.appendPlainText(f"[ai] running: {path.name}")
        self.execute_file(path)

    @staticmethod
    def _extract_python_code(text: str) -> str:
        pattern = re.compile(r"```(?P<lang>[a-zA-Z0-9+#_-]*)\n(?P<code>.*?)```", re.DOTALL)
        blocks = [(m.group("lang").strip().lower(), m.group("code")) for m in pattern.finditer(text)]
        for lang, code in blocks:
            if lang in {"python", "py"}:
                return code.strip()
        if blocks:
            return blocks[0][1].strip()
        return ""

    def _next_task_file(self) -> Path:
        tasks_dir = self.workspace_path / "tasks"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = tasks_dir / f"task_{timestamp}.py"
        if not base.exists():
            return base
        idx = 1
        while True:
            candidate = tasks_dir / f"task_{timestamp}_{idx}.py"
            if not candidate.exists():
                return candidate
            idx += 1

    def execute_file(self, path: Path) -> bool:
        ext = path.suffix.lower()
        shell = self._current_shell
        p = str(path)
        py = str(Path(sys.executable))

        if ext == ".py":
            cmd = f'& "{py}" "{p}"' if shell == "PowerShell" else f'"{py}" "{p}"'
        elif ext == ".js":
            cmd = f'node "{p}"'
        elif ext == ".ts":
            cmd = f'npx ts-node "{p}"'
        elif ext == ".sh":
            cmd = f'bash "{p}"'
        elif ext == ".rb":
            cmd = f'ruby "{p}"'
        elif ext == ".php":
            cmd = f'php "{p}"'
        elif ext == ".go":
            cmd = f'go run "{p}"'
        elif ext == ".lua":
            cmd = f'lua "{p}"'
        elif ext == ".pl":
            cmd = f'perl "{p}"'
        elif ext == ".r":
            cmd = f'Rscript "{p}"'
        else:
            return False

        self.execute_command(cmd)
        return True

    def _send_input_command(self):
        command = self.input_line.text().strip()
        if not command:
            return
        self.execute_command(command)
        self.input_line.clear()

    def _restart_terminal(self, shell_name: str):
        if self.process.state() != QProcess.NotRunning:
            self._intentional_restart = True
            self.process.kill()
            self.process.waitForFinished(1000)

        program, args = self.SHELLS.get(shell_name, self.SHELLS["PowerShell"])
        self.process.setWorkingDirectory(str(self.workspace_path))
        self.output.appendPlainText(f"\n[terminal] starting {shell_name} in {self.workspace_path}")
        self.process.start(program, args)
        if not self.process.waitForStarted(3000):
            self.output.appendPlainText(f"[terminal] failed to start {shell_name}.")
            return

    def _send_cd(self, path: Path):
        shell_name = self._current_shell
        if shell_name == "Command Prompt":
            cmd = f'cd /d "{path}"'
        else:
            escaped = str(path).replace("'", "''")
            cmd = f"Set-Location -LiteralPath '{escaped}'"
        self.process.write((cmd + "\n").encode("utf-8"))

    def _on_stdout(self):
        data = bytes(self.process.readAllStandardOutput()).decode("utf-8", errors="replace")
        if data:
            self.output.appendPlainText(data.rstrip("\n"))

    def _on_stderr(self):
        data = bytes(self.process.readAllStandardError()).decode("utf-8", errors="replace")
        if data:
            self.output.appendPlainText(data.rstrip("\n"))

    def _on_finished(self, exit_code: int, _status):
        if self._intentional_restart:
            self._intentional_restart = False
            return
        self.output.appendPlainText(f"[terminal exited with code {exit_code}]")

    def shutdown(self):
        if self.process.state() == QProcess.NotRunning:
            return
        self._intentional_restart = True
        self.process.terminate()
        if not self.process.waitForFinished(800):
            self.process.kill()
            self.process.waitForFinished(800)

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)