"""Bottom integrated terminal panel with selectable shell (PowerShell / CMD)."""
from __future__ import annotations

from pathlib import Path
import sys

from PySide6.QtCore import QProcess, Qt
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QComboBox,
    QPushButton,
    QPlainTextEdit,
    QLineEdit,
)


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
        "PowerShell": ("powershell.exe", ["-NoLogo", "-NoProfile"]),
        "Command Prompt": ("cmd.exe", ["/Q"]),
    }

    def __init__(self, workspace_path: Path, parent=None):
        super().__init__(parent)
        self.workspace_path = Path(workspace_path).resolve()
        self._intentional_restart = False
        self.process = QProcess(self)
        self.process.readyReadStandardOutput.connect(self._on_stdout)
        self.process.readyReadStandardError.connect(self._on_stderr)
        self.process.finished.connect(self._on_finished)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

        top = QHBoxLayout()
        top.addWidget(QLabel("TERMINAL"))
        top.addStretch()

        self.shell_combo = QComboBox()
        self.shell_combo.addItems(list(self.SHELLS.keys()))
        self.shell_combo.currentTextChanged.connect(self._restart_terminal)
        top.addWidget(self.shell_combo)

        self.clear_btn = QPushButton("Clear")
        self.clear_btn.clicked.connect(lambda: self.output.clear())
        top.addWidget(self.clear_btn)

        self.restart_btn = QPushButton("Restart")
        self.restart_btn.clicked.connect(lambda: self._restart_terminal(self.shell_combo.currentText()))
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

        self._restart_terminal(self.shell_combo.currentText())

    def set_working_directory(self, path: Path):
        self.workspace_path = Path(path).resolve()
        if self.process.state() == QProcess.Running:
            self._send_cd(self.workspace_path)

    def execute_command(self, command: str):
        if not command.strip():
            return
        if self.process.state() != QProcess.Running:
            self._restart_terminal(self.shell_combo.currentText())
        self.process.write((command + "\n").encode("utf-8"))

    def execute_file(self, path: Path) -> bool:
        ext = path.suffix.lower()
        shell = self.shell_combo.currentText()
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

    def _send_cd(self, path: Path):
        shell_name = self.shell_combo.currentText()
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
