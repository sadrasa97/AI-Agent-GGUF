"""Workspace file-tree explorer with VS Code-like tree interactions."""
from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtCore import QDir, QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QAction, QColor, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QFileSystemModel,
    QInputDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QStyledItemDelegate,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

IGNORED_DIRS = {"__pycache__", ".git", "node_modules", ".venv", "venv", "dist", "build"}


def _workspace_header_text(workspace: Path) -> str:
    if workspace.name == "__no_project__":
        return "NO FOLDER OPENED"
    return workspace.name.upper() or "WORKSPACE"

class FileExplorer(QWidget):
    fileActivated = Signal(Path)
    runRequested = Signal(Path)
    newFileRequested = Signal(Path)
    newFolderRequested = Signal(Path)

    class _ExplorerProxyModel(QSortFilterProxyModel):
        def __init__(self, parent=None):
            super().__init__(parent)
            self._workspace: Path | None = None

        def set_workspace(self, workspace: Path):
            self._workspace = Path(workspace)
            self.invalidateFilter()

        def filterAcceptsRow(self, source_row, source_parent):
            model = self.sourceModel()
            if model is None:
                return False
            idx = model.index(source_row, 0, source_parent)
            if not idx.isValid():
                return False
            path = Path(model.filePath(idx))

            # Keep workspace root visible and hide noisy build/cache dirs.
            if path.name in IGNORED_DIRS and path.is_dir():
                return False
            return True

    class _LineCountCache:
        def __init__(self):
            # path -> (mtime_ns, size, line_count)
            self._disk_cache: dict[Path, tuple[int, int, int]] = {}
            # path -> (line_count, dirty)
            self._live_counts: dict[Path, tuple[int, bool]] = {}

        def set_live(self, path: Path, line_count: int, dirty: bool):
            self._live_counts[Path(path)] = (max(0, int(line_count)), bool(dirty))

        def get_live(self, path: Path) -> tuple[int, bool] | None:
            return self._live_counts.get(Path(path))

        def clear_live(self, path: Path):
            self._live_counts.pop(Path(path), None)

        def line_count(self, path: Path) -> int | None:
            path = Path(path)
            live = self.get_live(path)
            if live is not None:
                return live[0]
            if not path.is_file() or self._is_binary(path):
                return None
            try:
                stat = path.stat()
            except OSError:
                return None
            cached = self._disk_cache.get(path)
            fingerprint = (stat.st_mtime_ns, stat.st_size)
            if cached and cached[0] == fingerprint[0] and cached[1] == fingerprint[1]:
                return cached[2]
            count = self._count_lines(path)
            if count is None:
                return None
            self._disk_cache[path] = (fingerprint[0], fingerprint[1], count)
            return count

        def invalidate(self, path: Path):
            self._disk_cache.pop(Path(path), None)

        @staticmethod
        def _is_binary(path: Path) -> bool:
            try:
                with path.open("rb") as f:
                    chunk = f.read(8192)
            except OSError:
                return True
            return b"\x00" in chunk

        @staticmethod
        def _count_lines(path: Path) -> int | None:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                return None
            if not text:
                return 0
            return text.count("\n") + 1

    class _ExplorerDelegate(QStyledItemDelegate):
        def __init__(self, host: "FileExplorer"):
            super().__init__(host)
            self.host = host

        def paint(self, painter: QPainter, option, index):
            super().paint(painter, option, index)
            path = self.host._path_from_proxy_index(index)
            if path is None or path.is_dir():
                return

            line_count = self.host._line_counts.line_count(path)
            if line_count is None:
                return

            live = self.host._line_counts.get_live(path)
            is_dirty = bool(live[1]) if live is not None else False
            suffix = "*" if is_dirty else ""
            label = f"{line_count}{suffix}"

            painter.save()
            painter.setPen(QColor("#8B949E"))
            right_rect = option.rect.adjusted(0, 0, -10, 0)
            painter.drawText(right_rect, Qt.AlignVCenter | Qt.AlignRight, label)
            painter.restore()

    def __init__(self, workspace: Path, parent=None):
        super().__init__(parent)
        self.workspace = Path(workspace)
        self._theme = "dark"
        self._expanded_paths: set[str] = set()
        self._line_counts = self._LineCountCache()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.header = QLabel(_workspace_header_text(self.workspace))
        layout.addWidget(self.header)

        self.model = QFileSystemModel()
        self.model.setFilter(QDir.AllEntries | QDir.NoDotAndDotDot)
        self.model.setRootPath(str(self.workspace))

        self.proxy = self._ExplorerProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.set_workspace(self.workspace)

        self.tree = QTreeView()
        self.tree.setModel(self.proxy)
        self.tree.setRootIndex(self.proxy.mapFromSource(self.model.index(str(self.workspace))))
        self.tree.setHeaderHidden(True)
        self.tree.setAnimated(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setIndentation(14)
        self.tree.setExpandsOnDoubleClick(True)
        self.tree.setItemsExpandable(True)
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.tree.setVerticalScrollMode(QTreeView.ScrollPerPixel)
        self.tree.setAllColumnsShowFocus(True)
        self.tree.setSelectionBehavior(QTreeView.SelectRows)

        self.tree.setItemDelegate(self._ExplorerDelegate(self))
        for col in (1, 2, 3): self.tree.hideColumn(col)

        self.tree.doubleClicked.connect(self._on_double_click)
        self.tree.expanded.connect(self._on_expanded)
        self.tree.collapsed.connect(self._on_collapsed)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._context_menu)
        layout.addWidget(self.tree)

        self.apply_theme(self._theme)

    def set_workspace(self, workspace: Path):
        self.workspace = Path(workspace)
        self.model.setRootPath(str(self.workspace))
        self.proxy.set_workspace(self.workspace)
        self.tree.setRootIndex(self.proxy.mapFromSource(self.model.index(str(self.workspace))))
        self.header.setText(_workspace_header_text(self.workspace))
        self._expanded_paths.clear()

    def refresh(self):
        self.model.setRootPath(str(self.workspace))
        self.tree.setRootIndex(self.proxy.mapFromSource(self.model.index(str(self.workspace))))
        self._restore_expanded_paths()

    def apply_theme(self, theme: str):
        self._theme = "dark"
        header_style = "background:#252526; color:#BBBBBB; padding:8px 10px; font-weight:700; font-size:10px; letter-spacing:1px; border-bottom: 1px solid #2D2D30;"
        tree_style = """
            QTreeView { background:#1E1E1E; color:#CCCCCC; border:none; outline:0; }
            QTreeView::item { padding:4px 6px; margin: 0 4px; min-height: 20px; }
            QTreeView::item:selected { background:#37373D; color:#FFFFFF; }
            QTreeView::item:hover { background:#2A2D2E; }
            QTreeView::branch:has-children:closed:has-siblings,
            QTreeView::branch:closed:has-children:has-siblings,
            QTreeView::branch:closed:has-children:!has-siblings {
                image: none;
            }
            QTreeView::branch:has-children:open:has-siblings,
            QTreeView::branch:open:has-children:has-siblings,
            QTreeView::branch:open:has-children:!has-siblings {
                image: none;
            }
        """
        self.header.setStyleSheet(header_style)
        self.tree.setStyleSheet(tree_style)

    def _on_double_click(self, index):
        path = self._path_from_proxy_index(index)
        if path is None:
            return
        if path.is_file(): self.fileActivated.emit(path)

    def _on_expanded(self, index):
        path = self._path_from_proxy_index(index)
        if path is not None and path.is_dir():
            self._expanded_paths.add(str(path))

    def _on_collapsed(self, index):
        path = self._path_from_proxy_index(index)
        if path is not None and path.is_dir():
            self._expanded_paths.discard(str(path))

    def _restore_expanded_paths(self):
        for path_str in sorted(self._expanded_paths):
            src_idx = self.model.index(path_str)
            if not src_idx.isValid():
                continue
            idx = self.proxy.mapFromSource(src_idx)
            if idx.isValid():
                self.tree.expand(idx)

    def _path_from_proxy_index(self, index) -> Path | None:
        if not index.isValid():
            return None
        src = self.proxy.mapToSource(index)
        if not src.isValid():
            return None
        return Path(self.model.filePath(src))

    def update_file_stats(self, path: Path, line_count: int, is_dirty: bool):
        path = Path(path)
        self._line_counts.set_live(path, line_count, is_dirty)
        src_idx = self.model.index(str(path))
        if src_idx.isValid():
            idx = self.proxy.mapFromSource(src_idx)
            if idx.isValid():
                self.tree.update(idx)

    def clear_file_stats(self, path: Path):
        path = Path(path)
        self._line_counts.clear_live(path)
        self._line_counts.invalidate(path)
        src_idx = self.model.index(str(path))
        if src_idx.isValid():
            idx = self.proxy.mapFromSource(src_idx)
            if idx.isValid():
                self.tree.update(idx)

    def selected_base_directory(self) -> Path:
        index = self.tree.currentIndex()
        if not index.isValid():
            return self.workspace
        path = self._path_from_proxy_index(index)
        if path is None:
            return self.workspace
        return path if path.is_dir() else path.parent

    def _context_menu(self, pos):
        index = self.tree.indexAt(pos)
        menu = QMenu(self)
        target_dir = self.workspace
        if index.isValid():
            clicked_path = self._path_from_proxy_index(index)
            if clicked_path is None:
                return
            target_dir = clicked_path if clicked_path.is_dir() else clicked_path.parent
        new_file_action = QAction("New File", self)
        new_file_action.triggered.connect(lambda: self.newFileRequested.emit(target_dir))
        menu.addAction(new_file_action)
        new_folder_action = QAction("New Folder", self)
        new_folder_action.triggered.connect(lambda: self.newFolderRequested.emit(target_dir))
        menu.addAction(new_folder_action)
        menu.addSeparator()

        refresh_action = QAction("Refresh", self)
        refresh_action.triggered.connect(self.refresh)
        menu.addAction(refresh_action)

        if index.isValid():
            path = self._path_from_proxy_index(index)
            if path is None:
                return
            open_action = QAction("Open", self)
            open_action.triggered.connect(lambda: self.fileActivated.emit(path) if path.is_file() else None)
            menu.addAction(open_action)

            if path.is_file() and path.suffix == ".py":
                run_action = QAction("Run Python File", self)
                run_action.triggered.connect(lambda: self.runRequested.emit(path))
                menu.addAction(run_action)

            rename_action = QAction("Rename", self)
            rename_action.triggered.connect(lambda: self._rename_path(path))
            menu.addAction(rename_action)

            delete_action = QAction("Delete", self)
            delete_action.triggered.connect(lambda: self._delete_path(path))
            menu.addAction(delete_action)

            reveal_action = QAction("Copy Relative Path", self)
            reveal_action.triggered.connect(lambda: self._copy_relative_path(path))
            menu.addAction(reveal_action)

        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _rename_path(self, path: Path):
        new_name, ok = QInputDialog.getText(self, "Rename", "New name:", text=path.name)
        if not ok or not new_name.strip() or new_name == path.name:
            return
        new_path = path.parent / new_name.strip()
        if new_path.exists():
            QMessageBox.warning(self, "Rename", f"Target already exists:\n{new_path}")
            return
        try:
            path.rename(new_path)
        except Exception as exc:
            QMessageBox.critical(self, "Rename", f"Could not rename:\n{exc}")
            return
        self.refresh()

    def _delete_path(self, path: Path):
        label = "folder" if path.is_dir() else "file"
        resp = QMessageBox.question(
            self,
            "Delete",
            f"Delete this {label}?\n{path}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if resp != QMessageBox.Yes:
            return
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink(missing_ok=True)
        except Exception as exc:
            QMessageBox.critical(self, "Delete", f"Could not delete:\n{exc}")
            return
        self.refresh()

    def _copy_relative_path(self, path: Path):
        try:
            rel = path.relative_to(self.workspace)
        except ValueError:
            rel = path
        QApplication.clipboard().setText(str(rel).replace("\\", "/"))