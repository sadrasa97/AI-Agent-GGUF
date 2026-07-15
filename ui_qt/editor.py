"""
VS-Code-style code editor: QPlainTextEdit + a gutter widget for line
numbers, wrapped in a QTabWidget so multiple files can be open at once.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QTextFormat
from PySide6.QtWidgets import (
    QPlainTextEdit, QTabWidget, QTextEdit, QWidget, QMessageBox, QFileDialog,
)

from ui_qt.syntax import CodeHighlighter

EDITOR_BG = "#1e1e1e"
EDITOR_FG = "#d4d4d4"
GUTTER_BG = "#1e1e1e"
GUTTER_FG = "#858585"
CURRENT_LINE_BG = QColor("#2a2d2e")


class LineNumberArea(QWidget):
    def __init__(self, editor: "CodeEditor"):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self) -> QSize:
        return QSize(self.editor.line_number_area_width(), 0)

    def paintEvent(self, event):
        self.editor.line_number_area_paint_event(event)


class CodeEditor(QPlainTextEdit):
    """A single editable file buffer."""

    def __init__(self, file_path: Optional[Path] = None, parent=None):
        super().__init__(parent)
        self.file_path = file_path
        self.is_dirty = False

        font = QFont("JetBrains Mono, Consolas, Menlo, monospace")
        font.setStyleHint(QFont.Monospace)
        font.setFixedPitch(True)
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

        self.setStyleSheet(
            f"QPlainTextEdit {{ background-color: {EDITOR_BG}; color: {EDITOR_FG}; "
            f"border: none; selection-background-color: #264F78; }}"
        )
        self.textChanged.connect(self._mark_dirty)

    # -- dirty tracking -------------------------------------------------
    def _mark_dirty(self):
        self.is_dirty = True

    def mark_clean(self):
        self.is_dirty = False

    # -- gutter -----------------------------------------------------------
    def line_number_area_width(self) -> int:
        digits = len(str(max(1, self.blockCount())))
        return 12 + self.fontMetrics().horizontalAdvance("9") * digits

    def _update_line_area_width(self, _new_block_count):
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def _update_line_area(self, rect: QRect, dy: int):
        if dy:
            self._line_area.scroll(0, dy)
        else:
            self._line_area.update(0, rect.y(), self._line_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_line_area_width(0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._line_area.setGeometry(QRect(cr.left(), cr.top(), self.line_number_area_width(), cr.height()))

    def line_number_area_paint_event(self, event):
        painter = QPainter(self._line_area)
        painter.fillRect(event.rect(), QColor(GUTTER_BG))

        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = int(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + int(self.blockBoundingRect(block).height())

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                number = str(block_number + 1)
                painter.setPen(QColor(GUTTER_FG))
                painter.drawText(
                    0, top, self._line_area.width() - 6, self.fontMetrics().height(),
                    Qt.AlignRight, number,
                )
            block = block.next()
            top = bottom
            bottom = top + int(self.blockBoundingRect(block).height())
            block_number += 1

    def _highlight_current_line(self):
        extra_selections = []
        if not self.isReadOnly():
            sel = QTextEdit.ExtraSelection()
            sel.format.setBackground(CURRENT_LINE_BG)
            sel.format.setProperty(QTextFormat.FullWidthSelection, True)
            sel.cursor = self.textCursor()
            sel.cursor.clearSelection()
            extra_selections.append(sel)
        self.setExtraSelections(extra_selections)


class EditorTabs(QTabWidget):
    """Container for multiple open CodeEditor buffers."""

    fileSaved = Signal(Path)
    activeFileChanged = Signal(object)  # Path or None

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTabsClosable(True)
        self.setMovable(True)
        self.setDocumentMode(True)
        self.tabCloseRequested.connect(self._close_tab)
        self.currentChanged.connect(self._on_current_changed)
        self._untitled_count = 0

    # ------------------------------------------------------------------
    def open_file(self, path: Path):
        path = Path(path)
        for i in range(self.count()):
            editor = self.widget(i)
            if editor.file_path == path:
                self.setCurrentIndex(i)
                return
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Could not open {path}:\n{exc}")
            return
        editor = CodeEditor(file_path=path)
        editor.setPlainText(text)
        editor.mark_clean()
        idx = self.addTab(editor, path.name)
        self.setCurrentIndex(idx)
        self.setTabToolTip(idx, str(path))

    def new_untitled(self, template_code: str = "", language: str = "py"):
        self._untitled_count += 1
        editor = CodeEditor(file_path=None)
        editor.highlighter.set_extension(language)
        editor.setPlainText(template_code)
        editor.mark_clean() if not template_code else None
        title = f"Untitled-{self._untitled_count}"
        idx = self.addTab(editor, title)
        self.setCurrentIndex(idx)
        return editor

    def current_editor(self) -> Optional[CodeEditor]:
        return self.currentWidget()

    def save_current(self, save_as: bool = False):
        editor = self.current_editor()
        if editor is None:
            return
        path = editor.file_path
        if path is None or save_as:
            start_dir = str(path.parent) if path else ""
            filename, _ = QFileDialog.getSaveFileName(self, "Save File", start_dir)
            if not filename:
                return
            path = Path(filename)
            editor.file_path = path
            editor.highlighter.set_extension(path.suffix.lstrip("."))
        try:
            path.write_text(editor.toPlainText(), encoding="utf-8")
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Could not save {path}:\n{exc}")
            return
        editor.mark_clean()
        idx = self.indexOf(editor)
        self.setTabText(idx, path.name)
        self.setTabToolTip(idx, str(path))
        self.fileSaved.emit(path)

    def _close_tab(self, index: int):
        editor = self.widget(index)
        if editor.is_dirty:
            name = self.tabText(index).rstrip("*")
            resp = QMessageBox.question(
                self, "Unsaved changes",
                f"Save changes to {name} before closing?",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
            )
            if resp == QMessageBox.Cancel:
                return
            if resp == QMessageBox.Yes:
                self.setCurrentIndex(index)
                self.save_current()
        self.removeTab(index)

    def _on_current_changed(self, index: int):
        editor = self.widget(index) if index >= 0 else None
        self.activeFileChanged.emit(editor.file_path if editor else None)

    def mark_tab_dirty_titles(self):
        """Call periodically (or on textChanged) to add '*' to dirty tab titles."""
        for i in range(self.count()):
            editor = self.widget(i)
            base = self.tabText(i).rstrip("*")
            self.setTabText(i, base + ("*" if editor.is_dirty else ""))
