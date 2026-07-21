"""
Markdown Viewer — VS Code-style Edit/Preview/Split mode for .md files.

Provides:
  - MarkdownViewer: renders markdown to styled HTML using QTextBrowser
  - MarkdownEditorPage: split-panel with CodeEditor (left) + MarkdownViewer (right),
    with toggle buttons for Edit | Preview | Both modes (same as VS Code).
"""
from __future__ import annotations
import html
import importlib
import re
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QColor, QTextCursor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QTextBrowser,
    QPushButton, QFrame, QSizePolicy, QToolButton, QApplication,
    QLabel, QScrollArea,
)

from ui_qt.editor import CodeEditor, THEMES

try:
    MarkdownIt = importlib.import_module("markdown_it").MarkdownIt
    footnote_plugin = importlib.import_module("mdit_py_plugins.footnote").footnote_plugin
    tasklists_plugin = importlib.import_module("mdit_py_plugins.tasklists").tasklists_plugin
    dollarmath_plugin = importlib.import_module("mdit_py_plugins.dollarmath").dollarmath_plugin
except Exception:
    MarkdownIt = None

# ──────────────────────────────────────────────────────────────
# Markdown → HTML conversion (lightweight, no external deps)
# ──────────────────────────────────────────────────────────────

MD_THEMES = {
    "dark": {
        "bg": "#0B0D14",
        "text": "#E2E8F0",
        "heading": "#C0C8E2",
        "link": "#7CB8FF",
        "code_bg": "#161A26",
        "code_text": "#D4D4D8",
        "blockquote_border": "#3A4466",
        "blockquote_bg": "#11141F",
        "hr": "#1E2333",
        "table_border": "#252B3D",
        "table_bg": "#0F111A",
        "table_alt_bg": "#131620",
        "inline_code_bg": "#1A1E2E",
    },
    "light": {
        "bg": "#FFFFFF",
        "text": "#1F2937",
        "heading": "#111827",
        "link": "#2563EB",
        "code_bg": "#F3F4F6",
        "code_text": "#1F2937",
        "blockquote_border": "#D1D5DB",
        "blockquote_bg": "#F9FAFB",
        "hr": "#E5E7EB",
        "table_border": "#E5E7EB",
        "table_bg": "#FFFFFF",
        "table_alt_bg": "#F9FAFB",
        "inline_code_bg": "#F3F4F6",
    },
}


def _md_to_html(md_text: str, theme: str = "dark") -> str:
    """Convert markdown text to styled HTML.

    Uses markdown-it (CommonMark + GFM-like extensions) when available,
    with a lightweight fallback parser so the app still works without
    extra dependencies.
    """
    t = MD_THEMES.get(theme, MD_THEMES["dark"])

    def _fallback_regex_render(src: str) -> str:
        rendered = html.escape(src)
        rendered = re.sub(
            r"```(\w*)\n(.*?)```",
            lambda m: (
                "<div class='md-code-block'>"
                + (f"<span class='md-lang-label'>{m.group(1).upper()}</span>" if m.group(1) else "")
                + f"<pre><code>{m.group(2)}</code></pre></div>"
            ),
            rendered,
            flags=re.DOTALL,
        )
        rendered = re.sub(r"`([^`]+)`", r"<code class='md-inline-code'>\1</code>", rendered)
        rendered = re.sub(r"^###### (.+)$", r"<h6>\1</h6>", rendered, flags=re.MULTILINE)
        rendered = re.sub(r"^##### (.+)$", r"<h5>\1</h5>", rendered, flags=re.MULTILINE)
        rendered = re.sub(r"^#### (.+)$", r"<h4>\1</h4>", rendered, flags=re.MULTILINE)
        rendered = re.sub(r"^### (.+)$", r"<h3>\1</h3>", rendered, flags=re.MULTILINE)
        rendered = re.sub(r"^## (.+)$", r"<h2>\1</h2>", rendered, flags=re.MULTILINE)
        rendered = re.sub(r"^# (.+)$", r"<h1>\1</h1>", rendered, flags=re.MULTILINE)
        rendered = re.sub(r"\*\*\*(.+?)\*\*\*", r"<strong><em>\1</em></strong>", rendered)
        rendered = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", rendered)
        rendered = re.sub(r"\*(.+?)\*", r"<em>\1</em>", rendered)
        rendered = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", r'<img src="\2" alt="\1" class="md-image"/>', rendered)
        rendered = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', rendered)
        rendered = re.sub(r"^> (.+)$", r"<blockquote>\1</blockquote>", rendered, flags=re.MULTILINE)
        rendered = re.sub(r"^---+\s*$", r"<hr class='md-hr'/>", rendered, flags=re.MULTILINE)
        rendered = rendered.replace("\n", "<br/>")
        return rendered

    if MarkdownIt is not None:
        parser = MarkdownIt("commonmark", {"html": False, "linkify": True, "typographer": True})
        parser.enable("table")
        parser.enable("strikethrough")
        parser.use(tasklists_plugin)
        parser.use(footnote_plugin)
        parser.use(dollarmath_plugin)

        default_fence = parser.renderer.rules.get("fence")

        def _fence_rule(tokens, idx, options, env):
            token = tokens[idx]
            info = (token.info or "").strip().split(" ")[0].lower()
            code = html.escape(token.content)
            lang_label = f"<span class='md-lang-label'>{info.upper()}</span>" if info else ""
            if info == "mermaid":
                return (
                    "<div class='md-code-block mermaid-block'>"
                    "<span class='md-lang-label'>MERMAID</span>"
                    f"<pre><code>{code}</code></pre>"
                    "</div>"
                )
            return (
                "<div class='md-code-block'>"
                f"{lang_label}"
                f"<pre><code>{code}</code></pre>"
                "</div>"
            )

        parser.renderer.rules["fence"] = _fence_rule
        parser.renderer.rules["code_block"] = _fence_rule
        html_body = parser.render(md_text)
        _ = default_fence
    else:
        html_body = _fallback_regex_render(md_text)

    # Build the full HTML document with VS Code-like styling
    full_html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"/>
<style>
body {{
    background-color: {t['bg']};
    color: {t['text']};
    font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, sans-serif;
    font-size: 14px;
    line-height: 1.6;
    padding: 16px 24px;
    margin: 0;
}}
h1 {{ color: {t['heading']}; font-size: 1.8em; font-weight: 600; border-bottom: 1px solid {t['hr']}; padding-bottom: 8px; margin-top: 24px; }}
h2 {{ color: {t['heading']}; font-size: 1.5em; font-weight: 600; border-bottom: 1px solid {t['hr']}; padding-bottom: 6px; margin-top: 20px; }}
h3 {{ color: {t['heading']}; font-size: 1.25em; font-weight: 600; margin-top: 16px; }}
h4 {{ color: {t['heading']}; font-size: 1.1em; font-weight: 600; }}
h5 {{ color: {t['heading']}; font-size: 1em; font-weight: 600; }}
h6 {{ color: {t['heading']}; font-size: 0.9em; font-weight: 600; }}
a {{ color: {t['link']}; text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
code {{ font-family: 'JetBrains Mono', 'Consolas', 'Courier New', monospace; font-size: 0.9em; }}
code.md-inline-code {{
    background-color: {t['inline_code_bg']};
    padding: 2px 6px;
    border-radius: 4px;
    color: {t['code_text']};
}}
.md-code-block {{
    background-color: {t['code_bg']};
    border: 1px solid {t['hr']};
    border-radius: 8px;
    padding: 12px 16px;
    margin: 12px 0;
    overflow-x: auto;
}}
.md-code-block pre {{
    margin: 0;
    background: transparent;
}}
.md-code-block pre code {{
    color: {t['code_text']};
    background: transparent;
    padding: 0;
    white-space: pre-wrap;
    word-break: break-word;
}}
.md-lang-label {{
    display: inline-block;
    color: #A78BFA;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.5px;
    margin-bottom: 8px;
    text-transform: uppercase;
}}
blockquote {{
    margin: 12px 0;
    padding: 8px 16px;
    background-color: {t['blockquote_bg']};
    border-left: 4px solid {t['blockquote_border']};
    border-radius: 4px;
    color: {t['text']};
}}
hr.md-hr {{
    border: none;
    border-top: 1px solid {t['hr']};
    margin: 20px 0;
}}
.md-table {{
    border-collapse: collapse;
    width: auto;
    margin: 12px 0;
    font-size: 13px;
}}
.md-table th {{
    background-color: {t['table_bg']};
    color: {t['heading']};
    font-weight: 600;
    padding: 8px 12px;
    border: 1px solid {t['table_border']};
}}
.md-table td {{
    padding: 6px 12px;
    border: 1px solid {t['table_border']};
}}
.md-table tr:nth-child(even) {{
    background-color: {t['table_alt_bg']};
}}
img.md-image {{
    max-width: 100%;
    border-radius: 8px;
    margin: 12px 0;
}}
ul, ol {{
    padding-left: 24px;
    margin: 8px 0;
}}
li {{
    margin: 4px 0;
}}
p {{
    margin: 8px 0;
}}
</style>
</head>
<body>
{html_body}
</body>
</html>"""
    return full_html


# ──────────────────────────────────────────────────────────────
# MarkdownViewer — renders markdown using QTextBrowser
# ──────────────────────────────────────────────────────────────


class MarkdownViewer(QWidget):
    """A read-only markdown preview panel using QTextBrowser to render HTML."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._theme = "dark"
        self._markdown_text = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(True)
        self.browser.setOpenLinks(True)
        self.browser.setReadOnly(True)
        self.browser.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.browser.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        layout.addWidget(self.browser)

        self.apply_theme(self._theme)

    def apply_theme(self, theme: str):
        self._theme = theme if theme in MD_THEMES else "dark"
        t = MD_THEMES[self._theme]
        self.browser.setStyleSheet(f"""
            QTextBrowser {{
                background-color: {t['bg']};
                color: {t['text']};
                border: none;
                padding: 0px;
            }}
        """)
        # Re-render if we have content
        if self._markdown_text:
            self.set_markdown(self._markdown_text)

    def set_markdown(self, md_text: str):
        """Parse markdown and render as HTML."""
        self._markdown_text = md_text
        html = _md_to_html(md_text, self._theme)
        self.browser.setHtml(html)

    def clear(self):
        self._markdown_text = ""
        self.browser.clear()


# ──────────────────────────────────────────────────────────────
# MarkdownModeBar — Edit | Preview | Both toggle bar
# ──────────────────────────────────────────────────────────────


class MarkdownModeBar(QFrame):
    """Toggle bar for switching between Edit, Preview, and Both (split) modes."""

    modeChanged = Signal(str)  # "edit", "preview", "both"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._active_mode = "both"
        self.setFixedHeight(32)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 2, 8, 2)
        layout.setSpacing(4)

        self.edit_btn = QPushButton("✏️  Edit")
        self.edit_btn.setCheckable(True)
        self.edit_btn.setToolTip("Show raw markdown editor only")
        self.edit_btn.clicked.connect(lambda: self._set_mode("edit"))

        self.preview_btn = QPushButton("👁️  Preview")
        self.preview_btn.setCheckable(True)
        self.preview_btn.setToolTip("Show rendered preview only")
        self.preview_btn.clicked.connect(lambda: self._set_mode("preview"))

        self.both_btn = QPushButton("⇔  Both")
        self.both_btn.setCheckable(True)
        self.both_btn.setChecked(True)
        self.both_btn.setToolTip("Show split view: editor + preview")
        self.both_btn.clicked.connect(lambda: self._set_mode("both"))

        for btn in (self.edit_btn, self.preview_btn, self.both_btn):
            btn.setStyleSheet("""
                QPushButton {
                    background: #161A26;
                    color: #8B94A7;
                    border: 1px solid #252B3D;
                    border-radius: 6px;
                    padding: 2px 12px;
                    font-size: 11px;
                    font-weight: 600;
                }
                QPushButton:hover {
                    background: #252B3D;
                    color: #E2E8F0;
                }
                QPushButton:checked {
                    background: #1E2333;
                    color: #00E5FF;
                    border: 1px solid #3A4466;
                }
            """)
            layout.addWidget(btn)

        layout.addStretch()

        # Theme-aware styling
        self.setStyleSheet("""
            MarkdownModeBar {
                background: #0F111A;
                border-bottom: 1px solid #1E2333;
            }
        """)

    def _set_mode(self, mode: str):
        self._active_mode = mode
        self.edit_btn.setChecked(mode == "edit")
        self.preview_btn.setChecked(mode == "preview")
        self.both_btn.setChecked(mode == "both")
        self.modeChanged.emit(mode)

    def current_mode(self) -> str:
        return self._active_mode


# ──────────────────────────────────────────────────────────────
# MarkdownEditorPage — split-panel markdown editor
# ──────────────────────────────────────────────────────────────


class MarkdownEditorPage(QWidget):
    """A complete markdown editing page with Edit | Preview | Both modes,
    exactly like VS Code's built-in markdown editor."""

    fileSaved = Signal(Path)

    def __init__(self, file_path: Optional[Path] = None, parent=None):
        super().__init__(parent)
        self.file_path = file_path
        self._theme = "dark"
        self._mode = "both"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Mode toggle bar
        self.mode_bar = MarkdownModeBar()
        self.mode_bar.modeChanged.connect(self._on_mode_changed)
        layout.addWidget(self.mode_bar)

        # Split panel: editor (left) + preview (right)
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setHandleWidth(2)
        self.splitter.setChildrenCollapsible(True)

        # Code editor (raw markdown)
        self.editor = CodeEditor(file_path=file_path)
        self.editor.setLineWrapMode(CodeEditor.WidgetWidth)  # wrap text for markdown
        self.editor.textChanged.connect(self._on_editor_text_changed)

        # Markdown preview
        self.preview = MarkdownViewer()

        self.splitter.addWidget(self.editor)
        self.splitter.addWidget(self.preview)
        self.splitter.setSizes([400, 400])
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)

        layout.addWidget(self.splitter, stretch=1)

        # Update preview with initial content
        self._update_preview()

    def _on_mode_changed(self, mode: str):
        self._mode = mode
        if mode == "edit":
            self.editor.show()
            self.preview.hide()
        elif mode == "preview":
            self.editor.hide()
            self.preview.show()
        else:  # both
            self.editor.show()
            self.preview.show()

    def _on_editor_text_changed(self):
        self._update_preview()

    def _update_preview(self):
        text = self.editor.toPlainText()
        self.preview.set_markdown(text)

    def apply_theme(self, theme: str):
        self._theme = theme if theme in THEMES else "dark"
        self.editor.apply_theme(theme)
        self.preview.apply_theme(theme)

    @property
    def is_dirty(self):
        return self.editor.is_dirty

    def save(self, path: Optional[Path] = None):
        if path:
            self.file_path = path
            self.editor.file_path = path
        if self.file_path:
            self.file_path.write_text(self.editor.toPlainText(), encoding="utf-8")
            self.editor.mark_clean()
            self.fileSaved.emit(self.file_path)
