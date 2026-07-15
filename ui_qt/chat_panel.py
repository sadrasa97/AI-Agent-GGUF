"""Chat panel (right dock) — talks to whichever provider is active
(GGUF / OpenRouter / NVIDIA) on a background QThread so the UI never
blocks while tokens stream in.

Layout mirrors GitHub Copilot Chat:
  - the whole panel sits inside ONE bordered outer "chat box"
  - inside it, every turn is its OWN separate card: a distinct box for
    the user's question and a distinct box for the assistant's answer,
    each with a small role avatar + name header, stacked top-to-bottom
    in a scroll area.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, QThread, Signal, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPlainTextEdit,
    QPushButton, QComboBox, QFileDialog, QFrame, QScrollArea,
    QSizePolicy,
)

from config.settings import Settings
from agent.providers import create_provider, ProviderError
from tools.code_tools import list_workspace_files, read_text_file

# Attached files larger than this are truncated when inlined into the prompt.
MAX_ATTACHMENT_CHARS = 20_000
MAX_TOOL_OUTPUT_CHARS = 12_000
MAX_REGEX_MATCHES = 120


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


class ChatBubble(QFrame):
    """A single self-contained message card — either the user's question
    or the assistant's answer — styled like a GitHub Copilot Chat turn:
    round avatar + role name header, content below, own background/border.
    Uses a word-wrapping QLabel for content so height always tracks the
    text correctly (no manual height math needed).
    """

    ROLE_STYLES = {
        "user": {
            "bg": "#20293a",
            "border": "#2e4a73",
            "label": "You",
            "label_color": "#6fb3ff",
            "avatar_bg": "#2e4a73",
            "avatar": "🧑",
        },
        "assistant": {
            "bg": "#1f2620",
            "border": "#33472f",
            "label": "Assistant",
            "label_color": "#9bd39c",
            "avatar_bg": "#33472f",
            "avatar": "✨",
        },
        "error": {
            "bg": "#2e1f20",
            "border": "#5a2c2c",
            "label": "Error",
            "label_color": "#f48771",
            "avatar_bg": "#5a2c2c",
            "avatar": "⚠",
        },
        "system": {
            "bg": "#22242a",
            "border": "#33353c",
            "label": "Agent",
            "label_color": "#c9a6ff",
            "avatar_bg": "#3a2f5c",
            "avatar": "🛠",
        },
    }

    def __init__(self, role: str, parent=None):
        super().__init__(parent)
        self.role = role
        self._raw_html = ""
        style = self.ROLE_STYLES.get(role, self.ROLE_STYLES["assistant"])

        self.setObjectName("bubble")
        self.setStyleSheet(
            f"#bubble {{ background:{style['bg']}; border:1px solid {style['border']}; "
            f"border-radius:12px; }}"
        )
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 12)
        outer.setSpacing(6)

        header = QHBoxLayout()
        header.setSpacing(8)

        avatar = QLabel(style["avatar"])
        avatar.setFixedSize(22, 22)
        avatar.setAlignment(Qt.AlignCenter)
        avatar.setStyleSheet(
            f"background:{style['avatar_bg']}; border-radius:11px; font-size:12px; border:none;"
        )
        header.addWidget(avatar)

        role_label = QLabel(style["label"])
        role_label.setStyleSheet(
            f"color:{style['label_color']}; font-weight:700; font-size:12px; "
            f"letter-spacing:0.3px; background:transparent; border:none;"
        )
        header.addWidget(role_label)
        header.addStretch()

        self.tag_label = QLabel("")
        self.tag_label.setStyleSheet(
            "color:#e0af68; background:#3a2f13; border-radius:8px; padding:1px 8px; "
            "font-size:10px; font-weight:600; border:none;"
        )
        self.tag_label.setVisible(False)
        header.addWidget(self.tag_label)
        outer.addLayout(header)

        self.content = QLabel("")
        self.content.setWordWrap(True)
        self.content.setTextFormat(Qt.RichText)
        self.content.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse)
        self.content.setOpenExternalLinks(True)
        self.content.setStyleSheet(
            "QLabel { background:transparent; color:#e2e2e5; border:none; }"
        )
        content_font = QFont("Consolas, Menlo, monospace")
        content_font.setPointSize(10)
        self.content.setFont(content_font)
        outer.addWidget(self.content)

    def set_tag(self, text: str):
        if text:
            self.tag_label.setText(text)
            self.tag_label.setVisible(True)
        else:
            self.tag_label.setVisible(False)

    def set_html(self, html: str):
        self._raw_html = html
        self.content.setText(html if html else "&nbsp;")

    def append_plain(self, text: str):
        escaped = (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("\n", "<br/>")
        )
        self._raw_html += escaped
        self.content.setText(self._raw_html)

    def clear_content(self):
        self._raw_html = ""
        self.content.setText("")


class ChatPanel(QWidget):
    """Streaming chat UI + a 'insert into editor' hook."""

    codeBlockReady = Signal(str, str)  # (language, code) — generic snippet, not tied to a file
    agentFileEdit = Signal(str, str, str)  # (relative_path, language, code) — Agent mode auto-apply

    def __init__(self, settings: Settings, get_workspace_context, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.get_workspace_context = get_workspace_context  # callable() -> str
        self.history: list[dict] = []
        self._thread: Optional[QThread] = None
        self._worker: Optional[GenerationWorker] = None
        self._response_buffer = ""
        self._attachments: list[Path] = []
        self.mode = "Agent"  # "Chat", "Agent", or "Plan" — Agent is the default
        self._current_assistant_bubble: Optional[ChatBubble] = None

        self.setStyleSheet("background:#1a1b1e;")

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(10, 10, 10, 10)
        outer_layout.setSpacing(0)

        # ---- the whole chat lives inside ONE bordered outer box ----
        chat_box = QFrame()
        chat_box.setObjectName("chatBox")
        chat_box.setStyleSheet(
            "#chatBox { background:#1e1f22; border:1px solid #2c2d31; border-radius:14px; }"
        )
        outer_layout.addWidget(chat_box)

        layout = QVBoxLayout(chat_box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        header = QHBoxLayout()
        header.setContentsMargins(14, 10, 12, 4)
        title = QLabel("CHAT")
        title.setStyleSheet("color:#9a9ba1; font-weight:600; font-size:11px; letter-spacing:1.5px;")
        header.addWidget(title)
        header.addStretch()
        layout.addLayout(header)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("background:#2c2d31; max-height:1px; border:none;")
        layout.addWidget(sep)

        # ---- scrollable message list — each turn its own card ----
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("QScrollArea { background:transparent; border:none; }")

        self.messages_container = QWidget()
        self.messages_container.setStyleSheet("background:transparent;")
        self.messages_layout = QVBoxLayout(self.messages_container)
        self.messages_layout.setContentsMargins(12, 8, 12, 8)
        self.messages_layout.setSpacing(10)
        self.messages_layout.addStretch(1)

        self.scroll.setWidget(self.messages_container)
        layout.addWidget(self.scroll, stretch=1)

        # ---- attachment chips (shown above the input box, hidden when empty) ----
        self.attachments_row = QHBoxLayout()
        self.attachments_row.setContentsMargins(12, 0, 12, 0)
        self.attachments_row.setSpacing(6)
        self.attachments_row.addStretch()
        attachments_wrap = QWidget()
        attachments_wrap.setStyleSheet("background:transparent;")
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
        self.input_box.setToolTip(
            "Optional tool directives in your message:\n"
            "  /regex <pattern>  -> search workspace with Python regex\n"
            "  /ps <command>     -> run PowerShell command in workspace"
        )
        self.input_box.setStyleSheet(
            "QPlainTextEdit { background:transparent; color:#eee; border:none; padding:2px; }"
        )
        self.input_box.submitRequested.connect(self.send_message)
        composer_layout.addWidget(self.input_box)

        composer_btn_row = QHBoxLayout()
        composer_btn_row.setSpacing(5)

        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["Agent", "Chat", "Plan"])
        self.mode_combo.setCurrentText(self.mode)
        self.mode_combo.setToolTip(
            "Agent: model edits existing files and creates new files/folders directly, like Copilot Agent mode.\n"
            "Chat: normal coding assistant, you choose how to apply code.\n"
            "Plan: model first drafts a step-by-step plan before writing any code."
        )
        self.mode_combo.currentTextChanged.connect(self._on_mode_changed)
        composer_btn_row.addWidget(self.mode_combo)

        self.backend_combo = QComboBox()
        self.backend_combo.addItems(["gguf", "openrouter", "nvidia"])
        self.backend_combo.setCurrentText(self.settings.backend)
        self.backend_combo.currentTextChanged.connect(self._on_backend_changed)
        composer_btn_row.addWidget(self.backend_combo)

        self.attach_btn = QPushButton("📎")
        self.attach_btn.setToolTip("Attach a file to share with the model")
        self.attach_btn.clicked.connect(self.attach_file)
        composer_btn_row.addWidget(self.attach_btn)

        self.clear_btn = QPushButton("🗑")
        self.clear_btn.setToolTip("Clear conversation")
        self.clear_btn.clicked.connect(self.clear_history)
        composer_btn_row.addWidget(self.clear_btn)

        composer_btn_row.addStretch()

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setToolTip("Stop generation")
        self.stop_btn.clicked.connect(self.stop_generation)
        self.stop_btn.setEnabled(False)
        composer_btn_row.addWidget(self.stop_btn)

        self.send_btn = QPushButton("➤")
        self.send_btn.setToolTip("Send (Enter)")
        self.send_btn.clicked.connect(self.send_message)
        composer_btn_row.addWidget(self.send_btn)
        composer_layout.addLayout(composer_btn_row)

        # ---- small, pill-shaped, understated buttons/pickers ----
        combo_style = (
            "QComboBox { background:#232427; color:#c9c9cc; padding:3px 8px; border:1px solid #38393e; "
            "border-radius:9px; font-size:10.5px; font-weight:600; min-height:18px; }"
            "QComboBox:hover { background:#2a2b30; border:1px solid #47484d; }"
            "QComboBox::drop-down { border:none; width:14px; }"
            "QComboBox QAbstractItemView { background:#232427; color:#ddd; selection-background-color:#3a3b40; "
            "border:1px solid #38393e; outline:none; }"
        )
        self.mode_combo.setStyleSheet(combo_style)
        self.backend_combo.setStyleSheet(combo_style)

        icon_btn_style = (
            "QPushButton { background:#232427; color:#c9c9cc; padding:4px 7px; border:1px solid #38393e; "
            "border-radius:9px; font-size:11px; min-width:14px; }"
            "QPushButton:hover { background:#2f3034; border:1px solid #47484d; }"
            "QPushButton:pressed { background:#1e1f22; }"
        )
        self.attach_btn.setStyleSheet(icon_btn_style)
        self.clear_btn.setStyleSheet(
            icon_btn_style.replace("color:#c9c9cc", "color:#8a8b90").replace(
                "QPushButton:hover { background:#2f3034;", "QPushButton:hover { background:#3a2c2c; color:#f48771;"
            )
        )
        self.stop_btn.setStyleSheet(
            "QPushButton { background:#232427; color:#c9c9cc; padding:4px 12px; border:1px solid #38393e; "
            "border-radius:9px; font-size:11px; font-weight:600; }"
            "QPushButton:hover { background:#3a2c2c; color:#f48771; border:1px solid #5a3535; }"
            "QPushButton:disabled { background:#1e1f22; color:#4a4a4e; border:1px solid #262729; }"
        )
        self.send_btn.setStyleSheet(
            "QPushButton { background:#6c8cff; color:white; padding:4px 12px; border:none; "
            "border-radius:9px; font-weight:700; font-size:12px; min-width:22px; }"
            "QPushButton:hover { background:#7d9aff; }"
            "QPushButton:pressed { background:#5b78e0; }"
            "QPushButton:disabled { background:#33343a; color:#6a6a6e; }"
        )

        outer_composer_row = QHBoxLayout()
        outer_composer_row.setContentsMargins(12, 0, 12, 10)
        outer_composer_row.addWidget(composer)
        layout.addLayout(outer_composer_row)

    # ------------------------------------------------------------------
    def _on_backend_changed(self, text: str):
        self.settings.backend = text
        self.settings.save()

    def _on_mode_changed(self, text: str):
        self.mode = text
        if text == "Plan":
            placeholder = "Describe what you want built — I'll draft a plan first…  (Enter to send, Shift+Enter new line)"
        elif text == "Agent":
            placeholder = "Describe what to build or fix — the agent will edit/create files directly…  (Enter to send, Shift+Enter new line)"
        else:
            placeholder = "Ask the model to write/explain/fix code…  (Enter to send, Shift+Enter new line)"
        self.input_box.setPlaceholderText(placeholder)

    def clear_history(self):
        self.history.clear()
        while self.messages_layout.count() > 1:  # keep trailing stretch
            item = self.messages_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._current_assistant_bubble = None

    # ------------------------------------------------------------------
    # Bubble management
    # ------------------------------------------------------------------
    def _add_bubble(self, role: str) -> ChatBubble:
        bubble = ChatBubble(role)
        # insert before the trailing stretch item so new cards stack downward
        self.messages_layout.insertWidget(self.messages_layout.count() - 1, bubble)
        return bubble

    def _scroll_to_bottom(self):
        bar = self.scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

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

    @staticmethod
    def _truncate_text(text: str, max_chars: int = MAX_TOOL_OUTPUT_CHARS) -> str:
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + "\n...[truncated]..."

    @staticmethod
    def _parse_tool_directives(user_text: str) -> tuple[str, list[str], list[str]]:
        cleaned_lines: list[str] = []
        regex_queries: list[str] = []
        ps_commands: list[str] = []
        for line in user_text.splitlines():
            stripped = line.strip()
            lowered = stripped.lower()
            if lowered.startswith("/regex "):
                query = stripped[7:].strip()
                if query:
                    regex_queries.append(query)
                continue
            if lowered.startswith("/ps "):
                cmd = stripped[4:].strip()
                if cmd:
                    ps_commands.append(cmd)
                continue
            cleaned_lines.append(line)
        return "\n".join(cleaned_lines).strip(), regex_queries, ps_commands

    def _run_workspace_regex(self, pattern: str) -> str:
        try:
            regex = re.compile(pattern)
        except re.error as exc:
            return f"Pattern compile error: {exc}"

        workspace = self.settings.workspace_path
        matches: list[str] = []
        files = list_workspace_files(workspace, max_depth=10, max_files=4000)
        for path in files:
            try:
                content = read_text_file(path, max_bytes=500_000)
            except Exception:
                continue
            for line_no, line in enumerate(content.splitlines(), start=1):
                if not regex.search(line):
                    continue
                rel = path.relative_to(workspace).as_posix()
                snippet = line.strip()
                matches.append(f"{rel}:{line_no}: {snippet}")
                if len(matches) >= MAX_REGEX_MATCHES:
                    return "\n".join(matches) + "\n... (match limit reached)"
        if not matches:
            return "No matches found."
        return "\n".join(matches)

    def _run_powershell(self, command: str) -> str:
        try:
            proc = subprocess.run(
                [
                    "powershell.exe",
                    "-NoLogo",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-Command",
                    command,
                ],
                cwd=str(self.settings.workspace_path),
                capture_output=True,
                text=True,
                timeout=30,
            )
        except Exception as exc:  # noqa: BLE001
            return f"PowerShell execution failed: {exc}"

        stdout = proc.stdout.strip()
        stderr = proc.stderr.strip()
        parts = [f"ExitCode: {proc.returncode}"]
        if stdout:
            parts.append("STDOUT:\n" + stdout)
        if stderr:
            parts.append("STDERR:\n" + stderr)
        return self._truncate_text("\n\n".join(parts))

    def _build_tool_context(self, user_text: str) -> tuple[str, str]:
        cleaned_text, regex_queries, ps_commands = self._parse_tool_directives(user_text)
        if not regex_queries and not ps_commands:
            return user_text, ""

        sections: list[str] = [
            "Local tool outputs (executed before answering):",
            f"Workspace: {self.settings.workspace_path}",
        ]

        for query in regex_queries:
            sections.append(f"\n[Regex Search] pattern={query}")
            sections.append(self._run_workspace_regex(query))

        for command in ps_commands:
            sections.append(f"\n[PowerShell] command={command}")
            sections.append(self._run_powershell(command))

        return (cleaned_text or user_text), "\n".join(sections)

    def send_message(self):
        if self._thread is not None:
            return  # generation already in progress
        text = self.input_box.toPlainText().strip()
        attachment_names = [p.name for p in self._attachments]
        if not text and not attachment_names:
            return
        attachment_context = self._build_attachment_context()
        processed_text, tool_context = self._build_tool_context(text)
        full_message = f"{attachment_context}{processed_text}" if attachment_context else processed_text
        if tool_context:
            full_message = f"{tool_context}\n\nUser request:\n{full_message}"

        if self.mode == "Plan":
            full_message = (
                "You are in PLAN mode. Do not write full implementation code yet. "
                "Respond with a concise, numbered step-by-step plan (files to touch, "
                "functions/classes to add or change, and open questions). Only after "
                "the plan is explicitly approved in a follow-up message should you write code.\n\n"
                f"{full_message}"
            )
        elif self.mode == "Agent":
            full_message = (
                "You are in AGENT mode: you edit and create files in the workspace directly, "
                "the same way GitHub Copilot's agent mode does. Use the workspace tree/context "
                "given to you to decide which files already exist (edit them) versus which are "
                "new (create them).\n"
                "For every file you create or modify, output ONE fenced code block per file whose "
                "opening fence includes the file's path relative to the workspace root using "
                "`file=<path>` right after the language, e.g.:\n"
                "```python file=src/app.py\n"
                "<the file's full new content>\n"
                "```\n"
                "Rules: always write the file's COMPLETE resulting content in the block (not a diff, "
                "not just the changed lines). Only add `file=<path>` for blocks that should actually "
                "be written to disk — omit it for illustrative snippets. Briefly explain what you "
                "changed in plain text outside the code blocks.\n\n"
                f"{full_message}"
            )

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

        # --- user message: its own card ---
        user_bubble = self._add_bubble("user")
        if self.mode == "Plan":
            user_bubble.set_tag("PLAN")
        elif self.mode == "Agent":
            user_bubble.set_tag("AGENT")
        user_bubble.set_html(display_text)

        # --- assistant reply: a separate, empty card that streams in ---
        assistant_bubble = self._add_bubble("assistant")
        assistant_bubble.set_html("<i style='color:#7a7b80;'>Thinking…</i>")
        self._current_assistant_bubble = assistant_bubble

        self._scroll_to_bottom()

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
        if self._current_assistant_bubble is None:
            return
        if not self._response_buffer:
            # first token arrived — clear the "Thinking…" placeholder
            self._current_assistant_bubble.clear_content()
        self._response_buffer += tok
        self._current_assistant_bubble.append_plain(tok)
        self._scroll_to_bottom()

    def _on_error(self, msg: str):
        if self._current_assistant_bubble is not None and not self._response_buffer:
            # replace the empty/"thinking" assistant card with an error card
            idx = self.messages_layout.indexOf(self._current_assistant_bubble)
            if idx != -1:
                self.messages_layout.takeAt(idx)
            self._current_assistant_bubble.deleteLater()
            self._current_assistant_bubble = None
        error_bubble = self._add_bubble("error")
        error_bubble.set_html(self._escape(msg))
        self._scroll_to_bottom()

    def _on_finished(self):
        if self._response_buffer.strip():
            self.history.append({"role": "assistant", "content": self._response_buffer})
            blocks = self._extract_code_blocks(self._response_buffer)
            applied_paths: list[str] = []
            for lang, code, path in blocks:
                if self.mode == "Agent" and path:
                    self.agentFileEdit.emit(path, lang, code)
                    applied_paths.append(path)
                elif not path:
                    self.codeBlockReady.emit(lang, code)
            if applied_paths:
                chips = " ".join(
                    f"<span style='background:#2b2440;color:#c9a6ff;border-radius:8px;"
                    f"padding:1px 8px;margin-right:4px;font-size:11px;'>📝 {self._escape(p)}</span>"
                    for p in applied_paths
                )
                status_bubble = self._add_bubble("system")
                status_bubble.set_html(f"Applied changes to:<br/>{chips}")
        elif self._current_assistant_bubble is not None:
            # no tokens ever arrived and no error was raised — drop the empty card
            idx = self.messages_layout.indexOf(self._current_assistant_bubble)
            if idx != -1:
                self.messages_layout.takeAt(idx)
                self._current_assistant_bubble.deleteLater()

        self._current_assistant_bubble = None

        if self._thread:
            self._thread.quit()
            self._thread.wait()
        self._thread = None
        self._worker = None
        self.send_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self._scroll_to_bottom()

    @staticmethod
    def _extract_code_blocks(text: str) -> list[tuple[str, str, Optional[str]]]:
        """Returns (language, code, file_path_or_None) for every fenced block.
        Agent-mode blocks look like ```python file=src/app.py ... ```."""
        pattern = re.compile(
            r"```(?P<lang>[a-zA-Z0-9+#_-]*)(?:[ \t]+file=(?P<path>[^\s`]+))?\n(?P<code>.*?)```",
            re.DOTALL,
        )
        return [
            (m.group("lang") or "text", m.group("code"), m.group("path"))
            for m in pattern.finditer(text)
        ]

    @staticmethod
    def _escape(text: str) -> str:
        return (
            text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br/>")
        )