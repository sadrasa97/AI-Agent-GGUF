"""Chat panel (right dock) — talks to whichever provider is active
(GGUF / OpenRouter / NVIDIA) on a background QThread so the UI never
blocks while tokens stream in.

Design language: a modern, "state-of-the-art" agentic IDE assistant —
think Copilot Chat / Cursor composer, pushed a notch further:
  - a single glass-like bordered chat surface with a soft gradient
    accent rail across the top
  - every turn is its own elevated card with a gradient avatar,
    role label, live timestamp and (for the assistant) a subtle
    "typing" affordance while streaming
  - fenced code blocks inside a message are detected and rendered as
    their own dark "code card" with a language chip + copy button,
    instead of being flattened into plain text
  - a floating pill composer with gradient send button, animated
    generating state, and compact icon actions
  - a redesigned session tab strip with a live "session dot" and a
    frosted "+ New chat" affordance
"""
from __future__ import annotations

import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, QThread, Signal, Qt, QTimer
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPlainTextEdit,
    QPushButton, QComboBox, QFileDialog, QFrame, QScrollArea,
    QSizePolicy, QApplication, QTabWidget, QTabBar, QToolButton, QInputDialog,
    QLineEdit, QGraphicsDropShadowEffect,
)
from PySide6.QtGui import QColor

from config.settings import Settings
from agent.providers import create_provider, ProviderError
from tools.code_tools import list_workspace_files, read_text_file
from tools.voice_input import (
    VoiceError,
    record_microphone_wav_until_stop,
    transcribe_audio_file,
)

# Attached files larger than this are truncated when inlined into the prompt.
MAX_ATTACHMENT_CHARS = 20_000
MAX_TOOL_OUTPUT_CHARS = 12_000
MAX_REGEX_MATCHES = 120


# ---------------------------------------------------------------------------
# Design tokens — a single palette shared by every widget in this module so
# the whole panel reads as one cohesive, intentional surface.
# ---------------------------------------------------------------------------
class Theme:
    app_bg = "#16171a"
    panel_bg = "#1b1c20"
    panel_border = "#2a2b30"
    surface = "#212227"
    surface_hover = "#282932"
    surface_border = "#34353c"
    divider = "#2a2b30"

    text = "#eaeaef"
    text_dim = "#9a9ba5"
    text_faint = "#6c6d76"

    accent_a = "#7c8cff"
    accent_b = "#a78bfa"
    accent_soft_bg = "#242645"
    accent_soft_border = "#3a3d70"

    danger = "#f4796b"
    danger_bg = "#301f22"
    danger_border = "#5a2f36"

    success = "#7ee0a3"
    warn = "#e6b673"

    code_bg = "#111214"
    code_border = "#2c2d33"


ACCENT_GRADIENT = f"qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {Theme.accent_a}, stop:1 {Theme.accent_b})"


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
        self._provider = None

    def stop(self):
        self._stop = True
        if self._provider is not None:
            try:
                self._provider.request_stop()
            except Exception:
                pass

    def run(self):
        try:
            provider = create_provider(self.settings)
            self._provider = provider
        except ProviderError as exc:
            self.error.emit(str(exc))
            self.finished.emit()
            return
        try:
            for tok in provider.stream(self.history, workspace_context=self.workspace_context):
                if self._stop or QThread.currentThread().isInterruptionRequested():
                    break
                self.token.emit(tok)
        except ProviderError as exc:
            if not self._stop:
                self.error.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            if not self._stop:
                self.error.emit(f"Unexpected error: {exc}")
        finally:
            try:
                provider.close()
            except Exception:
                pass
            self._provider = None
            self.finished.emit()


class VoiceTranscriptionWorker(QObject):
    status = Signal(str)
    transcript = Signal(str)
    finished = Signal()
    error = Signal(str)

    def __init__(self, settings: Settings):
        super().__init__()
        self.settings = settings
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        wav_path: Optional[Path] = None
        try:
            sample_rate = int(getattr(self.settings, "asr_sample_rate", 16000) or 16000)
            self.status.emit("Recording... click the mic button again to stop.")
            wav_path = record_microphone_wav_until_stop(sample_rate=sample_rate, should_stop=lambda: self._stop)
            self.status.emit("Transcribing with Qwen Voice...")
            text = transcribe_audio_file(wav_path, self.settings)
            self.transcript.emit(text)
        except VoiceError as exc:
            self.error.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self.error.emit(f"Voice capture failed: {exc}")
        finally:
            if wav_path is not None:
                try:
                    wav_path.unlink(missing_ok=True)
                except Exception:
                    pass
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


def _soft_shadow(blur=28, dy=6, alpha=110, color="#000000") -> QGraphicsDropShadowEffect:
    eff = QGraphicsDropShadowEffect()
    eff.setBlurRadius(blur)
    eff.setOffset(0, dy)
    c = QColor(color)
    c.setAlpha(alpha)
    eff.setColor(c)
    return eff


class ChatBubble(QFrame):
    """A single self-contained message card — either the user's question
    or the assistant's answer — styled like a modern agent-chat turn:
    gradient avatar + role name + timestamp, rich content below (with
    fenced code rendered as its own code card), own background/border
    and a soft drop shadow for a bit of depth.
    """

    ROLE_STYLES = {
        "user": {
            "bg": "#20232f",
            "border": "#33395a",
            "label": "You",
            "label_color": "#9db4ff",
            "avatar_grad": "qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #4f6bff, stop:1 #7c8cff)",
            "avatar": "🧑",
        },
        "assistant": {
            "bg": "#1c211d",
            "border": "#33472f",
            "label": "Assistant",
            "label_color": "#9bd39c",
            "avatar_grad": "qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #3d8b52, stop:1 #7ee0a3)",
            "avatar": "✨",
        },
        "error": {
            "bg": Theme.danger_bg,
            "border": Theme.danger_border,
            "label": "Error",
            "label_color": Theme.danger,
            "avatar_grad": "qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #7a2f2f, stop:1 #f4796b)",
            "avatar": "⚠",
        },
        "system": {
            "bg": "#1e1f27",
            "border": "#33353f",
            "label": "Agent",
            "label_color": "#c9a6ff",
            "avatar_grad": "qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #5b3fa0, stop:1 #a78bfa)",
            "avatar": "🛠",
        },
    }

    CODE_FENCE_RE = re.compile(
        r"(?ms)^```(?P<lang>[a-zA-Z0-9+#_-]*)[ \t]*\n(?P<code>.*?)\n^```[ \t]*"
    )
    RTL_RE = re.compile(r"[\u0590-\u08FF\uFB1D-\uFDFD\uFE70-\uFEFC]")

    retryRequested = Signal()

    def __init__(self, role: str, parent=None):
        super().__init__(parent)
        self.role = role
        self._raw_text = ""
        self._copy_text = ""
        style = self.ROLE_STYLES.get(role, self.ROLE_STYLES["assistant"])

        self.setObjectName("bubble")
        self.setStyleSheet(
            f"#bubble {{ background:{style['bg']}; border:1px solid {style['border']}; "
            f"border-radius:14px; }}"
        )
        self.setGraphicsEffect(_soft_shadow(blur=22, dy=4, alpha=70))
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(13, 11, 13, 12)
        outer.setSpacing(7)

        header = QHBoxLayout()
        header.setSpacing(9)

        avatar = QLabel(style["avatar"])
        avatar.setFixedSize(24, 24)
        avatar.setAlignment(Qt.AlignCenter)
        avatar.setStyleSheet(
            f"background:{style['avatar_grad']}; border-radius:12px; font-size:12px; "
            f"border:none; color:white;"
        )
        header.addWidget(avatar)

        role_label = QLabel(style["label"])
        role_label.setStyleSheet(
            f"color:{style['label_color']}; font-weight:700; font-size:12px; "
            f"letter-spacing:0.3px; background:transparent; border:none;"
        )
        header.addWidget(role_label)

        self.time_label = QLabel(datetime.now().strftime("%H:%M"))
        self.time_label.setStyleSheet(
            f"color:{Theme.text_faint}; font-size:10px; background:transparent; border:none;"
        )
        header.addWidget(self.time_label)

        header.addStretch()

        self.tag_label = QLabel("")
        self.tag_label.setStyleSheet(
            "color:#e0af68; background:#3a2f13; border-radius:8px; padding:1px 9px; "
            "font-size:10px; font-weight:700; letter-spacing:0.5px; border:none;"
        )
        self.tag_label.setVisible(False)
        header.addWidget(self.tag_label)
        outer.addLayout(header)

        # Content area holds a dynamic mix of QLabel (prose) and code-card
        # frames (fenced code), stacked vertically so code gets its own
        # visually distinct block instead of being crushed into plain text.
        self.content_col = QVBoxLayout()
        self.content_col.setContentsMargins(0, 0, 0, 0)
        self.content_col.setSpacing(8)
        outer.addLayout(self.content_col)

        self._prose_font = QFont("Segoe UI")
        if hasattr(self._prose_font, "setFamilies"):
            self._prose_font.setFamilies(["Segoe UI", "Tahoma", "Arial"])
        self._prose_font.setPointSize(10)

        self.footer = QHBoxLayout()
        self.footer.setContentsMargins(0, 2, 0, 0)
        self.footer.addStretch()

        if role in ("assistant", "error"):
            self.retry_btn = QPushButton("↻  Retry")
            self.retry_btn.setCursor(Qt.PointingHandCursor)
            self.retry_btn.setToolTip("Regenerate this response")
            self.retry_btn.setStyleSheet(self._secondary_btn_qss())
            self.retry_btn.clicked.connect(self.retryRequested.emit)
            self.footer.addWidget(self.retry_btn)
        else:
            self.retry_btn = None

        self.copy_btn = QPushButton("⧉  Copy")
        self.copy_btn.setVisible(False)
        self.copy_btn.setCursor(Qt.PointingHandCursor)
        self.copy_btn.setToolTip("Copy full response")
        self.copy_btn.setStyleSheet(self._secondary_btn_qss())
        self.copy_btn.clicked.connect(self._copy_text_to_clipboard)
        self.footer.addWidget(self.copy_btn)
        outer.addLayout(self.footer)

    @staticmethod
    def _secondary_btn_qss() -> str:
        return (
            f"QPushButton {{ background:{Theme.surface}; color:{Theme.text_dim}; padding:3px 10px; "
            f"border:1px solid {Theme.surface_border}; border-radius:8px; font-size:10px; font-weight:600; }}"
            f"QPushButton:hover {{ background:{Theme.surface_hover}; border:1px solid #4a4b52; color:{Theme.text}; }}"
            f"QPushButton:pressed {{ background:#1e1f22; }}"
        )

    def add_footer_button(self, text: str, callback, danger: bool = False) -> QPushButton:
        """Insert an extra action button (e.g. Undo) into this bubble's footer,
        left of the Copy/Retry buttons."""
        btn = QPushButton(text)
        btn.setCursor(Qt.PointingHandCursor)
        if danger:
            btn.setStyleSheet(
                f"QPushButton {{ background:{Theme.danger_bg}; color:{Theme.danger}; padding:3px 10px; "
                f"border:1px solid {Theme.danger_border}; border-radius:8px; font-size:10px; font-weight:700; }}"
                f"QPushButton:hover {{ background:#4a3131; color:#ff9b8c; }}"
                f"QPushButton:disabled {{ background:{Theme.surface}; color:{Theme.text_faint}; border:1px solid {Theme.surface_border}; }}"
            )
        else:
            btn.setStyleSheet(self._secondary_btn_qss())
        btn.clicked.connect(callback)
        self.footer.insertWidget(0, btn)
        return btn

        # single placeholder label used until real content streams in
        self._placeholder = self._make_prose_label()
        self.content_col.addWidget(self._placeholder)

    # ------------------------------------------------------------------
    def _make_prose_label(self) -> QLabel:
        lbl = QLabel("")
        lbl.setWordWrap(True)
        lbl.setTextFormat(Qt.RichText)
        lbl.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse)
        lbl.setOpenExternalLinks(True)
        lbl.setStyleSheet(f"QLabel {{ background:transparent; color:{Theme.text}; border:none; }}")
        lbl.setFont(self._prose_font)
        return lbl

    def _clear_content_widgets(self):
        while self.content_col.count():
            item = self.content_col.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _make_code_card(self, lang: str, code: str) -> QFrame:
        card = QFrame()
        card.setObjectName("codeCard")
        card.setStyleSheet(
            f"#codeCard {{ background:{Theme.code_bg}; border:1px solid {Theme.code_border}; "
            f"border-radius:10px; }}"
        )
        v = QVBoxLayout(card)
        v.setContentsMargins(10, 6, 10, 10)
        v.setSpacing(4)

        top = QHBoxLayout()
        lang_chip = QLabel((lang or "text").upper())
        lang_chip.setStyleSheet(
            f"color:{Theme.accent_b}; background:{Theme.accent_soft_bg}; border:1px solid {Theme.accent_soft_border}; "
            f"border-radius:6px; padding:1px 7px; font-size:9.5px; font-weight:700; letter-spacing:0.5px;"
        )
        top.addWidget(lang_chip)
        top.addStretch()
        copy_code_btn = QPushButton("⧉")
        copy_code_btn.setCursor(Qt.PointingHandCursor)
        copy_code_btn.setToolTip("Copy code block")
        copy_code_btn.setFixedWidth(26)
        copy_code_btn.setStyleSheet(
            f"QPushButton {{ background:transparent; color:{Theme.text_dim}; border:none; font-size:12px; }}"
            f"QPushButton:hover {{ color:{Theme.text}; }}"
        )
        copy_code_btn.clicked.connect(lambda _c=False, txt=code: self._copy_snippet(txt, copy_code_btn))
        top.addWidget(copy_code_btn)
        v.addLayout(top)

        body = QLabel(self._escape(code.rstrip("\n")))
        body.setWordWrap(False)
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        body.setStyleSheet(f"QLabel {{ background:transparent; color:#d7dae0; border:none; }}")
        code_font = QFont("Consolas, Menlo, monospace")
        code_font.setPointSize(10)
        body.setFont(code_font)
        v.addWidget(body)
        return card

    @staticmethod
    def _copy_snippet(text: str, button: QPushButton):
        QApplication.clipboard().setText(text)
        old = button.text()
        button.setText("✓")
        QTimer.singleShot(900, lambda: button.setText(old))

    @classmethod
    def _contains_rtl(cls, text: str) -> bool:
        return bool(cls.RTL_RE.search(text or ""))

    @classmethod
    def _with_direction(cls, html: str, plain_text: str) -> str:
        if cls._contains_rtl(plain_text):
            return f"<div dir='rtl' style='text-align:right;'>{html}</div>"
        return html

    # ------------------------------------------------------------------
    def set_tag(self, text: str):
        if text:
            self.tag_label.setText(text)
            self.tag_label.setVisible(True)
        else:
            self.tag_label.setVisible(False)

    def set_html(self, html: str):
        """Set static (non-streaming) content. Detects fenced code blocks
        in the *raw* text form and splits them into prose + code cards."""
        self._raw_text = html
        self._copy_text = html.replace("<br/>", "\n").replace("<br>", "\n")
        self._render_mixed_content(html)

    def _render_mixed_content(self, html: str):
        self._clear_content_widgets()
        if not html:
            lbl = self._make_prose_label()
            lbl.setText("&nbsp;")
            self.content_col.addWidget(lbl)
            return

        # html here already has <br/> in place of newlines for plain text;
        # to detect fences we work against a text edition with \n restored.
        text_form = html.replace("<br/>", "\n").replace("<br>", "\n")
        pos = 0
        found_any = False
        for m in self.CODE_FENCE_RE.finditer(text_form):
            found_any = True
            before = text_form[pos:m.start()].strip("\n")
            if before.strip():
                lbl = self._make_prose_label()
                lbl.setText(self._with_direction(self._escape(before), before))
                self.content_col.addWidget(lbl)
            self.content_col.addWidget(self._make_code_card(m.group("lang"), m.group("code")))
            pos = m.end()
        remainder = text_form[pos:].strip("\n")
        if remainder.strip() or not found_any:
            lbl = self._make_prose_label()
            if found_any:
                lbl.setText(self._with_direction(self._escape(remainder), remainder))
            else:
                lbl.setText(self._with_direction(html, text_form))
            self.content_col.addWidget(lbl)

    def append_plain(self, text: str):
        """Streaming path: keep it fast/simple — plain escaped text into a
        single growing label. Fence-aware re-render happens once streaming
        finishes (via set_html on the final buffer from the caller)."""
        escaped = (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("\n", "<br/>")
        )
        self._raw_text += escaped
        self._copy_text += text
        if self.content_col.count() != 1 or not isinstance(self.content_col.itemAt(0).widget(), QLabel):
            self._clear_content_widgets()
            self.content_col.addWidget(self._make_prose_label())
        lbl = self.content_col.itemAt(0).widget()
        lbl.setText(self._with_direction(self._raw_text, self._copy_text))

    def finalize_stream(self):
        """Call once streaming is complete to re-render with code cards."""
        self._render_mixed_content(self._raw_text)

    def clear_content(self):
        self._raw_text = ""
        self._copy_text = ""
        self._clear_content_widgets()
        self.content_col.addWidget(self._make_prose_label())

    def set_copy_text(self, text: str):
        self._copy_text = text or ""
        self.copy_btn.setVisible(bool(self._copy_text.strip()))

    def _copy_text_to_clipboard(self):
        if not self._copy_text.strip():
            return
        clipboard = QApplication.clipboard()
        clipboard.setText(self._copy_text)
        self.copy_btn.setText("✓  Copied")
        QTimer.singleShot(1200, lambda: self.copy_btn.setText("⧉  Copy"))

    @staticmethod
    def _escape(text: str) -> str:
        return (
            text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br/>")
        )


SCROLLBAR_QSS = f"""
QScrollBar:vertical {{ background:transparent; width:10px; margin:2px; }}
QScrollBar::handle:vertical {{ background:#3a3b42; border-radius:5px; min-height:24px; }}
QScrollBar::handle:vertical:hover {{ background:{Theme.accent_a}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0px; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background:none; }}
"""


class ChatPanel(QWidget):
    """Streaming chat UI + a 'insert into editor' hook."""

    codeBlockReady = Signal(str, str)  # (language, code) — generic snippet, not tied to a file
    agentFileEdit = Signal(str, str, str)  # (relative_path, language, code) — Agent mode auto-apply
    agentUndoRequested = Signal(list)  # list[str] of relative paths to revert, most-recent batch

    MODE_META = {
        "Agent": ("🤖", "Agent edits files directly in your workspace"),
        "Chat": ("💬", "Ask questions, you choose how to apply code"),
        "Plan": ("🧭", "Model drafts a step-by-step plan first"),
    }
    THINK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL | re.IGNORECASE)

    def __init__(self, settings: Settings, get_workspace_context, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.get_workspace_context = get_workspace_context  # callable() -> str
        self.history: list[dict] = []
        self._thread: Optional[QThread] = None
        self._worker: Optional[GenerationWorker] = None
        self._voice_thread: Optional[QThread] = None
        self._voice_worker: Optional[VoiceTranscriptionWorker] = None
        self._response_buffer = ""
        self._attachments: list[Path] = []
        self.mode = "Chat"  # "Chat", "Agent", or "Plan"
        self._current_assistant_bubble: Optional[ChatBubble] = None
        self._is_generating = False
        self._pending_tokens: list[str] = []
        self._stream_flush_timer = QTimer(self)
        self._stream_flush_timer.setInterval(35)
        self._stream_flush_timer.timeout.connect(self._flush_stream_tokens)
        self._gen_dots_timer = QTimer(self)
        self._gen_dots_timer.setInterval(420)
        self._gen_dots_timer.timeout.connect(self._tick_generating_label)
        self._gen_dots_phase = 0

        self.setStyleSheet(f"background:{Theme.app_bg};")

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(10, 10, 10, 10)
        outer_layout.setSpacing(0)

        # ---- the whole chat lives inside ONE bordered outer box ----
        chat_box = QFrame()
        chat_box.setObjectName("chatBox")
        chat_box.setStyleSheet(
            f"#chatBox {{ background:{Theme.panel_bg}; border:1px solid {Theme.panel_border}; border-radius:16px; }}"
        )
        chat_box.setGraphicsEffect(_soft_shadow(blur=34, dy=8, alpha=130))
        outer_layout.addWidget(chat_box)

        layout = QVBoxLayout(chat_box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ---- gradient accent rail + header ----
        accent_rail = QFrame()
        accent_rail.setFixedHeight(3)
        accent_rail.setStyleSheet(
            f"background:{ACCENT_GRADIENT}; border-top-left-radius:16px; border-top-right-radius:16px;"
        )
        layout.addWidget(accent_rail)

        header = QHBoxLayout()
        header.setContentsMargins(14, 10, 12, 8)
        header.setSpacing(8)

        title_dot = QLabel("●")
        title_dot.setStyleSheet(f"color:{Theme.accent_a}; font-size:9px;")
        header.addWidget(title_dot)

        title = QLabel("CHAT")
        title.setStyleSheet(
            f"color:{Theme.text_dim}; font-weight:700; font-size:11px; letter-spacing:1.8px; background:transparent;"
        )
        header.addWidget(title)

        self.mode_badge = QLabel()
        self.mode_badge.setStyleSheet(
            f"color:{Theme.accent_b}; background:{Theme.accent_soft_bg}; border:1px solid {Theme.accent_soft_border}; "
            f"border-radius:8px; padding:2px 9px; font-size:10px; font-weight:700;"
        )
        header.addWidget(self.mode_badge)

        header.addStretch()

        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet(
            f"color:{Theme.text_faint}; font-size:10.5px; background:transparent;"
        )
        header.addWidget(self.status_label)

        self.clear_btn = QToolButton()
        self.clear_btn.setText("⟲")
        self.clear_btn.setCursor(Qt.PointingHandCursor)
        self.clear_btn.setToolTip("Clear this chat session")
        self.clear_btn.setStyleSheet(
            f"QToolButton {{ color:{Theme.text_dim}; background:transparent; border:none; font-size:13px; padding:2px 4px; }}"
            f"QToolButton:hover {{ color:{Theme.text}; }}"
        )
        self.clear_btn.clicked.connect(self.clear_history)
        header.addWidget(self.clear_btn)

        layout.addLayout(header)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"background:{Theme.divider}; max-height:1px; border:none;")
        layout.addWidget(sep)

        # ---- scrollable message list — each turn its own card ----
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet(f"QScrollArea {{ background:transparent; border:none; }} {SCROLLBAR_QSS}")

        self.messages_container = QWidget()
        self.messages_container.setStyleSheet("background:transparent;")
        self.messages_layout = QVBoxLayout(self.messages_container)
        self.messages_layout.setContentsMargins(12, 10, 12, 8)
        self.messages_layout.setSpacing(11)

        # ---- empty-state hero shown before the first message ----
        self.empty_state = self._build_empty_state()
        self.messages_layout.addWidget(self.empty_state)
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

        # ---- composer: rounded "pill" input card, agent-style ----
        self.composer = QWidget()
        self.composer.setObjectName("composer")
        self._apply_composer_style(focused=False)
        composer_layout = QVBoxLayout(self.composer)
        composer_layout.setContentsMargins(11, 9, 11, 9)
        composer_layout.setSpacing(7)

        self.input_box = ChatInputBox()
        self.input_box.setFixedHeight(64)
        self.input_box.setPlaceholderText(
            "Ask the model to write/explain/fix code…  (Enter to send, Shift+Enter new line)"
        )
        self.input_box.setToolTip(
            "Optional tool directives in your message:\n"
            "  /regex <pattern>  -> search workspace with Python regex\n"
            "  /ps <command>     -> run PowerShell command in workspace"
        )
        self.input_box.setStyleSheet(
            f"QPlainTextEdit {{ background:transparent; color:{Theme.text}; border:none; padding:2px; "
            f"selection-background-color:{Theme.accent_soft_border}; }}"
        )
        input_font = QFont("Segoe UI, Consolas, sans-serif")
        input_font.setPointSize(10)
        self.input_box.setFont(input_font)
        self.input_box.submitRequested.connect(self._on_send_or_stop)
        composer_layout.addWidget(self.input_box)

        composer_btn_row = QHBoxLayout()
        composer_btn_row.setSpacing(6)

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

        self.voice_btn = QPushButton("🎤")
        self.voice_btn.setToolTip("Record voice (click again to stop and transcribe)")
        self.voice_btn.clicked.connect(self._toggle_voice_recording)
        composer_btn_row.addWidget(self.voice_btn)

        composer_btn_row.addStretch()

        self.send_btn = QPushButton("➤  Send")
        self.send_btn.setCursor(Qt.PointingHandCursor)
        self.send_btn.setToolTip("Send (Enter)")
        self.send_btn.clicked.connect(self._on_send_or_stop)
        composer_btn_row.addWidget(self.send_btn)
        composer_layout.addLayout(composer_btn_row)

        # ---- small, pill-shaped, understated buttons/pickers ----
        combo_style = (
            f"QComboBox {{ background:{Theme.surface}; color:{Theme.text_dim}; padding:3px 9px; "
            f"border:1px solid {Theme.surface_border}; border-radius:9px; font-size:10.5px; font-weight:600; min-height:18px; }}"
            f"QComboBox:hover {{ background:{Theme.surface_hover}; border:1px solid #4a4b52; color:{Theme.text}; }}"
            f"QComboBox::drop-down {{ border:none; width:16px; }}"
            f"QComboBox QAbstractItemView {{ background:{Theme.surface}; color:#ddd; selection-background-color:#3a3b40; "
            f"border:1px solid {Theme.surface_border}; outline:none; }}"
        )
        self.mode_combo.setStyleSheet(combo_style)
        self.backend_combo.setStyleSheet(combo_style)

        icon_btn_style = (
            f"QPushButton {{ background:{Theme.surface}; color:{Theme.text_dim}; padding:4px 8px; "
            f"border:1px solid {Theme.surface_border}; border-radius:9px; font-size:12px; min-width:14px; }}"
            f"QPushButton:hover {{ background:{Theme.surface_hover}; border:1px solid #4a4b52; color:{Theme.text}; }}"
            f"QPushButton:pressed {{ background:#1e1f22; }}"
        )
        self.attach_btn.setStyleSheet(icon_btn_style)
        self.voice_btn.setStyleSheet(icon_btn_style)
        self._style_send_button(generating=False)

        self.input_box.installEventFilter(self)

        outer_composer_row = QHBoxLayout()
        outer_composer_row.setContentsMargins(12, 0, 12, 12)
        outer_composer_row.addWidget(self.composer)
        layout.addLayout(outer_composer_row)

        self._update_mode_badge()

    # ------------------------------------------------------------------
    # Cosmetic helpers
    # ------------------------------------------------------------------
    def _build_empty_state(self) -> QWidget:
        wrap = QWidget()
        wrap.setStyleSheet("background:transparent;")
        v = QVBoxLayout(wrap)
        v.setContentsMargins(20, 46, 20, 30)
        v.setSpacing(6)
        v.setAlignment(Qt.AlignHCenter)

        badge = QLabel("✨")
        badge.setAlignment(Qt.AlignCenter)
        badge.setFixedSize(52, 52)
        badge.setStyleSheet(
            f"background:{ACCENT_GRADIENT}; border-radius:26px; font-size:22px; color:white;"
        )
        v.addWidget(badge, alignment=Qt.AlignHCenter)

        heading = QLabel("Ready when you are")
        heading.setAlignment(Qt.AlignCenter)
        heading.setStyleSheet(f"color:{Theme.text}; font-size:14px; font-weight:700; background:transparent;")
        v.addWidget(heading)

        sub = QLabel("Ask a question, request a fix, or describe a feature.\nSwitch modes below to control how changes are applied.")
        sub.setAlignment(Qt.AlignCenter)
        sub.setWordWrap(True)
        sub.setStyleSheet(f"color:{Theme.text_faint}; font-size:11px; background:transparent;")
        v.addWidget(sub)
        return wrap

    def _apply_composer_style(self, focused: bool):
        border = Theme.accent_a if focused else Theme.surface_border
        self.composer.setStyleSheet(
            f"#composer {{ background:{Theme.surface}; border:1.5px solid {border}; border-radius:16px; }}"
        )

    def eventFilter(self, obj, event):
        if obj is self.input_box:
            if event.type() == event.Type.FocusIn:
                self._apply_composer_style(True)
            elif event.type() == event.Type.FocusOut:
                self._apply_composer_style(False)
        return super().eventFilter(obj, event)

    def _update_mode_badge(self):
        icon, tip = self.MODE_META.get(self.mode, ("💬", ""))
        self.mode_badge.setText(f"{icon} {self.mode.upper()}")
        self.mode_badge.setToolTip(tip)

    def _style_send_button(self, generating: bool):
        if generating:
            self.send_btn.setText("■  Stop")
            self.send_btn.setToolTip("Stop generation")
            self.send_btn.setStyleSheet(
                f"QPushButton {{ background:{Theme.danger_bg}; color:{Theme.danger}; padding:5px 14px; "
                f"border:1px solid {Theme.danger_border}; border-radius:10px; font-size:11.5px; font-weight:700; }}"
                f"QPushButton:hover {{ background:#4a3131; color:#ff9b8c; border:1px solid #6a4040; }}"
                f"QPushButton:pressed {{ background:#2f2121; }}"
            )
            return
        self.send_btn.setText("➤  Send")
        self.send_btn.setToolTip("Send (Enter)")
        self.send_btn.setStyleSheet(
            f"QPushButton {{ background:{ACCENT_GRADIENT}; color:white; padding:5px 16px; border:none; "
            f"border-radius:10px; font-weight:700; font-size:11.5px; min-width:26px; }}"
            f"QPushButton:hover {{ background:{Theme.accent_a}; }}"
            f"QPushButton:pressed {{ background:#5b78e0; }}"
            f"QPushButton:disabled {{ background:#33343a; color:#6a6a6e; }}"
        )

    def _tick_generating_label(self):
        dots = "." * ((self._gen_dots_phase % 3) + 1)
        self._gen_dots_phase += 1
        self.status_label.setText(f"Generating{dots}")

    # ------------------------------------------------------------------
    def _on_backend_changed(self, text: str):
        self.settings.backend = text
        self.settings.save()

    def _on_send_or_stop(self):
        if self._is_generating:
            self.stop_generation()
            return
        self.send_message()

    def _set_generation_state(self, generating: bool):
        self._is_generating = generating
        self._style_send_button(generating)
        if generating:
            self._gen_dots_phase = 0
            self._gen_dots_timer.start()
            self._tick_generating_label()
        else:
            self._gen_dots_timer.stop()
            self.status_label.setText("Ready")

    def _on_mode_changed(self, text: str):
        self.mode = text
        if text == "Plan":
            placeholder = "Describe what you want built — I'll draft a plan first…  (Enter to send, Shift+Enter new line)"
        elif text == "Agent":
            placeholder = "Describe what to build or fix — the agent will edit/create files directly…  (Enter to send, Shift+Enter new line)"
        else:
            placeholder = "Ask the model to write/explain/fix code…  (Enter to send, Shift+Enter new line)"
        self.input_box.setPlaceholderText(placeholder)
        self._update_mode_badge()

    def clear_history(self):
        self.history.clear()
        while self.messages_layout.count() > 2:  # keep empty-state + trailing stretch
            item = self.messages_layout.takeAt(0)
            w = item.widget()
            if w and w is not self.empty_state:
                w.deleteLater()
        self.empty_state.setVisible(True)
        self._current_assistant_bubble = None

    def _toggle_voice_recording(self):
        if self._voice_thread is not None:
            if self._voice_worker:
                self._voice_worker.stop()
            return

        self._voice_worker = VoiceTranscriptionWorker(self.settings)
        self._voice_thread = QThread()
        self._voice_worker.moveToThread(self._voice_thread)

        self._voice_thread.started.connect(self._voice_worker.run)
        self._voice_worker.status.connect(self._on_voice_status)
        self._voice_worker.transcript.connect(self._on_voice_transcript)
        self._voice_worker.error.connect(self._on_voice_error)
        self._voice_worker.finished.connect(self._on_voice_finished)

        self.voice_btn.setText("■")
        self.voice_btn.setToolTip("Stop recording")
        self.voice_btn.setStyleSheet(
            f"QPushButton {{ background:{Theme.danger_bg}; color:{Theme.danger}; padding:4px 8px; "
            f"border:1px solid {Theme.danger_border}; border-radius:9px; font-size:12px; min-width:14px; }}"
            f"QPushButton:hover {{ background:#4a3131; color:#ff9b8c; border:1px solid #6a4040; }}"
            f"QPushButton:pressed {{ background:#2f2121; }}"
        )
        self._voice_thread.start()

    def _on_voice_status(self, text: str):
        bubble = self._add_bubble("system")
        bubble.set_html(self._escape(text))
        self._scroll_to_bottom()

    def _on_voice_transcript(self, text: str):
        current = self.input_box.toPlainText().strip()
        merged = f"{current}\n{text}" if current else text
        self.input_box.setPlainText(merged)
        self.input_box.setFocus()
        cursor = self.input_box.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.input_box.setTextCursor(cursor)

        bubble = self._add_bubble("system")
        bubble.set_html("Voice transcribed and inserted into the composer.")
        self._scroll_to_bottom()

    def _on_voice_error(self, msg: str):
        bubble = self._add_bubble("error")
        bubble.set_html(self._escape(msg))
        self._scroll_to_bottom()

    def _on_voice_finished(self):
        if self._voice_thread:
            self._voice_thread.quit()
            self._voice_thread.wait()
        self._voice_thread = None
        self._voice_worker = None

        self.voice_btn.setText("🎤")
        self.voice_btn.setToolTip("Record voice (click again to stop and transcribe)")
        self.voice_btn.setStyleSheet(
            f"QPushButton {{ background:{Theme.surface}; color:{Theme.text_dim}; padding:4px 8px; "
            f"border:1px solid {Theme.surface_border}; border-radius:9px; font-size:12px; min-width:14px; }}"
            f"QPushButton:hover {{ background:{Theme.surface_hover}; border:1px solid #4a4b52; color:{Theme.text}; }}"
            f"QPushButton:pressed {{ background:#1e1f22; }}"
        )

    # ------------------------------------------------------------------
    # Bubble management
    # ------------------------------------------------------------------
    def _add_bubble(self, role: str) -> ChatBubble:
        self.empty_state.setVisible(False)
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
            chip.setCursor(Qt.PointingHandCursor)
            chip.setToolTip(str(path))
            chip.setStyleSheet(
                f"QPushButton {{ background:{Theme.surface}; color:{Theme.text_dim}; padding:3px 10px; "
                f"border:1px solid {Theme.surface_border}; border-radius:10px; font-size:11px; }}"
                f"QPushButton:hover {{ background:{Theme.danger_bg}; color:{Theme.danger}; border:1px solid {Theme.danger_border}; }}"
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
                f"<span style='background:{Theme.surface};color:{Theme.text_dim};border-radius:8px;"
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

        self._start_generation()

    def _start_generation(self):
        """Kick off a GenerationWorker against the current self.history.
        Shared by send_message() (fresh turn) and retry_last() (regenerate)."""
        if self._thread is not None:
            return

        # --- assistant reply: a separate, empty card that streams in ---
        assistant_bubble = self._add_bubble("assistant")
        assistant_bubble.set_html(f"<i style='color:{Theme.text_faint};'>Thinking…</i>")
        assistant_bubble.retryRequested.connect(lambda b=assistant_bubble: self.retry_last(b))
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

        self._set_generation_state(True)

    def retry_last(self, bubble: "ChatBubble"):
        """Regenerate a response: drop the given bubble (and, if it corresponds
        to the most recent assistant turn, its entry in history) and re-run
        generation against the same prompt/history."""
        if self._thread is not None:
            return  # already generating, ignore double-clicks

        if self.history and self.history[-1].get("role") == "assistant":
            self.history.pop()

        idx = self.messages_layout.indexOf(bubble)
        if idx != -1:
            self.messages_layout.takeAt(idx)
        bubble.deleteLater()
        if self._current_assistant_bubble is bubble:
            self._current_assistant_bubble = None

        self._start_generation()

    def _undo_applied(self, paths: list[str], button: QPushButton):
        button.setEnabled(False)
        button.setText("Reverted")
        self.agentUndoRequested.emit(paths)

    def stop_generation(self):
        if not self._is_generating:
            return

        # First click should always register immediately in the UI.
        self.status_label.setText("Stopping...")
        self.send_btn.setEnabled(False)

        if self._worker:
            self._worker.stop()
        if self._thread:
            self._thread.requestInterruption()

    def _on_token(self, tok: str):
        if self._current_assistant_bubble is None:
            return
        self._pending_tokens.append(tok)
        if not self._stream_flush_timer.isActive():
            self._stream_flush_timer.start()

    def _flush_stream_tokens(self):
        if self._current_assistant_bubble is None or not self._pending_tokens:
            return
        chunk = "".join(self._pending_tokens)
        self._pending_tokens.clear()
        if not self._response_buffer:
            # first streamed chunk arrived — clear the "Thinking…" placeholder
            self._current_assistant_bubble.clear_content()
        self._response_buffer += chunk
        self._current_assistant_bubble.append_plain(chunk)
        self._scroll_to_bottom()

    def _on_error(self, msg: str):
        self._flush_stream_tokens()
        if self._current_assistant_bubble is not None and not self._response_buffer:
            # replace the empty/"thinking" assistant card with an error card
            idx = self.messages_layout.indexOf(self._current_assistant_bubble)
            if idx != -1:
                self.messages_layout.takeAt(idx)
            self._current_assistant_bubble.deleteLater()
            self._current_assistant_bubble = None
        error_bubble = self._add_bubble("error")
        error_bubble.set_html(self._escape(msg))
        error_bubble.set_copy_text(msg)
        self._scroll_to_bottom()

    def _on_finished(self):
        self._flush_stream_tokens()
        self._stream_flush_timer.stop()
        clean_response = self._sanitize_response_text(self._response_buffer)
        if clean_response.strip():
            self.history.append({"role": "assistant", "content": clean_response})
            if self._current_assistant_bubble is not None:
                self._current_assistant_bubble.set_html(self._escape(clean_response))
                self._current_assistant_bubble.set_copy_text(clean_response)
            blocks = self._extract_code_blocks(clean_response)
            applied_paths: list[str] = []
            for lang, code, path in blocks:
                if self.mode == "Agent" and path:
                    self.agentFileEdit.emit(path, lang, code)
                    applied_paths.append(path)
            if applied_paths:
                chips = " ".join(
                    f"<span style='background:{Theme.accent_soft_bg};color:{Theme.accent_b};border-radius:8px;"
                    f"padding:1px 8px;margin-right:4px;font-size:11px;'>📝 {self._escape(p)}</span>"
                    for p in applied_paths
                )
                status_bubble = self._add_bubble("system")
                status_bubble.set_html(f"Applied changes to:<br/>{chips}")
                undo_btn = status_bubble.add_footer_button("↩  Undo", lambda: None, danger=True)
                undo_btn.clicked.disconnect()
                undo_btn.clicked.connect(
                    lambda _c=False, paths=list(applied_paths), b=undo_btn: self._undo_applied(paths, b)
                )
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
        self._set_generation_state(False)
        self._scroll_to_bottom()

    @staticmethod
    def _extract_code_blocks(text: str) -> list[tuple[str, str, Optional[str]]]:
        """Returns (language, code, file_path_or_None) for every fenced block.
        Agent-mode blocks look like ```python file=src/app.py ... ```."""
        pattern = re.compile(
            r"(?ms)^```(?P<lang>[a-zA-Z0-9+#_-]*)(?:[ \t]+file=(?P<path>[^\s`]+))?[ \t]*\n"
            r"(?P<code>.*?)\n^```[ \t]*",
        )
        return [
            (m.group("lang") or "text", m.group("code"), m.group("path"))
            for m in pattern.finditer(text)
        ]

    @classmethod
    def _sanitize_response_text(cls, text: str) -> str:
        if not text:
            return ""
        cleaned = cls.THINK_RE.sub("", text)
        return cleaned.strip()

    @staticmethod
    def _escape(text: str) -> str:
        return (
            text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br/>")
        )


class ChatTabsPanel(QWidget):
    """Hosts multiple independent ChatPanel sessions in a tabbed strip
    above the chat area (agent-style 'new session' tabs), restyled with
    a slightly more premium tab bar (accent underline, live dot, frosted
    '+ New chat' affordance).

    Each tab owns its own ChatPanel instance, which means its own
    `history` list, its own GenerationWorker/QThread, its own attachments,
    mode, and backend selector — sessions never share state. Closing a
    tab tears down that ChatPanel's in-flight generation (if any) and
    discards its history.
    """

    codeBlockReady = Signal(str, str)              # (language, code) — from active session
    agentFileEdit = Signal(str, str, str)           # (relative_path, language, code) — from any session
    agentUndoRequested = Signal(list)               # list[str] relative paths — from any session

    def __init__(self, settings: Settings, get_workspace_context, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.get_workspace_context = get_workspace_context
        self._session_counter = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.setStyleSheet(f"background:{Theme.app_bg};")

        self.tabs = QTabWidget()
        # Native close buttons are replaced below with the same custom
        # QToolButton close affordance used by the editor tabs, so both
        # tab strips in the app look and behave identically.
        self.tabs.setTabsClosable(False)
        self.tabs.setMovable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.tabBarDoubleClicked.connect(self._rename_tab)
        # Same flat tab shape + bottom accent underline as EditorTabs
        # (see ui_qt/editor.py THEMES[...]["tabs_style"]) so the chat tab
        # bar is visually identical to the editor tab bar.
        self.tabs.setStyleSheet(
            f"QTabWidget::pane {{ border:none; background:{Theme.panel_bg}; top:-1px; }}"
            f"QTabBar {{ qproperty-drawBase: 0; background:{Theme.app_bg}; }}"
            f"QTabBar::tab {{ background:{Theme.surface}; color:{Theme.text_dim}; "
            f"padding:10px 24px 10px 16px; margin-right:2px; border:none; "
            f"border-bottom:2px solid transparent; font-size:12px; font-weight:600; }}"
            f"QTabBar::tab:selected {{ background:{Theme.panel_bg}; color:{Theme.text}; "
            f"border-bottom:2px solid {Theme.accent_a}; }}"
            f"QTabBar::tab:hover:!selected {{ background:{Theme.surface_hover}; color:{Theme.text}; }}"
        )
        layout.addWidget(self.tabs, stretch=1)

        # "+ New chat" button pinned to the tab bar's corner.
        new_tab_btn = QToolButton()
        new_tab_btn.setText("＋ New")
        new_tab_btn.setCursor(Qt.PointingHandCursor)
        new_tab_btn.setToolTip("New chat session (Ctrl+T)")
        new_tab_btn.setStyleSheet(
            f"QToolButton {{ background:{ACCENT_GRADIENT}; color:white; border:none; "
            f"border-radius:8px; padding:4px 12px; font-weight:700; font-size:11px; margin:5px; }}"
            f"QToolButton:hover {{ background:{Theme.accent_a}; }}"
        )
        new_tab_btn.clicked.connect(lambda: self.add_new_tab())
        self.tabs.setCornerWidget(new_tab_btn, Qt.TopRightCorner)

        self.add_new_tab()

    # ------------------------------------------------------------------
    def add_new_tab(self, title: Optional[str] = None) -> ChatPanel:
        self._session_counter += 1
        panel = ChatPanel(self.settings, self.get_workspace_context)
        panel.codeBlockReady.connect(self.codeBlockReady.emit)
        panel.agentFileEdit.connect(self.agentFileEdit.emit)
        panel.agentUndoRequested.connect(self.agentUndoRequested.emit)

        label = title or f"Chat {self._session_counter}"
        index = self.tabs.addTab(panel, label)
        self._install_close_button(index)
        self.tabs.setCurrentIndex(index)
        panel.input_box.setFocus()
        return panel

    def _install_close_button(self, index: int):
        """Attach a close button styled exactly like EditorTabs' close
        button (ui_qt/editor.py THEMES[...]["tab_close_btn"]), instead of
        Qt's native (differently shaped) close indicator."""
        btn = QToolButton()
        btn.setText("✕")
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFixedSize(18, 18)
        btn.setToolTip("Close chat session")
        btn.setStyleSheet(
            "QToolButton { color:#5A647D; background: transparent; border: none; "
            "padding: 0px; border-radius: 4px; font-size: 11px; }"
            "QToolButton:hover { color:#E2E8F0; background:#252B3D; }"
        )
        btn.clicked.connect(lambda: self._close_tab(self._index_of_button(btn)))
        self.tabs.tabBar().setTabButton(index, QTabBar.ButtonPosition.RightSide, btn)

    def _index_of_button(self, button) -> int:
        bar = self.tabs.tabBar()
        for i in range(bar.count()):
            if bar.tabButton(i, QTabBar.ButtonPosition.RightSide) is button:
                return i
        return -1

    def _close_tab(self, index: int):
        panel = self.tabs.widget(index)
        if panel is None:
            return
        if self.tabs.count() <= 1:
            # Keep at least one session alive — reset it instead of removing.
            panel.stop_generation()
            panel.clear_history()
            return
        panel.stop_generation()
        self.tabs.removeTab(index)
        panel.deleteLater()

    def _rename_tab(self, index: int):
        if index < 0:
            return
        current = self.tabs.tabText(index)
        new_name, ok = QInputDialog.getText(
            self, "Rename Chat Session", "Session name:", QLineEdit.Normal, current
        )
        if ok and new_name.strip():
            self.tabs.setTabText(index, new_name.strip())

    # ------------------------------------------------------------------
    # Compatibility helpers used by MainWindow
    # ------------------------------------------------------------------
    @property
    def current_panel(self) -> Optional[ChatPanel]:
        return self.tabs.currentWidget()

    def all_panels(self) -> list[ChatPanel]:
        return [self.tabs.widget(i) for i in range(self.tabs.count())]

    def sync_backend_combo(self, backend: str):
        """Reflect a backend change (made elsewhere, e.g. Model Settings dialog)
        across every open chat session."""
        for panel in self.all_panels():
            if panel is not None:
                panel.backend_combo.blockSignals(True)
                panel.backend_combo.setCurrentText(backend)
                panel.backend_combo.blockSignals(False)