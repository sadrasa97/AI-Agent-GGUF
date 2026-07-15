from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QFormLayout,
    QComboBox,
    QLineEdit,
    QPushButton,
    QHBoxLayout,
    QGroupBox,
    QDialogButtonBox,
    QFileDialog,
)

from config.settings import Settings


class ModelSettingsDialog(QDialog):
    """Unified model/backend settings dialog."""

    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Model Settings")
        self.resize(640, 360)

        root = QVBoxLayout(self)

        backend_form = QFormLayout()
        self.backend_combo = QComboBox()
        self.backend_combo.addItems(["gguf", "openrouter", "nvidia"])
        self.backend_combo.setCurrentText(self.settings.backend)
        backend_form.addRow("Active backend", self.backend_combo)
        root.addLayout(backend_form)

        gguf_group = QGroupBox("Local GGUF")
        gguf_form = QFormLayout(gguf_group)
        gguf_path_row = QHBoxLayout()
        self.gguf_path_edit = QLineEdit(self.settings.model_path)
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_gguf)
        gguf_path_row.addWidget(self.gguf_path_edit, 1)
        gguf_path_row.addWidget(browse_btn)
        gguf_form.addRow("Model path", gguf_path_row)
        root.addWidget(gguf_group)

        openrouter_group = QGroupBox("OpenRouter")
        openrouter_form = QFormLayout(openrouter_group)
        self.openrouter_key_edit = QLineEdit(self.settings.openrouter_api_key)
        self.openrouter_key_edit.setEchoMode(QLineEdit.Password)
        self.openrouter_model_edit = QLineEdit(self.settings.openrouter_model)
        openrouter_form.addRow("API key", self.openrouter_key_edit)
        openrouter_form.addRow("Model", self.openrouter_model_edit)
        root.addWidget(openrouter_group)

        nvidia_group = QGroupBox("NVIDIA")
        nvidia_form = QFormLayout(nvidia_group)
        self.nvidia_key_edit = QLineEdit(self.settings.nvidia_api_key)
        self.nvidia_key_edit.setEchoMode(QLineEdit.Password)
        self.nvidia_model_edit = QLineEdit(self.settings.nvidia_model)
        nvidia_form.addRow("API key", self.nvidia_key_edit)
        nvidia_form.addRow("Model", self.nvidia_model_edit)
        root.addWidget(nvidia_group)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save_and_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _browse_gguf(self):
        start_dir = ""
        if self.gguf_path_edit.text().strip():
            start_dir = str(Path(self.gguf_path_edit.text().strip()).expanduser().parent)
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Select GGUF Model",
            start_dir,
            "GGUF Models (*.gguf)",
        )
        if filename:
            self.gguf_path_edit.setText(filename)

    def _save_and_accept(self):
        self.settings.backend = self.backend_combo.currentText().strip() or self.settings.backend
        self.settings.model_path = self.gguf_path_edit.text().strip()
        self.settings.openrouter_api_key = self.openrouter_key_edit.text().strip()
        self.settings.openrouter_model = self.openrouter_model_edit.text().strip() or self.settings.openrouter_model
        self.settings.nvidia_api_key = self.nvidia_key_edit.text().strip()
        self.settings.nvidia_model = self.nvidia_model_edit.text().strip() or self.settings.nvidia_model
        self.settings.save()
        self.accept()
