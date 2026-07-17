"""VS-Code-style code editor."""
from __future__ import annotations
import ast
import json
from pathlib import Path
from typing import Optional
from PySide6.QtCore import QRect, QSize, Qt, Signal, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QTextFormat, QTextCursor, QTextDocument, QKeySequence, QTextCharFormat
from PySide6.QtWidgets import (
    QPlainTextEdit, QTabWidget, QTabBar, QTextEdit, QWidget, QMessageBox, QFileDialog,
    QHBoxLayout, QVBoxLayout, QLineEdit, QPushButton, QLabel, QFrame, QSizePolicy, QToolButton,
)
from ui_qt.syntax import CodeHighlighter

THEMES = {
    "dark": {
        "editor_bg": "#0B0D14", "editor_fg": "#E2E8F0",
        "gutter_bg": "#0F111A", "gutter_fg": "#5A647D",
        "current_line_bg": QColor("#131620"), "selection_bg": "#252B3D",
        "error_bg": QColor("#2D1115"), "error_underline": QColor("#FF2E63"),
        "find_bar_style": """
            QFrame#findBar { background:#0F111A; border-bottom:1px solid #1E2333; }
            QLineEdit { background:#161A26; color:#E2E8F0; border:1px solid #252B3D; border-radius:6px; padding:4px 8px; }
            QLineEdit:focus { border:1px solid #00E5FF; }
            QPushButton#toolBtn { background:#161A26; color:#8B94A7; border:1px solid #252B3D; border-radius:6px; padding:3px 8px; }
            QPushButton#toolBtn:hover { background:#252B3D; color:#E2E8F0; }
            QPushButton#toolBtn:checked { background:#1E2333; color:#00E5FF; border:1px solid #3A4466; }
            QLabel#matchLabel { color:#5A647D; font-size:11px; padding:0 6px; }
        """,
        "tabs_style": """
            QTabWidget::pane { border: none; background: #0B0D14; top: -1px; }
            QTabBar { qproperty-drawBase: 0; }
            QTabBar::tab { background: #0F111A; color: #8B94A7; padding: 10px 24px 10px 16px; margin-right: 2px; border: none; border-bottom: 2px solid transparent; font-size: 12px; font-weight: 600; }
            QTabBar::tab:selected { background: #0B0D14; color: #E2E8F0; border-bottom: 2px solid #00E5FF; }
            QTabBar::tab:hover:!selected { background: #131620; color: #E2E8F0; }
        """,
        "tab_close_btn": "QToolButton { color:#5A647D; background: transparent; border: none; padding: 0px; border-radius: 4px; } QToolButton:hover { color:#E2E8F0; background:#252B3D; }",
    },
    "light": {
        "editor_bg": "#FFFFFF", "editor_fg": "#1F2937",
        "gutter_bg": "#F8F9FA", "gutter_fg": "#9CA3AF",
        "current_line_bg": QColor("#F3F4F6"), "selection_bg": "#DBEAFE",
        "error_bg": QColor("#FEE2E2"), "error_underline": QColor("#EF4444"),
        "find_bar_style": """
            QFrame#findBar { background:#F8F9FA; border-bottom:1px solid #E5E7EB; }
            QLineEdit { background:#FFFFFF; color:#1F2937; border:1px solid #E5E7EB; border-radius:6px; padding:4px 8px; }
            QLineEdit:focus { border:1px solid #2563EB; }
            QPushButton#toolBtn { background:#FFFFFF; color:#6B7280; border:1px solid #E5E7EB; border-radius:6px; padding:3px 8px; }
            QPushButton#toolBtn:hover { background:#F3F4F6; color:#111827; }
            QPushButton#toolBtn:checked { background:#EFF6FF; color:#2563EB; border:1px solid #BFDBFE; }
            QLabel#matchLabel { color:#6B7280; font-size:11px; padding:0 6px; }
        """,
        "tabs_style": """
            QTabWidget::pane { border: none; background: #FFFFFF; top: -1px; }
            QTabBar { qproperty-drawBase: 0; }
            QTabBar::tab { background: #F8F9FA; color: #6B7280; padding: 10px 24px 10px 16px; margin-right: 2px; border: none; border-bottom: 2px solid transparent; font-size: 12px; font-weight: 600; }
            QTabBar::tab:selected { background: #FFFFFF; color: #111827; border-bottom: 2px solid #2563EB; }
            QTabBar::tab:hover:!selected { background: #F3F4F6; color: #111827; }
        """,
        "tab_close_btn": "QToolButton { color:#9CA3AF; background: transparent; border: none; padding: 0px; border-radius: 4px; } QToolButton:hover { color:#111827; background:#E5E7EB; }",
    }
}

class LineNumberArea(QWidget):
    def __init__(self, editor: "CodeEditor", parent=None):
        super().__init__(parent)
        self.editor = editor
    def sizeHint(self) -> QSize: return QSize(self.editor.line_number_area_width(), 0)
    def paintEvent(self, event): self.editor.line_number_area_paint_event(event)

class CodeEditor(QPlainTextEdit):
    findRequested = Signal()
    replaceRequested = Signal()

    def __init__(self, file_path: Optional[Path] = None, parent=None):
        super().__init__(parent)
        self.file_path = file_path
        self.is_dirty = False
        self.theme = "dark"
        self._error_selections: list[QTextEdit.ExtraSelection] = []
        font = QFont("JetBrains Mono, Consolas, Menlo, monospace")
        font.setPointSize(11)
        self.setFont(font)
        self.setTabStopDistance(4 * self.fontMetrics().horizontalAdvance(" "))
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self._line_area = LineNumberArea(self)
        self.blockCountChanged.connect(self._update_line_area_width)
        self.updateRequest.connect(self._update_line_area)
        self.cursorPositionChanged.connect(self._highlight_current_line)
        self._update_line_area_width(0)
        self._highlight_current_line()
        ext = file_path.suffix.lstrip(".") if file_path else "py"
        self.highlighter = CodeHighlighter(self.document(), ext)
        self._diagnostic_timer = QTimer(self)
        self._diagnostic_timer.setSingleShot(True)
        self._diagnostic_timer.setInterval(550)
        self._diagnostic_timer.timeout.connect(self._run_diagnostics)
        self.apply_theme("dark")
        self.textChanged.connect(self._mark_dirty)
        self.textChanged.connect(self._queue_diagnostics)

    def _mark_dirty(self): self.is_dirty = True
    def mark_clean(self): self.is_dirty = False
    def line_number_area_width(self) -> int:
        digits = len(str(max(1, self.blockCount())))
        return 16 + self.fontMetrics().horizontalAdvance("9") * digits
    def _update_line_area_width(self, _new_block_count): self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)
    def _update_line_area(self, rect: QRect, dy: int):
        if dy: self._line_area.scroll(0, dy)
        else: self._line_area.update(0, rect.y(), self._line_area.width(), rect.height())
        if rect.contains(self.viewport().rect()): self._update_line_area_width(0)
    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._line_area.setGeometry(QRect(cr.left(), cr.top(), self.line_number_area_width(), cr.height()))
    def line_number_area_paint_event(self, event):
        painter = QPainter(self._line_area)
        painter.fillRect(event.rect(), QColor(THEMES[self.theme]["gutter_bg"]))
        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = int(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + int(self.blockBoundingRect(block).height())
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                number = str(block_number + 1)
                painter.setPen(QColor(THEMES[self.theme]["gutter_fg"]))
                painter.drawText(0, top, self._line_area.width() - 8, self.fontMetrics().height(), Qt.AlignRight, number)
            block = block.next()
            top = bottom
            bottom = top + int(self.blockBoundingRect(block).height())
            block_number += 1
    def _highlight_current_line(self):
        extra_selections = []
        if not self.isReadOnly():
            sel = QTextEdit.ExtraSelection()
            sel.format.setBackground(THEMES[self.theme]["current_line_bg"])
            sel.format.setProperty(QTextFormat.FullWidthSelection, True)
            sel.cursor = self.textCursor()
            sel.cursor.clearSelection()
            extra_selections.append(sel)
        self.setExtraSelections(extra_selections + self._error_selections)
    def apply_theme(self, theme: str):
        self.theme = theme if theme in THEMES else "dark"
        spec = THEMES[self.theme]
        self.setStyleSheet(f"QPlainTextEdit {{ background-color: {spec['editor_bg']}; color: {spec['editor_fg']}; border: none; selection-background-color: {spec['selection_bg']}; }}")
        self._line_area.update()
        self._highlight_current_line()
    def _queue_diagnostics(self): self._diagnostic_timer.start()
    def _run_diagnostics(self):
        ext = (self.file_path.suffix.lstrip(".") if self.file_path else self.highlighter.extension).lower()
        text = self.toPlainText()
        errors: list[tuple[int, str]] = []
        if ext == "py":
            try: ast.parse(text or "\n")
            except SyntaxError as exc:
                if exc.lineno: errors.append((exc.lineno, exc.msg or "Syntax error"))
        elif ext == "json":
            try: json.loads(text or "{}")
            except json.JSONDecodeError as exc: errors.append((max(1, exc.lineno), exc.msg))
        new_selections: list[QTextEdit.ExtraSelection] = []
        for line_number, message in errors:
            block = self.document().findBlockByNumber(line_number - 1)
            if not block.isValid(): continue
            cursor = QTextCursor(block); cursor.select(QTextCursor.LineUnderCursor)
            sel = QTextEdit.ExtraSelection(); sel.cursor = cursor
            sel.format.setBackground(THEMES[self.theme]["error_bg"])
            sel.format.setUnderlineColor(THEMES[self.theme]["error_underline"])
            sel.format.setUnderlineStyle(QTextCharFormat.WaveUnderline)
            sel.format.setToolTip(message)
            new_selections.append(sel)
        self._error_selections = new_selections
        self._highlight_current_line()
    def keyPressEvent(self, event):
        if event.matches(QKeySequence.Find): self.findRequested.emit(); event.accept(); return
        if event.matches(QKeySequence.Replace): self.replaceRequested.emit(); event.accept(); return
        super().keyPressEvent(event)

class FindReplaceBar(QFrame):
    def __init__(self, editor: "CodeEditor", parent=None):
        super().__init__(parent)
        self.editor = editor
        self.setObjectName("findBar")
        self.apply_theme("dark")
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(4)
        find_row = QHBoxLayout()
        find_row.setSpacing(4)
        self.find_edit = QLineEdit()
        self.find_edit.setPlaceholderText("Find")
        self.find_edit.textChanged.connect(self._on_find_text_changed)
        self.find_edit.returnPressed.connect(self.find_next)
        find_row.addWidget(self.find_edit, 1)
        self.match_label = QLabel("")
        self.match_label.setObjectName("matchLabel")
        find_row.addWidget(self.match_label)
        self.case_btn = QPushButton("Aa")
        self.case_btn.setObjectName("toolBtn")
        self.case_btn.setCheckable(True)
        self.case_btn.setToolTip("Match Case")
        self.case_btn.toggled.connect(lambda _c: self._on_find_text_changed())
        find_row.addWidget(self.case_btn)
        self.word_btn = QPushButton("ab")
        self.word_btn.setObjectName("toolBtn")
        self.word_btn.setCheckable(True)
        self.word_btn.setToolTip("Match Whole Word")
        self.word_btn.toggled.connect(lambda _c: self._on_find_text_changed())
        find_row.addWidget(self.word_btn)
        prev_btn = QPushButton("˄")
        prev_btn.setObjectName("toolBtn")
        prev_btn.setToolTip("Previous Match (Shift+Enter)")
        prev_btn.clicked.connect(self.find_prev)
        find_row.addWidget(prev_btn)
        next_btn = QPushButton("˅")
        next_btn.setObjectName("toolBtn")
        next_btn.setToolTip("Next Match (Enter)")
        next_btn.clicked.connect(self.find_next)
        find_row.addWidget(next_btn)
        self.toggle_replace_btn = QPushButton("⋯")
        self.toggle_replace_btn.setObjectName("toolBtn")
        self.toggle_replace_btn.setCheckable(True)
        self.toggle_replace_btn.setToolTip("Toggle Replace (Ctrl+H)")
        self.toggle_replace_btn.toggled.connect(self._on_toggle_replace)
        find_row.addWidget(self.toggle_replace_btn)
        close_btn = QPushButton("✕")
        close_btn.setObjectName("toolBtn")
        close_btn.setToolTip("Close (Esc)")
        close_btn.clicked.connect(self.hide_bar)
        find_row.addWidget(close_btn)
        root.addLayout(find_row)
        self.replace_widget = QWidget()
        replace_row = QHBoxLayout(self.replace_widget)
        replace_row.setContentsMargins(0, 0, 0, 0)
        replace_row.setSpacing(4)
        self.replace_edit = QLineEdit()
        self.replace_edit.setPlaceholderText("Replace")
        self.replace_edit.returnPressed.connect(self.replace_one)
        replace_row.addWidget(self.replace_edit, 1)
        replace_btn = QPushButton("Replace")
        replace_btn.setObjectName("toolBtn")
        replace_btn.clicked.connect(self.replace_one)
        replace_row.addWidget(replace_btn)
        replace_all_btn = QPushButton("Replace All")
        replace_all_btn.setObjectName("toolBtn")
        replace_all_btn.clicked.connect(self.replace_all)
        replace_row.addWidget(replace_all_btn)
        self.replace_widget.setVisible(False)
        root.addWidget(self.replace_widget)
        self.hide()

    def apply_theme(self, theme: str):
        theme_key = theme if theme in THEMES else "dark"
        self.setStyleSheet(THEMES[theme_key]["find_bar_style"])

    def show_bar(self, with_replace: bool = False):
        selected = self.editor.textCursor().selectedText()
        if selected and "\u2029" not in selected: self.find_edit.setText(selected)
        self.show()
        if with_replace: self.toggle_replace_btn.setChecked(True)
        self.find_edit.setFocus(); self.find_edit.selectAll(); self._on_find_text_changed()

    def hide_bar(self): self.hide(); self.editor.setFocus()
    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape: self.hide_bar(); return
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and event.modifiers() & Qt.ShiftModifier: self.find_prev(); return
        super().keyPressEvent(event)
    def _on_toggle_replace(self, checked: bool):
        self.replace_widget.setVisible(checked)
        if checked: self.replace_edit.setFocus()
    def _flags(self, backward: bool = False) -> QTextDocument.FindFlag:
        flags = QTextDocument.FindFlags()
        if self.case_btn.isChecked(): flags |= QTextDocument.FindCaseSensitively
        if self.word_btn.isChecked(): flags |= QTextDocument.FindWholeWords
        if backward: flags |= QTextDocument.FindBackward
        return flags
    def _match_count(self, text: str) -> int:
        if not text: return 0
        haystack = self.editor.toPlainText()
        if not self.case_btn.isChecked(): haystack, text = haystack.lower(), text.lower()
        return haystack.count(text)
    def _update_match_label(self, found: bool):
        text = self.find_edit.text()
        if not text: self.match_label.setText(""); return
        total = self._match_count(text)
        self.match_label.setText("No results" if total == 0 else f"{total} match" + ("es" if total != 1 else ""))
        self.find_edit.setStyleSheet("" if (found or total > 0) else "QLineEdit { border:1px solid #FF2E63; }")
    def _on_find_text_changed(self):
        text = self.find_edit.text()
        if not text: self.match_label.setText(""); return
        cursor = self.editor.textCursor(); cursor.movePosition(QTextCursor.Start); self.editor.setTextCursor(cursor)
        found = self.editor.find(text, self._flags()); self._update_match_label(found)
    def find_next(self):
        text = self.find_edit.text()
        if not text: return
        found = self.editor.find(text, self._flags())
        if not found:
            cursor = self.editor.textCursor(); cursor.movePosition(QTextCursor.Start); self.editor.setTextCursor(cursor)
            found = self.editor.find(text, self._flags())
        self._update_match_label(found)
    def find_prev(self):
        text = self.find_edit.text()
        if not text: return
        found = self.editor.find(text, self._flags(backward=True))
        if not found:
            cursor = self.editor.textCursor(); cursor.movePosition(QTextCursor.End); self.editor.setTextCursor(cursor)
            found = self.editor.find(text, self._flags(backward=True))
        self._update_match_label(found)
    def replace_one(self):
        text = self.find_edit.text()
        if not text: return
        cursor = self.editor.textCursor(); selected = cursor.selectedText()
        is_match = selected == text if self.case_btn.isChecked() else selected.lower() == text.lower()
        if cursor.hasSelectedText() and is_match: cursor.insertText(self.replace_edit.text()); self.editor.setTextCursor(cursor)
        self.find_next()
    def replace_all(self):
        text = self.find_edit.text()
        if not text: return
        replacement = self.replace_edit.text(); flags = self._flags()
        document = self.editor.document(); edit_cursor = QTextCursor(document); edit_cursor.beginEditBlock()
        count = 0; pos = 0
        while True:
            found_cursor = document.find(text, pos, flags)
            if found_cursor.isNull(): break
            found_cursor.insertText(replacement); pos = found_cursor.position(); count += 1
        edit_cursor.endEditBlock()
        self.match_label.setText(f"Replaced {count} occurrence" + ("s" if count != 1 else ""))

class EditorPage(QWidget):
    def __init__(self, editor: CodeEditor, parent=None):
        super().__init__(parent)
        self.editor = editor
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.find_bar = FindReplaceBar(editor)
        layout.addWidget(self.find_bar)
        layout.addWidget(editor)
        editor.findRequested.connect(lambda: self.find_bar.show_bar(with_replace=False))
        editor.replaceRequested.connect(lambda: self.find_bar.show_bar(with_replace=True))

    @property
    def file_path(self): return self.editor.file_path
    @property
    def is_dirty(self): return self.editor.is_dirty

class EditorTabs(QTabWidget):
    fileSaved = Signal(Path)
    activeFileChanged = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTabsClosable(True); self.setMovable(True); self.setDocumentMode(True); self.setElideMode(Qt.ElideRight)
        self.tabCloseRequested.connect(self._close_tab)
        self.currentChanged.connect(self._on_current_changed)
        self._untitled_count = 0; self.theme = "dark"
        self.apply_theme("dark")

    def open_file(self, path: Path):
        path = Path(path)
        for i in range(self.count()):
            page = self.widget(i)
            if page.editor.file_path == path: self.setCurrentIndex(i); return
        try: text = path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc: QMessageBox.critical(self, "Error", f"Could not open {path}:\n{exc}"); return
        editor = CodeEditor(file_path=path)
        editor.setPlainText(text); editor.mark_clean()
        page = EditorPage(editor)
        idx = self.addTab(page, path.name)
        self._install_close_button(idx)
        self.setCurrentIndex(idx)
        self.setTabToolTip(idx, str(path))
        page.find_bar.apply_theme(self.theme); page.editor.apply_theme(self.theme)

    def new_untitled(self, template_code: str = "", language: str = "py"):
        self._untitled_count += 1
        editor = CodeEditor(file_path=None)
        editor.highlighter.set_extension(language)
        editor.setPlainText(template_code)
        if not template_code: editor.mark_clean()
        page = EditorPage(editor)
        title = f"Untitled-{self._untitled_count}"
        idx = self.addTab(page, title)
        self._install_close_button(idx)
        self.setCurrentIndex(idx)
        page.find_bar.apply_theme(self.theme); page.editor.apply_theme(self.theme)
        return editor

    def current_editor(self) -> Optional[CodeEditor]:
        page = self.currentWidget()
        return page.editor if page is not None else None

    def save_current(self, save_as: bool = False):
        editor = self.current_editor()
        if editor is None: return
        page = self.currentWidget(); path = editor.file_path
        if path is None or save_as:
            start_dir = str(path.parent) if path else ""
            filename, _ = QFileDialog.getSaveFileName(self, "Save File", start_dir)
            if not filename: return
            path = Path(filename); editor.file_path = path; editor.highlighter.set_extension(path.suffix.lstrip("."))
        try: path.write_text(editor.toPlainText(), encoding="utf-8")
        except Exception as exc: QMessageBox.critical(self, "Error", f"Could not save {path}:\n{exc}"); return
        editor.mark_clean()
        idx = self.indexOf(page)
        self.setTabText(idx, path.name); self.setTabToolTip(idx, str(path))
        self.fileSaved.emit(path)

    def _close_tab(self, index: int):
        if index < 0 or index >= self.count(): return
        page = self.widget(index); editor = page.editor
        if editor.is_dirty:
            name = self.tabText(index).rstrip("*")
            resp = QMessageBox.question(self, "Unsaved changes", f"Save changes to {name} before closing?", QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
            if resp == QMessageBox.Cancel: return
            if resp == QMessageBox.Yes: self.setCurrentIndex(index); self.save_current()
        self.removeTab(index)

    def _on_current_changed(self, index: int):
        page = self.widget(index) if index >= 0 else None
        self.activeFileChanged.emit(page.editor.file_path if page else None)

    def apply_theme(self, theme: str):
        self.theme = theme if theme in THEMES else "dark"
        spec = THEMES[self.theme]
        self.setStyleSheet(spec["tabs_style"])
        for i in range(self.count()):
            page = self.widget(i)
            page.editor.apply_theme(self.theme); page.find_bar.apply_theme(self.theme)
            self._install_close_button(i)

    def _install_close_button(self, index: int):
        btn = QToolButton(self)
        btn.setText("×"); btn.setAutoRaise(True); btn.setCursor(Qt.ArrowCursor); btn.setFixedSize(16, 16)
        btn.setStyleSheet(THEMES[self.theme]["tab_close_btn"])
        btn.clicked.connect(lambda _=False, b=btn: self._close_tab(self._index_for_close_button(b)))
        self.tabBar().setTabButton(index, QTabBar.ButtonPosition.RightSide, btn)

    def _index_for_close_button(self, button: QToolButton) -> int:
        tab_bar = self.tabBar()
        for i in range(self.count()):
            if tab_bar.tabButton(i, QTabBar.ButtonPosition.RightSide) is button: return i
        return -1

    def mark_tab_dirty_titles(self):
        for i in range(self.count()):
            page = self.widget(i)
            base = self.tabText(i).rstrip("*")
            self.setTabText(i, base + ("*" if page.editor.is_dirty else ""))