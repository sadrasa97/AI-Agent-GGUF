"""Workspace file-tree explorer."""
from __future__ import annotations
from pathlib import Path
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFileSystemModel, QTreeView, QWidget, QVBoxLayout, QLabel, QMenu
from PySide6.QtGui import QAction

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

    def __init__(self, workspace: Path, parent=None):
        super().__init__(parent)
        self.workspace = Path(workspace)
        self._theme = "dark"
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.header = QLabel(_workspace_header_text(self.workspace))
        layout.addWidget(self.header)
        self.model = QFileSystemModel()
        self.model.setRootPath(str(self.workspace))
        self.tree = QTreeView()
        self.tree.setModel(self.model)
        self.tree.setRootIndex(self.model.index(str(self.workspace)))
        self.tree.setHeaderHidden(True)
        for col in (1, 2, 3): self.tree.hideColumn(col)
        self.tree.doubleClicked.connect(self._on_double_click)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._context_menu)
        layout.addWidget(self.tree)
        self.apply_theme(self._theme)

    def set_workspace(self, workspace: Path):
        self.workspace = Path(workspace)
        self.model.setRootPath(str(self.workspace))
        self.tree.setRootIndex(self.model.index(str(self.workspace)))
        self.header.setText(_workspace_header_text(self.workspace))

    def refresh(self):
        self.model.setRootPath(str(self.workspace))
        self.tree.setRootIndex(self.model.index(str(self.workspace)))

    def apply_theme(self, theme: str):
        self._theme = "dark"
        header_style = "background:#0F111A; color:#5A647D; padding:10px 14px; font-weight:700; font-size:10px; letter-spacing:1.5px; border-bottom: 1px solid #1E2333;"
        tree_style = """
            QTreeView { background:#0B0D14; color:#E2E8F0; border:none; outline:0; }
            QTreeView::item { padding:6px 8px; border-radius: 4px; margin: 1px 4px; }
            QTreeView::item:selected { background:#1E2333; color:#00E5FF; }
            QTreeView::item:hover { background:#161A26; }
        """
        self.header.setStyleSheet(header_style)
        self.tree.setStyleSheet(tree_style)

    def _on_double_click(self, index):
        path = Path(self.model.filePath(index))
        if path.is_file(): self.fileActivated.emit(path)

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
        refresh_action.triggered.connect(self.refresh)
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