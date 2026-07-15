"""Chat panel (right dock) — talks to whichever provider is active
(GGUF / OpenRouter / NVIDIA) on a background QThread so the UI never
blocks while tokens stream in.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, QThread, Signal, Qt
from PySide6.QtGui import QTextCursor, QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QPlainTextEdit,
    QPushButton, QLabel, QComboBox, QFileDialog,
)

from config.settings import Settings
from agent.providers import create_provider, ProviderError

# Attached files larger than this are truncated when inlined into the prompt.
MAX_ATTACHMENT_CHARS = 20_000


class GenerationWorker(QObject):
    token = Signal(str)
    finished = Signal()
    error = Signal(str)

    def __init__(self, settings: Settings, history: list[dict], workspace_context: Optional[str]):
        super().__init__()
        self.settings = settings
        self.history = history
        self.workspace_context = workspace_context
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            provider = create_provider(self.settings)
        except ProviderError as exc:
            self.error.emit(str(exc))
            self.finished.emit()
            return
        try:
            for tok in provider.stream(self.history, workspace_context=self.workspace_context):
                if self._stop:
                    break
                self.token.emit(tok)
        except ProviderError as exc:
            self.error.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self.error.emit(f"Unexpected error: {exc}")
        finally:
            provider.close()
            self.finished.emit()


class ChatInputBox(QPlainTextEdit):
    submitRequested = Signal()

    def keyPressEvent(self, event):
        key = event.key()
        if key in (Qt.Key_Return, Qt.Key_Enter):
            if event.modifiers() & Qt.ShiftModifier:
                super().keyPressEvent(event)
                return
            event.accept()
            self.submitRequested.emit()
            return
        super().keyPressEvent(event)


class ChatPanel(QWidget):
    """Streaming chat UI + a 'insert into editor' hook."""

    codeBlockReady = Signal(str, str)  # (language, code)

    def __init__(self, settings: Settings, get_workspace_context, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.get_workspace_context = get_workspace_context  # callable() -> str
        self.history: list[dict] = []
        self._thread: Optional[QThread] = None
        self._worker: Optional[GenerationWorker] = None
        self._response_buffer = ""
        self._attachments: list[Path] = []

        self.setStyleSheet("background:#1a1b1e;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        header = QHBoxLayout()
        header.setContentsMargins(10, 8, 10, 4)
        title = QLabel("CHAT")
        title.setStyleSheet("color:#9a9ba1; font-weight:600; font-size:11px; letter-spacing:1.5px;")
        header.addWidget(title)
        header.addStretch()

        self.backend_combo = QComboBox()
        self.backend_combo.addItems(["gguf", "openrouter", "nvidia"])
        self.backend_combo.setCurrentText(self.settings.backend)
        self.backend_combo.currentTextChanged.connect(self._on_backend_changed)
        self.backend_combo.setStyleSheet(
            "QComboBox { background:#2b2d31; color:#ddd; padding:3px 10px; border:1px solid #38393e; "
            "border-radius:10px; } QComboBox::drop-down { border:none; }"
        )
        header.addWidget(self.backend_combo)
        layout.addLayout(header)

        self.transcript = QTextEdit()
        self.transcript.setReadOnly(True)
        self.transcript.setStyleSheet(
            "QTextEdit { background:#1a1b1e; color:#d4d4d4; border:none; padding:10px; }"
        )
        font = QFont("Consolas, Menlo, monospace")
        font.setPointSize(10)
        self.transcript.setFont(font)
        layout.addWidget(self.transcript, stretch=1)

        # ---- attachment chips (shown above the input box, hidden when empty) ----
        self.attachments_row = QHBoxLayout()
        self.attachments_row.setContentsMargins(12, 0, 12, 0)
        self.attachments_row.setSpacing(6)
        self.attachments_row.addStretch()
        attachments_wrap = QWidget()
        attachments_wrap.setLayout(self.attachments_row)
        layout.addWidget(attachments_wrap)

        # ---- composer: rounded "pill" input card, VS-Code-agent style ----
        composer = QWidget()
        composer.setObjectName("composer")
        composer.setStyleSheet(
            "#composer { background:#2b2d31; border:1px solid #38393e; border-radius:14px; }"
        )
        composer_layout = QVBoxLayout(composer)
        composer_layout.setContentsMargins(10, 8, 10, 8)
        composer_layout.setSpacing(6)

        self.input_box = ChatInputBox()
        self.input_box.setFixedHeight(64)
        self.input_box.setPlaceholderText("Ask the model to write/explain/fix code…  (Enter to send, Shift+Enter new line)")
        self.input_box.setStyleSheet(
            "QPlainTextEdit { background:transparent; color:#eee; border:none; padding:2px; }"
        )
        self.input_box.submitRequested.connect(self.send_message)
        composer_layout.addWidget(self.input_box)

        composer_btn_row = QHBoxLayout()
        composer_btn_row.setSpacing(6)

        self.attach_btn = QPushButton("📎 Attach")
        self.attach_btn.setToolTip("Attach a file to share with the model")
        self.attach_btn.clicked.connect(self.attach_file)
        composer_btn_row.addWidget(self.attach_btn)

        self.clear_btn = QPushButton("Clear")
        self.clear_btn.setToolTip("Clear conversation")
        self.clear_btn.clicked.connect(self.clear_history)
        composer_btn_row.addWidget(self.clear_btn)

        composer_btn_row.addStretch()

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(self.stop_generation)
        self.stop_btn.setEnabled(False)
        self.send_btn = QPushButton("Send ➤")
        self.send_btn.clicked.connect(self.send_message)
        composer_btn_row.addWidget(self.stop_btn)
        composer_btn_row.addWidget(self.send_btn)
        composer_layout.addLayout(composer_btn_row)

        self.attach_btn.setStyleSheet(
            "QPushButton { background:#232427; color:#c9c9cc; padding:6px 12px; border:1px solid #38393e; "
            "border-radius:10px; font-size:12px; }"
            "QPushButton:hover { background:#2f3034; }"
        )
        self.clear_btn.setStyleSheet(
            "QPushButton { background:#232427; color:#8a8b90; padding:4px 8px; border:1px solid #38393e; "
            "border-radius:9px; font-size:11px; }"
            "QPushButton:hover { background:#2f3034; color:#c9c9cc; }"
        )
        self.stop_btn.setStyleSheet(
            "QPushButton { background:#2b2d31; color:#c9c9cc; padding:6px 14px; border:1px solid #38393e; "
            "border-radius:10px; }"
            "QPushButton:hover { background:#35363b; }"
            "QPushButton:disabled { background:#232427; color:#5a5a5e; border:1px solid #2c2d31; }"
        )
        self.send_btn.setStyleSheet(
            "QPushButton { background:#6c8cff; color:white; padding:6px 16px; border:none; "
            "border-radius:10px; font-weight:600; }"
            "QPushButton:hover { background:#7d9aff; }"
            "QPushButton:disabled { background:#3c3c3c; color:#888; }"
        )

        outer_composer_row = QHBoxLayout()
        outer_composer_row.setContentsMargins(12, 0, 12, 10)
        outer_composer_row.addWidget(composer)
        layout.addLayout(outer_composer_row)

    # ------------------------------------------------------------------
    def _on_backend_changed(self, text: str):
        self.settings.backend = text
        self.settings.save()

    def clear_history(self):
        self.history.clear()
        self.transcript.clear()

    def _append_transcript(self, html: str):
        self.transcript.moveCursor(QTextCursor.End)
        self.transcript.insertHtml(html)
        self.transcript.moveCursor(QTextCursor.End)

    # ------------------------------------------------------------------
    # File attachments
    # ------------------------------------------------------------------
    def attach_file(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Attach File to Share")
        if not filename:
            return
        path = Path(filename)
        if path not in self._attachments:
            self._attachments.append(path)
        self._render_attachment_chips()

    def _remove_attachment(self, path: Path):
        if path in self._attachments:
            self._attachments.remove(path)
        self._render_attachment_chips()

    def _render_attachment_chips(self):
        # Clear existing chips (keep the trailing stretch)
        while self.attachments_row.count() > 1:
            item = self.attachments_row.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        for path in self._attachments:
            chip = QPushButton(f"📄 {path.name}  ✕")
            chip.setToolTip(str(path))
            chip.setStyleSheet(
                "QPushButton { background:#232427; color:#c9c9cc; padding:3px 10px; "
                "border:1px solid #38393e; border-radius:10px; font-size:11px; }"
                "QPushButton:hover { background:#3a2c2c; color:#f48771; }"
            )
            chip.clicked.connect(lambda _checked=False, p=path: self._remove_attachment(p))
            self.attachments_row.insertWidget(self.attachments_row.count() - 1, chip)

    def _build_attachment_context(self) -> str:
        """Read attached files and format them for inclusion in the outgoing message."""
        if not self._attachments:
            return ""
        blocks = []
        for path in self._attachments:
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except Exception as exc:  # noqa: BLE001
                blocks.append(f"### Attached file: {path.name}\n[Could not read file: {exc}]")
                continue
            if len(content) > MAX_ATTACHMENT_CHARS:
                content = content[:MAX_ATTACHMENT_CHARS] + "\n...[truncated]..."
            blocks.append(f"### Attached file: {path.name}\n```\n{content}\n```")
        return "\n\n".join(blocks) + "\n\n"

    def send_message(self):
        if self._thread is not None:
            return  # generation already in progress
        text = self.input_box.toPlainText().strip()
        attachment_names = [p.name for p in self._attachments]
        if not text and not attachment_names:
            return
        attachment_context = self._build_attachment_context()
        full_message = f"{attachment_context}{text}" if attachment_context else text

        self.input_box.clear()
        self.history.append({"role": "user", "content": full_message})

        display_text = self._escape(text)
        if attachment_names:
            chips_html = " ".join(
                f"<span style='background:#232427;color:#c9c9cc;border-radius:8px;"
                f"padding:1px 8px;margin-right:4px;font-size:11px;'>📄 {self._escape(name)}</span>"
                for name in attachment_names
            )
            display_text = f"{chips_html}<br/>{display_text}" if display_text else chips_html

        self._attachments.clear()
        self._render_attachment_chips()

        self._append_transcript(f"<p><b style='color:#4fc1ff'>You:</b> {display_text}</p>")
        self._append_transcript("<p><b style='color:#b5cea8'>Assistant:</b></p>")
        cursor = self.transcript.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertBlock()
        self.transcript.setTextCursor(cursor)

        self._response_buffer = ""
        workspace_context = self.get_workspace_context() if self.get_workspace_context else None

        self._worker = GenerationWorker(self.settings, list(self.history), workspace_context)
        self._thread = QThread()
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.token.connect(self._on_token)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(self._on_finished)
        self._thread.start()

        self.send_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

    def stop_generation(self):
        if self._worker:
            self._worker.stop()

    def _on_token(self, tok: str):
        self._response_buffer += tok
        cursor = self.transcript.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(tok)
        self.transcript.setTextCursor(cursor)
        self.transcript.ensureCursorVisible()

    def _on_error(self, msg: str):
        self._append_transcript(f"<p style='color:#f48771'><b>Error:</b> {self._escape(msg)}</p>")

    def _on_finished(self):
        if self._response_buffer.strip():
            self.history.append({"role": "assistant", "content": self._response_buffer})
            for lang, code in self._extract_code_blocks(self._response_buffer):
                self.codeBlockReady.emit(lang, code)
        self._append_transcript("<br/><br/>")

        if self._thread:
            self._thread.quit()
            self._thread.wait()
        self._thread = None
        self._worker = None
        self.send_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

    @staticmethod
    def _extract_code_blocks(text: str) -> list[tuple[str, str]]:
        pattern = re.compile(r"```(?P<lang>[a-zA-Z0-9+#_-]*)\n(?P<code>.*?)```", re.DOTALL)
        return [(m.group("lang") or "text", m.group("code")) for m in pattern.finditer(text)]

    @staticmethod
    def _escape(text: str) -> str:
        return (
            text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br/>")
        )