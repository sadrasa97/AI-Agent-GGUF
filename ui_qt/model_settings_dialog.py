from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QApplication,
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
    QCheckBox,
    QMessageBox,
)
from PySide6.QtCore import Qt

from config.settings import Settings
from tools.model_manager import ensure_default_gguf_model


class ModelSettingsDialog(QDialog):
    """Unified model/backend settings dialog."""

    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Model Settings")
        self.resize(760, 620)

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
        self.auto_download_gguf_checkbox = QCheckBox("Auto-download default GGUF model when GGUF backend is selected")
        self.auto_download_gguf_checkbox.setChecked(self.settings.auto_download_default_gguf)
        gguf_form.addRow("Default model", self.auto_download_gguf_checkbox)
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

        voice_group = QGroupBox("Qwen Voice (ASR)")
        voice_form = QFormLayout(voice_group)

        self.asr_backend_combo = QComboBox()
        self.asr_backend_combo.addItems(["local", "api"])
        self.asr_backend_combo.setCurrentText((self.settings.asr_backend or "local").strip().lower())
        voice_form.addRow("ASR backend", self.asr_backend_combo)

        qwen_voice_row = QHBoxLayout()
        self.qwen_voice_model_edit = QLineEdit(self.settings.qwen_voice_model_path)
        qwen_voice_browse_btn = QPushButton("Browse...")
        qwen_voice_browse_btn.clicked.connect(self._browse_qwen_voice_model)
        qwen_voice_row.addWidget(self.qwen_voice_model_edit, 1)
        qwen_voice_row.addWidget(qwen_voice_browse_btn)
        voice_form.addRow("Qwen Voice GGUF model", qwen_voice_row)

        qwen_mmproj_row = QHBoxLayout()
        self.qwen_voice_mmproj_edit = QLineEdit(getattr(self.settings, "qwen_voice_mmproj_path", ""))
        qwen_mmproj_browse_btn = QPushButton("Browse...")
        qwen_mmproj_browse_btn.clicked.connect(self._browse_qwen_voice_mmproj)
        qwen_mmproj_row.addWidget(self.qwen_voice_mmproj_edit, 1)
        qwen_mmproj_row.addWidget(qwen_mmproj_browse_btn)
        voice_form.addRow("Qwen Voice mmproj", qwen_mmproj_row)

        self.asr_model_edit = QLineEdit(self.settings.asr_model_path)
        voice_form.addRow("Fallback ASR model", self.asr_model_edit)

        self.asr_language_edit = QLineEdit(self.settings.asr_language)
        self.asr_language_edit.setPlaceholderText("Auto")
        voice_form.addRow("Language", self.asr_language_edit)

        self.asr_sample_rate_edit = QLineEdit(str(self.settings.asr_sample_rate))
        voice_form.addRow("Sample rate", self.asr_sample_rate_edit)

        self.asr_api_url_edit = QLineEdit(self.settings.asr_api_url)
        voice_form.addRow("ASR API URL", self.asr_api_url_edit)

        self.asr_api_key_edit = QLineEdit(self.settings.asr_api_key)
        self.asr_api_key_edit.setEchoMode(QLineEdit.Password)
        voice_form.addRow("ASR API key", self.asr_api_key_edit)

        root.addWidget(voice_group)

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

    def _browse_qwen_voice_model(self):
        start_dir = ""
        current = self.qwen_voice_model_edit.text().strip()
        if current:
            start_dir = str(Path(current).expanduser().parent)
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Select Qwen Voice GGUF Model",
            start_dir,
            "GGUF Models (*.gguf)",
        )
        if filename:
            self.qwen_voice_model_edit.setText(filename)

    def _browse_qwen_voice_mmproj(self):
        start_dir = ""
        current = self.qwen_voice_mmproj_edit.text().strip()
        if current:
            start_dir = str(Path(current).expanduser().parent)
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Select Qwen Voice mmproj GGUF",
            start_dir,
            "GGUF Models (*.gguf)",
        )
        if filename:
            self.qwen_voice_mmproj_edit.setText(filename)

    def _save_and_accept(self):
        self.settings.backend = self.backend_combo.currentText().strip() or self.settings.backend
        self.settings.model_path = self.gguf_path_edit.text().strip()
        self.settings.auto_download_default_gguf = self.auto_download_gguf_checkbox.isChecked()
        self.settings.openrouter_api_key = self.openrouter_key_edit.text().strip()
        self.settings.openrouter_model = self.openrouter_model_edit.text().strip() or self.settings.openrouter_model
        self.settings.nvidia_api_key = self.nvidia_key_edit.text().strip()
        self.settings.nvidia_model = self.nvidia_model_edit.text().strip() or self.settings.nvidia_model
        self.settings.asr_backend = self.asr_backend_combo.currentText().strip() or "local"
        self.settings.qwen_voice_model_path = self.qwen_voice_model_edit.text().strip()
        self.settings.qwen_voice_mmproj_path = self.qwen_voice_mmproj_edit.text().strip()
        self.settings.asr_model_path = self.asr_model_edit.text().strip()
        self.settings.asr_language = self.asr_language_edit.text().strip() or "Auto"
        self.settings.asr_api_url = self.asr_api_url_edit.text().strip()
        self.settings.asr_api_key = self.asr_api_key_edit.text().strip()
        try:
            self.settings.asr_sample_rate = max(8000, int(self.asr_sample_rate_edit.text().strip() or "16000"))
        except ValueError:
            QMessageBox.warning(self, "Invalid sample rate", "Sample rate must be a number (e.g. 16000).")
            return

        needs_default_download = (
            self.settings.backend == "gguf"
            and self.settings.auto_download_default_gguf
            and not Path(self.settings.model_path).expanduser().is_file()
        )
        if needs_default_download:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                model_path, downloaded = ensure_default_gguf_model(self.settings)
            except Exception as exc:  # noqa: BLE001
                QMessageBox.warning(
                    self,
                    "GGUF Download Failed",
                    f"Could not download default GGUF model.\n\n{exc}",
                )
                return
            finally:
                QApplication.restoreOverrideCursor()
            self.gguf_path_edit.setText(str(model_path))
            if downloaded:
                QMessageBox.information(
                    self,
                    "GGUF Download Complete",
                    f"Downloaded default GGUF model to:\n{model_path}",
                )

        self.settings.save()
        self.accept()
