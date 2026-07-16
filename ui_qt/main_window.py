"""
MainWindow — the VS Code-style shell.

Layout:
  ┌─────────────────────────────────────────────────────────────┐
  │ Menu bar                                                     │
  ├───┬─────────────┬───────────────────────────────┬───────────┤
  │ A │  Explorer   │        Editor tabs             │   Chat    │
  │ c │  (dock)     │        (center)                │  (dock)   │
  │ t │             │                                 │           │
  ├───┴─────────────┴───────────────────────────────┴───────────┤
  │                     Output / Terminal (dock, bottom)          │
  ├────────────────────────────────────────────────────────────────┤
  │ Status bar: backend · model · workspace · cursor position     │
  └────────────────────────────────────────────────────────────────┘
"""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Allow running this file directly: `python ui_qt/main_window.py`
if __package__ is None or __package__ == "":
    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QAction, QKeySequence, QIcon
from PySide6.QtWidgets import (
    QMainWindow, QDockWidget, QFileDialog, QMessageBox, QToolBar,
    QLabel, QWidget, QVBoxLayout, QInputDialog, QApplication, QLineEdit,
    QStyle,
)

from config.settings import Settings, VALID_UI_THEMES
from tools.code_tools import (
    build_workspace_context, list_workspace_files, save_code, CodeBlock,
    resolve_workspace_path,
)
from ui_qt.editor import EditorTabs
from ui_qt.file_explorer import FileExplorer
from ui_qt.chat_panel import ChatPanel
from ui_qt.model_settings_dialog import ModelSettingsDialog
from ui_qt.output_panel import OutputPanel

DARK_STYLESHEET = """
QMainWindow, QWidget { background-color: #1a1b1e; color: #d4d4d8; font-family: 'Segoe UI', 'Inter', sans-serif; }
QMenuBar { background-color: #202124; color: #cccccc; padding: 2px; }
QMenuBar::item { padding: 4px 10px; border-radius: 6px; }
QMenuBar::item:selected { background-color: #2b2d31; }
QMenu { background-color: #202124; color: #cccccc; border: 1px solid #303136; border-radius: 8px; padding: 4px; }
QMenu::item { padding: 5px 12px; border-radius: 6px; }
QMenu::item:selected { background-color: #2b2d31; }
QToolBar#MainToolbar {
    background-color: #3c3c3c;
    border: none;
    border-bottom: 1px solid #2a2a2a;
    spacing: 0px;
    padding: 1px 6px;
}
QToolBar#MainToolbar QToolButton {
    background: transparent;
    color: #cccccc;
    border: 1px solid transparent;
    border-radius: 0px;
    padding: 4px;
    margin: 0px;
    min-width: 26px;
    min-height: 24px;
}
QToolBar#MainToolbar QToolButton:hover {
    background-color: #505050;
}
QToolBar#MainToolbar QToolButton:pressed {
    background-color: #444444;
}
QToolBar#MainToolbar QToolButton:checked {
    background-color: #4b4b4b;
    border: 1px solid #5c5c5c;
}
QToolBar#MainToolbar QToolButton:disabled {
    color: #5a5a5e;
}
QToolBar#MainToolbar::separator {
    background-color: #5a5a5a;
    width: 1px;
    margin: 4px 6px;
}
QTabWidget::pane { border: none; background: #1e1e1e; top: -1px; }
QTabBar { qproperty-drawBase: 0; }
QDockWidget { titlebar-close-icon: none; border: none; }
QDockWidget::title { background:#202124; color:#a0a1a6; padding:8px 10px; font-weight:600; font-size:11px; letter-spacing:1px; }
QScrollBar:vertical {
    background: transparent;
    width: 11px;
    margin: 3px 2px 3px 0;
}
QScrollBar::handle:vertical {
    background: rgba(255, 255, 255, 0.13);
    border-radius: 5px;
    min-height: 36px;
}
QScrollBar::handle:vertical:hover { background: rgba(255, 255, 255, 0.24); }
QScrollBar::handle:vertical:pressed { background: rgba(255, 255, 255, 0.34); }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; width: 0; background: none; border: none; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
QScrollBar:horizontal {
    background: transparent;
    height: 11px;
    margin: 0 3px 2px 3px;
}
QScrollBar::handle:horizontal {
    background: rgba(255, 255, 255, 0.13);
    border-radius: 5px;
    min-width: 36px;
}
QScrollBar::handle:horizontal:hover { background: rgba(255, 255, 255, 0.24); }
QScrollBar::handle:horizontal:pressed { background: rgba(255, 255, 255, 0.34); }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { height: 0; width: 0; background: none; border: none; }
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: none; }
QAbstractScrollArea::corner { background: transparent; border: none; }
QSplitter::handle { background:#1a1b1e; width:2px; }
QPushButton { border-radius: 8px; }
QLineEdit, QPlainTextEdit, QTextEdit { border-radius: 8px; }
"""

LIGHT_STYLESHEET = """
QMainWindow, QWidget { background-color: #f6f8fb; color: #1f1f1f; font-family: 'Segoe UI', 'Inter', sans-serif; }
QMenuBar { background-color: #ebedf0; color: #222222; padding: 2px; }
QMenuBar::item { padding: 4px 10px; border-radius: 6px; }
QMenuBar::item:selected { background-color: #dfe6f2; }
QMenu { background-color: #ffffff; color: #222222; border: 1px solid #d2d7df; border-radius: 8px; padding: 4px; }
QMenu::item { padding: 5px 12px; border-radius: 6px; }
QMenu::item:selected { background-color: #e9f1ff; }
QDockWidget { titlebar-close-icon: none; border: none; }
QDockWidget::title { background:#ebedf0; color:#555b66; padding:8px 10px; font-weight:600; font-size:11px; letter-spacing:1px; }
QScrollBar:vertical {
    background: transparent;
    width: 11px;
    margin: 3px 2px 3px 0;
}
QScrollBar::handle:vertical {
    background: rgba(0, 0, 0, 0.14);
    border-radius: 5px;
    min-height: 36px;
}
QScrollBar::handle:vertical:hover { background: rgba(0, 0, 0, 0.24); }
QScrollBar::handle:vertical:pressed { background: rgba(0, 0, 0, 0.34); }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; width: 0; background: none; border: none; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
QScrollBar:horizontal {
    background: transparent;
    height: 11px;
    margin: 0 3px 2px 3px;
}
QScrollBar::handle:horizontal {
    background: rgba(0, 0, 0, 0.14);
    border-radius: 5px;
    min-width: 36px;
}
QScrollBar::handle:horizontal:hover { background: rgba(0, 0, 0, 0.24); }
QScrollBar::handle:horizontal:pressed { background: rgba(0, 0, 0, 0.34); }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { height: 0; width: 0; background: none; border: none; }
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: none; }
QAbstractScrollArea::corner { background: transparent; border: none; }
QSplitter::handle { background:#d7dce4; width:2px; }
QPushButton { border-radius: 8px; }
QLineEdit, QPlainTextEdit, QTextEdit { border-radius: 8px; }
"""


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings):
        super().__init__()
        self.settings = settings
        self._last_generated_block: CodeBlock | None = None
        if self.settings.ui_theme not in VALID_UI_THEMES:
            self.settings.ui_theme = "dark"
        self.setWindowTitle("GGUF Code Agent — IDE")
        self.resize(1440, 900)
        self.setStyleSheet(DARK_STYLESHEET)

        # ---- central editor tabs ----
        self.editor_tabs = EditorTabs()
        self.setCentralWidget(self.editor_tabs)
        self.editor_tabs.fileSaved.connect(lambda _p: None)

        # ---- explorer dock (left) ----
        self.explorer = FileExplorer(self.settings.workspace_path)
        self.explorer.fileActivated.connect(self.editor_tabs.open_file)
        self.explorer.runRequested.connect(self._run_path)
        self.explorer.newFileRequested.connect(self._create_file_in_directory)
        self.explorer.newFolderRequested.connect(self._create_folder_in_directory)
        explorer_dock = QDockWidget("EXPLORER", self)
        explorer_dock.setWidget(self.explorer)
        explorer_dock.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable)
        explorer_dock.setTitleBarWidget(QWidget())
        self.addDockWidget(Qt.LeftDockWidgetArea, explorer_dock)
        self.explorer_dock = explorer_dock

        # Give the side docks (Explorer / Chat) ownership of the bottom corners so the
        # bottom Output/Terminal dock only spans the center, and Chat reaches full height
        # all the way down the right edge of the window.
        self.setCorner(Qt.TopLeftCorner, Qt.LeftDockWidgetArea)
        self.setCorner(Qt.BottomLeftCorner, Qt.LeftDockWidgetArea)
        self.setCorner(Qt.TopRightCorner, Qt.RightDockWidgetArea)
        self.setCorner(Qt.BottomRightCorner, Qt.RightDockWidgetArea)

        # ---- chat dock (right) ----
        self.chat_panel = ChatPanel(self.settings, self._workspace_context_for_chat)
        self.chat_panel.codeBlockReady.connect(self._on_code_block_from_chat)
        self.chat_panel.agentFileEdit.connect(self._on_agent_file_edit)
        chat_dock = QDockWidget("CHAT", self)
        chat_dock.setWidget(self.chat_panel)
        chat_dock.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable)
        chat_dock.setTitleBarWidget(QWidget())
        self.addDockWidget(Qt.RightDockWidgetArea, chat_dock)
        self.chat_dock = chat_dock

        self.resizeDocks([explorer_dock], [260], Qt.Horizontal)
        self.resizeDocks([chat_dock], [420], Qt.Horizontal)

        # ---- output dock (bottom) ----
        self.output_panel = OutputPanel(self.settings.workspace_path, self.settings)
        output_dock = QDockWidget("OUTPUT", self)
        output_dock.setWidget(self.output_panel)
        output_dock.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable)
        output_dock.setTitleBarWidget(QWidget())
        self.addDockWidget(Qt.BottomDockWidgetArea, output_dock)
        self.output_dock = output_dock
        self.resizeDocks([output_dock], [200], Qt.Vertical)

        # Use a VS Code-like top menu bar (File/Edit/View/Go/Run/Terminal/Help).
        self._build_menus()
        self._set_code_editor_visible(self.settings.show_code_editor, save=False)
        self._apply_theme(self.settings.ui_theme, save=False)

        self.editor_tabs.activeFileChanged.connect(self._on_active_file_changed)
        self.editor_tabs.currentChanged.connect(lambda _i: self._sync_undo_redo_state())
        self._sync_undo_redo_state()

    # ──────────────────────────────────────────────────────────────
    # Menus
    # ──────────────────────────────────────────────────────────────
    def _build_menus(self):
        menubar = self.menuBar()
        menubar.clear()

        file_menu = menubar.addMenu("&File")
        new_file_action = QAction("New File In Project…", self)
        new_file_action.setShortcut("Ctrl+Alt+N")
        new_file_action.triggered.connect(self._create_new_file)
        new_folder_action = QAction("New Folder In Project…", self)
        new_folder_action.setShortcut("Ctrl+Alt+Shift+N")
        new_folder_action.triggered.connect(self._create_new_folder)
        open_file_action = QAction("Open File…", self)
        open_file_action.setShortcut(QKeySequence.Open)
        open_file_action.triggered.connect(self._open_file_dialog)
        open_folder_action = QAction("Open Folder…", self)
        open_folder_action.triggered.connect(self._open_folder_dialog)
        save_action = QAction("Save", self)
        save_action.setShortcut(QKeySequence.Save)
        save_action.triggered.connect(lambda: self.editor_tabs.save_current())
        save_as_action = QAction("Save As…", self)
        save_as_action.setShortcut(QKeySequence.SaveAs)
        save_as_action.triggered.connect(lambda: self.editor_tabs.save_current(save_as=True))
        for action in (
            new_file_action,
            new_folder_action,
            open_file_action,
            open_folder_action,
            save_action,
            save_as_action,
        ):
            file_menu.addAction(action)

        edit_menu = menubar.addMenu("&Edit")
        undo_action = QAction("Undo", self)
        undo_action.setShortcut(QKeySequence.Undo)
        undo_action.triggered.connect(lambda: self._active_editor_call("undo"))
        edit_menu.addAction(undo_action)
        self.undo_action = undo_action

        redo_action = QAction("Redo", self)
        redo_action.setShortcut(QKeySequence.Redo)
        redo_action.triggered.connect(lambda: self._active_editor_call("redo"))
        edit_menu.addAction(redo_action)
        self.redo_action = redo_action

        view_menu = menubar.addMenu("&View")
        toggle_explorer_action = QAction("Toggle Explorer", self)
        toggle_explorer_action.setCheckable(True)
        toggle_explorer_action.setChecked(True)
        toggle_explorer_action.triggered.connect(
            lambda checked: self.explorer_dock.setVisible(checked)
        )
        self.explorer_dock.visibilityChanged.connect(toggle_explorer_action.setChecked)
        view_menu.addAction(toggle_explorer_action)

        toggle_chat_action = QAction("Toggle Chat", self)
        toggle_chat_action.setCheckable(True)
        toggle_chat_action.setChecked(True)
        toggle_chat_action.triggered.connect(lambda checked: self.chat_dock.setVisible(checked))
        self.chat_dock.visibilityChanged.connect(toggle_chat_action.setChecked)
        view_menu.addAction(toggle_chat_action)

        toggle_output_action = QAction("Toggle Output", self)
        toggle_output_action.setCheckable(True)
        toggle_output_action.setChecked(True)
        toggle_output_action.triggered.connect(lambda checked: self.output_dock.setVisible(checked))
        self.output_dock.visibilityChanged.connect(toggle_output_action.setChecked)
        view_menu.addAction(toggle_output_action)

        self.toggle_editor_action = QAction("Toggle Code Editor", self)
        self.toggle_editor_action.setCheckable(True)
        self.toggle_editor_action.setChecked(self.settings.show_code_editor)
        self.toggle_editor_action.triggered.connect(self._set_code_editor_visible)
        view_menu.addAction(self.toggle_editor_action)

        themes_menu = view_menu.addMenu("Theme")
        self.theme_dark_action = QAction("Dark", self)
        self.theme_dark_action.setCheckable(True)
        self.theme_dark_action.triggered.connect(lambda: self._apply_theme("dark"))
        themes_menu.addAction(self.theme_dark_action)

        self.theme_light_action = QAction("Light", self)
        self.theme_light_action.setCheckable(True)
        self.theme_light_action.triggered.connect(lambda: self._apply_theme("light"))
        themes_menu.addAction(self.theme_light_action)

        menubar.addMenu("&Go")

        run_menu = menubar.addMenu("&Run")
        run_action = QAction("Run Active File", self)
        run_action.setShortcut("F5")
        run_action.triggered.connect(self._run_active_file)
        run_menu.addAction(run_action)

        terminal_menu = menubar.addMenu("&Terminal")
        terminal_menu.addAction(toggle_output_action)

        settings_menu = menubar.addMenu("&Settings")
        model_action = QAction("Model Setup…", self)
        model_action.triggered.connect(self._open_model_settings_dialog)
        settings_menu.addAction(model_action)

        ai_menu = menubar.addMenu("&AI")
        apply_last_action = QAction("Apply Last Generated Code…", self)
        apply_last_action.triggered.connect(self._apply_last_generated_code)
        ai_menu.addAction(apply_last_action)

        help_menu = menubar.addMenu("&Help")
        about_action = QAction("About", self)
        about_action.triggered.connect(
            lambda: QMessageBox.information(self, "About", "GGUF Code Agent")
        )
        help_menu.addAction(about_action)

    def _apply_theme(self, theme: str, save: bool = True):
        theme_key = theme if theme in VALID_UI_THEMES else "dark"
        self.settings.ui_theme = theme_key

        self.setStyleSheet(DARK_STYLESHEET if theme_key == "dark" else LIGHT_STYLESHEET)
        self.editor_tabs.apply_theme(theme_key)

        if hasattr(self, "theme_dark_action"):
            self.theme_dark_action.setChecked(theme_key == "dark")
        if hasattr(self, "theme_light_action"):
            self.theme_light_action.setChecked(theme_key == "light")

        if save:
            self.settings.save()

    def _set_code_editor_visible(self, visible: bool, save: bool = True):
        self.settings.show_code_editor = bool(visible)
        self.editor_tabs.setVisible(self.settings.show_code_editor)
        if hasattr(self, "toggle_editor_action"):
            self.toggle_editor_action.setChecked(self.settings.show_code_editor)
        if save:
            self.settings.save()

    def _build_toolbar(self):
        toolbar = QToolBar("Main")
        toolbar.setObjectName("MainToolbar")
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        toolbar.setIconSize(QSize(16, 16))
        toolbar.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.addToolBar(toolbar)

        style = self.style()

        def std_icon(sp):
            return style.standardIcon(sp)

        # -- file/project actions (icon-only, VS Code title-bar style) --
        new_file_btn = QAction(std_icon(QStyle.SP_FileIcon), "New File", self)
        new_file_btn.setToolTip("New File (Ctrl+Alt+N)")
        new_file_btn.setShortcut("Ctrl+Alt+N")
        new_file_btn.triggered.connect(self._create_new_file)
        toolbar.addAction(new_file_btn)

        new_folder_btn = QAction(std_icon(QStyle.SP_DirIcon), "New Folder", self)
        new_folder_btn.setToolTip("New Folder (Ctrl+Alt+Shift+N)")
        new_folder_btn.setShortcut("Ctrl+Alt+Shift+N")
        new_folder_btn.triggered.connect(self._create_new_folder)
        toolbar.addAction(new_folder_btn)

        open_file_btn = QAction(std_icon(QStyle.SP_DialogOpenButton), "Open File", self)
        open_file_btn.setToolTip("Open File… (Ctrl+O)")
        open_file_btn.setShortcut(QKeySequence.Open)
        open_file_btn.triggered.connect(self._open_file_dialog)
        toolbar.addAction(open_file_btn)

        open_folder_btn = QAction(std_icon(QStyle.SP_DirOpenIcon), "Open Folder", self)
        open_folder_btn.setToolTip("Open Folder…")
        open_folder_btn.triggered.connect(self._open_folder_dialog)
        toolbar.addAction(open_folder_btn)

        toolbar.addSeparator()

        save_btn = QAction(std_icon(QStyle.SP_DialogSaveButton), "Save", self)
        save_btn.setToolTip("Save (Ctrl+S)")
        save_btn.setShortcut(QKeySequence.Save)
        save_btn.triggered.connect(lambda: self.editor_tabs.save_current())
        toolbar.addAction(save_btn)

        save_as_btn = QAction(std_icon(QStyle.SP_DriveFDIcon), "Save As", self)
        save_as_btn.setToolTip("Save As… (Ctrl+Shift+S)")
        save_as_btn.setShortcut(QKeySequence.SaveAs)
        save_as_btn.triggered.connect(lambda: self.editor_tabs.save_current(save_as=True))
        toolbar.addAction(save_as_btn)

        toolbar.addSeparator()

        # -- undo / redo, applied to the active editor buffer --
        undo_btn = QAction(std_icon(QStyle.SP_ArrowBack), "Undo", self)
        undo_btn.setToolTip("Undo (Ctrl+Z)")
        undo_btn.setShortcut(QKeySequence.Undo)
        undo_btn.triggered.connect(lambda: self._active_editor_call("undo"))
        toolbar.addAction(undo_btn)
        self.undo_action = undo_btn

        redo_btn = QAction(std_icon(QStyle.SP_ArrowForward), "Redo", self)
        redo_btn.setToolTip("Redo (Ctrl+Y)")
        redo_btn.setShortcut(QKeySequence.Redo)
        redo_btn.triggered.connect(lambda: self._active_editor_call("redo"))
        toolbar.addAction(redo_btn)
        self.redo_action = redo_btn

        toolbar.addSeparator()

        # -- panel toggle buttons (icon-only, checkable like VS Code activity bar) --
        toggle_explorer_btn = QAction(std_icon(QStyle.SP_FileDialogListView), "Explorer", self)
        toggle_explorer_btn.setToolTip("Toggle Explorer")
        toggle_explorer_btn.setCheckable(True)
        toggle_explorer_btn.setChecked(True)
        toggle_explorer_btn.triggered.connect(
            lambda checked: self.explorer_dock.setVisible(checked)
        )
        self.explorer_dock.visibilityChanged.connect(toggle_explorer_btn.setChecked)
        toolbar.addAction(toggle_explorer_btn)

        toggle_chat_btn = QAction(std_icon(QStyle.SP_MessageBoxInformation), "Chat", self)
        toggle_chat_btn.setToolTip("Toggle Chat")
        toggle_chat_btn.setCheckable(True)
        toggle_chat_btn.setChecked(True)
        toggle_chat_btn.triggered.connect(lambda checked: self.chat_dock.setVisible(checked))
        self.chat_dock.visibilityChanged.connect(toggle_chat_btn.setChecked)
        toolbar.addAction(toggle_chat_btn)

        toggle_output_btn = QAction(std_icon(QStyle.SP_ComputerIcon), "Output", self)
        toggle_output_btn.setToolTip("Toggle Terminal / Output")
        toggle_output_btn.setCheckable(True)
        toggle_output_btn.setChecked(True)
        toggle_output_btn.triggered.connect(lambda checked: self.output_dock.setVisible(checked))
        self.output_dock.visibilityChanged.connect(toggle_output_btn.setChecked)
        toolbar.addAction(toggle_output_btn)

        toolbar.addSeparator()

        run_btn = QAction(std_icon(QStyle.SP_MediaPlay), "Run", self)
        run_btn.setToolTip("Run Active File (F5)")
        run_btn.setShortcut("F5")
        run_btn.triggered.connect(self._run_active_file)
        toolbar.addAction(run_btn)

        settings_btn = QAction(std_icon(QStyle.SP_FileDialogDetailedView), "Settings", self)
        settings_btn.setToolTip("Model Settings")
        settings_btn.triggered.connect(self._open_model_settings_dialog)
        toolbar.addAction(settings_btn)

        apply_ai_btn = QAction(std_icon(QStyle.SP_DialogApplyButton), "Apply AI", self)
        apply_ai_btn.setToolTip("Apply Last Generated AI Code")
        apply_ai_btn.triggered.connect(self._apply_last_generated_code)
        toolbar.addAction(apply_ai_btn)

        # keep undo/redo enabled-state in sync with the active editor
        self.editor_tabs.currentChanged.connect(lambda _i: self._sync_undo_redo_state())
        self._sync_undo_redo_state()

    def _sync_undo_redo_state(self):
        if not hasattr(self, "undo_action") or not hasattr(self, "redo_action"):
            return
        editor = self.editor_tabs.current_editor()
        has_editor = editor is not None
        self.undo_action.setEnabled(has_editor and editor.document().isUndoAvailable())
        self.redo_action.setEnabled(has_editor and editor.document().isRedoAvailable())
        if editor is not None:
            editor.undoAvailable.connect(self.undo_action.setEnabled)
            editor.redoAvailable.connect(self.redo_action.setEnabled)

    # ──────────────────────────────────────────────────────────────
    # File actions
    # ──────────────────────────────────────────────────────────────
    def _open_file_dialog(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Open File", str(self.settings.workspace_path))
        if filename:
            self.editor_tabs.open_file(Path(filename))

    def _open_folder_dialog(self):
        folder = QFileDialog.getExistingDirectory(self, "Open Folder", str(self.settings.workspace_path))
        if folder:
            self.settings.workspace = folder
            self.settings.save()
            self.explorer.set_workspace(Path(folder))
            self.output_panel.set_working_directory(Path(folder))

    def _selected_base_directory(self) -> Path:
        index = self.explorer.tree.currentIndex()
        if index.isValid():
            selected = Path(self.explorer.model.filePath(index))
            return selected if selected.is_dir() else selected.parent
        return self.settings.workspace_path

    def _create_new_file(self):
        self._create_file_in_directory(self._selected_base_directory())

    def _create_new_folder(self):
        self._create_folder_in_directory(self._selected_base_directory())

    def _create_file_in_directory(self, base_dir: Path):
        text, ok = QInputDialog.getText(self, "New File", "File name (or relative path):")
        if not ok:
            return
        relative = text.strip().replace("\\", "/")
        if not relative:
            return

        target = (base_dir / relative).resolve()
        workspace_root = self.settings.workspace_path.resolve()
        try:
            target.relative_to(workspace_root)
        except ValueError:
            QMessageBox.warning(self, "Invalid Path", "File must be inside the current workspace.")
            return

        if target.exists():
            QMessageBox.warning(self, "Already Exists", f"File already exists:\n{target}")
            return

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("", encoding="utf-8")
        except Exception as exc:
            QMessageBox.critical(self, "Create File Failed", str(exc))
            return

        self.explorer.model.setRootPath(str(self.settings.workspace_path))
        self.explorer.tree.setRootIndex(self.explorer.model.index(str(self.settings.workspace_path)))
        self.editor_tabs.open_file(target)

    def _create_folder_in_directory(self, base_dir: Path):
        text, ok = QInputDialog.getText(self, "New Folder", "Folder name (or relative path):")
        if not ok:
            return
        relative = text.strip().replace("\\", "/")
        if not relative:
            return

        target = (base_dir / relative).resolve()
        workspace_root = self.settings.workspace_path.resolve()
        try:
            target.relative_to(workspace_root)
        except ValueError:
            QMessageBox.warning(self, "Invalid Path", "Folder must be inside the current workspace.")
            return

        if target.exists():
            QMessageBox.warning(self, "Already Exists", f"Folder already exists:\n{target}")
            return

        try:
            target.mkdir(parents=True, exist_ok=False)
        except Exception as exc:
            QMessageBox.critical(self, "Create Folder Failed", str(exc))
            return

        self.explorer.model.setRootPath(str(self.settings.workspace_path))
        self.explorer.tree.setRootIndex(self.explorer.model.index(str(self.settings.workspace_path)))

    def _active_editor_call(self, method_name: str):
        editor = self.editor_tabs.current_editor()
        if editor:
            getattr(editor, method_name)()

    def _on_active_file_changed(self, path):
        if path:
            self.setWindowTitle(f"{Path(path).name} — GGUF Code Agent")
        else:
            self.setWindowTitle("GGUF Code Agent — IDE")

    # ──────────────────────────────────────────────────────────────
    # Run
    # ──────────────────────────────────────────────────────────────
    def _run_active_file(self):
        editor = self.editor_tabs.current_editor()
        if editor is None:
            QMessageBox.information(self, "Run", "No file open.")
            return
        if editor.file_path is None or editor.is_dirty:
            self.editor_tabs.save_current()
            editor = self.editor_tabs.current_editor()
        if editor.file_path is None:
            return
        self._run_path(editor.file_path)

    def _run_path(self, path: Path):
        """Run a specific file on disk (opening it in the editor first if needed)."""
        self.editor_tabs.open_file(path)
        editor = self.editor_tabs.current_editor()
        if editor is not None and editor.is_dirty:
            self.editor_tabs.save_current()
        if not self.output_panel.execute_file(path):
            QMessageBox.information(self, "Run", f"No runner registered for {path.suffix} files.")
            return
        self.output_dock.setVisible(True)
        self.output_dock.raise_()

    # ──────────────────────────────────────────────────────────────
    # Chat <-> editor bridge
    # ──────────────────────────────────────────────────────────────
    def _workspace_context_for_chat(self) -> str:
        recent = []
        editor = self.editor_tabs.current_editor()
        if editor and editor.file_path:
            recent = [editor.file_path]
        return build_workspace_context(self.settings.workspace_path, recent_files=recent)

    def _on_code_block_from_chat(self, language: str, code: str):
        """Apply generated code in a user-selected way (replace/insert/new/save)."""
        block = CodeBlock(language, code)
        self._last_generated_block = block
        self._apply_generated_code_block(block)

    def _on_agent_file_edit(self, rel_path: str, language: str, code: str):
        """Agent mode: write the model's output straight to disk, the same way
        Copilot's agent mode edits/creates files without a manual apply step."""
        workspace_root = self.settings.workspace_path.resolve()
        try:
            target = resolve_workspace_path(workspace_root, rel_path)
        except ValueError:
            self.output_panel.output.appendPlainText(
                f"[agent] refused to write outside workspace: {rel_path}"
            )
            return

        is_new = not target.exists()
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(code, encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Agent Edit Failed", f"{target}:\n{exc}")
            return

        # refresh explorer so newly created files/folders show up
        self.explorer.model.setRootPath(str(self.settings.workspace_path))
        self.explorer.tree.setRootIndex(self.explorer.model.index(str(self.settings.workspace_path)))

        # reflect the change in an already-open tab, or open a new one
        existing_editor = None
        for i in range(self.editor_tabs.count()):
            page = self.editor_tabs.widget(i)
            if page.editor.file_path == target:
                existing_editor = page.editor
                self.editor_tabs.setCurrentIndex(i)
                break
        if existing_editor is not None:
            existing_editor.setPlainText(code)
            existing_editor.highlighter.set_extension(target.suffix.lstrip("."))
            existing_editor.mark_clean()
        else:
            self.editor_tabs.open_file(target)

        try:
            rel_display = target.relative_to(workspace_root)
        except ValueError:
            rel_display = target
        verb = "Created" if is_new else "Updated"
        self.output_panel.output.appendPlainText(f"[agent] {verb}: {rel_display}")

    def _apply_generated_code_block(self, block: CodeBlock):
        options = [
            "Open as new tab",
            "Replace active file content",
            "Insert at cursor",
            "Save directly to workspace file",
            "Save as new file and run",
        ]
        choice, ok = QInputDialog.getItem(
            self,
            "Apply AI Code",
            "How should generated code be applied?",
            options,
            0,
            False,
        )
        if not ok:
            return

        if choice == "Open as new tab":
            self.editor_tabs.new_untitled(template_code=block.code, language=block.extension)
            return

        editor = self.editor_tabs.current_editor()

        if choice == "Replace active file content":
            if editor is None:
                self.editor_tabs.new_untitled(template_code=block.code, language=block.extension)
                return
            editor.setPlainText(block.code)
            if editor.file_path is not None:
                editor.highlighter.set_extension(editor.file_path.suffix.lstrip("."))
            else:
                editor.highlighter.set_extension(block.extension)
            return

        if choice == "Insert at cursor":
            if editor is None:
                self.editor_tabs.new_untitled(template_code=block.code, language=block.extension)
                return
            cursor = editor.textCursor()
            cursor.insertText(block.code)
            editor.setTextCursor(cursor)
            return

        if choice == "Save directly to workspace file":
            start_dir = str(self.settings.workspace_path)
            default_name = f"generated.{block.extension}"
            filename, _ = QFileDialog.getSaveFileName(self, "Save Generated Code", str(Path(start_dir) / default_name))
            if not filename:
                return
            out_path = Path(filename)
            workspace_root = self.settings.workspace_path.resolve()
            try:
                out_path.resolve().relative_to(workspace_root)
            except ValueError:
                QMessageBox.warning(self, "Invalid Path", "Target file must be inside the current workspace.")
                return
            try:
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(block.code, encoding="utf-8")
            except Exception as exc:
                QMessageBox.critical(self, "Save Failed", str(exc))
                return
            self.explorer.model.setRootPath(str(self.settings.workspace_path))
            self.explorer.tree.setRootIndex(self.explorer.model.index(str(self.settings.workspace_path)))
            self.editor_tabs.open_file(out_path)
            return

        if choice == "Save as new file and run":
            out_path = self._auto_generated_file_path(block)
            try:
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(block.code, encoding="utf-8")
            except Exception as exc:
                QMessageBox.critical(self, "Save Failed", str(exc))
                return

            self.explorer.model.setRootPath(str(self.settings.workspace_path))
            self.explorer.tree.setRootIndex(self.explorer.model.index(str(self.settings.workspace_path)))
            self.editor_tabs.open_file(out_path)
            self._run_path(out_path)

    def _auto_generated_file_path(self, block: CodeBlock) -> Path:
        generated_dir = self.settings.workspace_path / "generated"
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = generated_dir / f"generated_{stamp}.{block.extension}"
        if not base.exists():
            return base

        idx = 1
        while True:
            candidate = generated_dir / f"generated_{stamp}_{idx}.{block.extension}"
            if not candidate.exists():
                return candidate
            idx += 1

    # ──────────────────────────────────────────────────────────────
    # Settings dialogs
    # ──────────────────────────────────────────────────────────────
    def _open_model_settings_dialog(self):
        dialog = ModelSettingsDialog(self.settings, self)
        if dialog.exec():
            self.chat_panel.backend_combo.setCurrentText(self.settings.backend)

    def _apply_last_generated_code(self):
        if self._last_generated_block is None:
            QMessageBox.information(self, "AI", "No generated code block available yet.")
            return
        self._apply_generated_code_block(self._last_generated_block)

    def _set_openrouter_key(self):
        text, ok = QInputDialog.getText(
            self, "OpenRouter API Key", "Key:", QLineEdit.Password, self.settings.openrouter_api_key,
        )
        if ok:
            self.settings.openrouter_api_key = text.strip()
            self.settings.save()

    def _set_nvidia_key(self):
        text, ok = QInputDialog.getText(
            self, "NVIDIA API Key", "Key:", QLineEdit.Password, self.settings.nvidia_api_key,
        )
        if ok:
            self.settings.nvidia_api_key = text.strip()
            self.settings.save()

    def _set_openrouter_model(self):
        text, ok = QInputDialog.getText(
            self, "OpenRouter Model", "Model id (e.g. qwen/qwen-2.5-coder-32b-instruct):",
            text=self.settings.openrouter_model,
        )
        if ok and text.strip():
            self.settings.openrouter_model = text.strip()
            self.settings.save()

    def _set_nvidia_model(self):
        text, ok = QInputDialog.getText(
            self, "NVIDIA Model", "Model id (e.g. meta/llama-3.1-70b-instruct):",
            text=self.settings.nvidia_model,
        )
        if ok and text.strip():
            self.settings.nvidia_model = text.strip()
            self.settings.save()

    def _set_gguf_path(self):
        filename, _ = QFileDialog.getOpenFileName(
            self, "Select GGUF Model", str(Path(self.settings.model_path).parent) if self.settings.model_path else "",
            "GGUF Models (*.gguf)",
        )
        if filename:
            self.settings.model_path = filename
            self.settings.save()

    # ──────────────────────────────────────────────────────────────
    def closeEvent(self, event):
        dirty_tabs = [i for i in range(self.editor_tabs.count()) if self.editor_tabs.widget(i).is_dirty]
        if dirty_tabs:
            resp = QMessageBox.question(
                self, "Unsaved changes", "You have unsaved files. Quit anyway?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if resp == QMessageBox.No:
                event.ignore()
                return
        self.output_panel.shutdown()
        self.settings.save()
        event.accept()