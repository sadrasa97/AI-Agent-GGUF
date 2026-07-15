"""Workspace file-tree explorer (left activity panel, like VS Code's Explorer)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFileSystemModel, QTreeView, QWidget, QVBoxLayout, QLabel, QMenu
from PySide6.QtGui import QAction

IGNORED_DIRS = {"__pycache__", ".git", "node_modules", ".venv", "venv", "dist", "build"}


class FileExplorer(QWidget):
    fileActivated = Signal(Path)
    runRequested = Signal(Path)
    newFileRequested = Signal(Path)
    newFolderRequested = Signal(Path)

    def __init__(self, workspace: Path, parent=None):
        super().__init__(parent)
        self.workspace = Path(workspace)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QLabel(self.workspace.name.upper() or "WORKSPACE")
        header.setStyleSheet(
            "background:#252526; color:#bbbbbb; padding:6px 10px; "
            "font-weight:bold; font-size:11px; letter-spacing:1px;"
        )
        layout.addWidget(header)

        self.model = QFileSystemModel()
        self.model.setRootPath(str(self.workspace))

        self.tree = QTreeView()
        self.tree.setModel(self.model)
        self.tree.setRootIndex(self.model.index(str(self.workspace)))
        self.tree.setHeaderHidden(True)
        for col in (1, 2, 3):
            self.tree.hideColumn(col)
        self.tree.setStyleSheet(
            "QTreeView { background:#252526; color:#cccccc; border:none; outline:0; }"
            "QTreeView::item { padding:3px; }"
            "QTreeView::item:selected { background:#37373d; }"
            "QTreeView::item:hover { background:#2a2d2e; }"
        )
        self.tree.doubleClicked.connect(self._on_double_click)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._context_menu)
        layout.addWidget(self.tree)

    def set_workspace(self, workspace: Path):
        self.workspace = Path(workspace)
        self.model.setRootPath(str(self.workspace))
        self.tree.setRootIndex(self.model.index(str(self.workspace)))

    def _on_double_click(self, index):
        path = Path(self.model.filePath(index))
        if path.is_file():
            self.fileActivated.emit(path)

    def _context_menu(self, pos):
        index = self.tree.indexAt(pos)
        menu = QMenu(self)

        target_dir = self.workspace
        if index.isValid():
            clicked_path = Path(self.model.filePath(index))
            target_dir = clicked_path if clicked_path.is_dir() else clicked_path.parent

        new_file_action = QAction("New File", self)
        new_file_action.triggered.connect(lambda: self.newFileRequested.emit(target_dir))
        menu.addAction(new_file_action)

        new_folder_action = QAction("New Folder", self)
        new_folder_action.triggered.connect(lambda: self.newFolderRequested.emit(target_dir))
        menu.addAction(new_folder_action)

        menu.addSeparator()
        refresh_action = QAction("Refresh", self)
        refresh_action.triggered.connect(lambda: self.model.setRootPath(str(self.workspace)))
        menu.addAction(refresh_action)

        if index.isValid():
            path = Path(self.model.filePath(index))
            open_action = QAction("Open", self)
            open_action.triggered.connect(lambda: self.fileActivated.emit(path) if path.is_file() else None)
            menu.addAction(open_action)
            if path.is_file() and path.suffix == ".py":
                run_action = QAction("▶️ Run", self)
                run_action.triggered.connect(lambda: self.runRequested.emit(path))
                menu.addAction(run_action)
        menu.exec(self.tree.viewport().mapToGlobal(pos))