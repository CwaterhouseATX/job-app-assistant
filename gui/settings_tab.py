"""Settings: edit values and commit to AppConfig on Save (not on every keystroke)."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QShowEvent
from PyQt6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from job_app_assistant.gui.app_config import (
    AppConfig,
    reload_library_feedback_from_disk,
    save_settings,
)


class SettingsTab(QWidget):
    def __init__(self, config: AppConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config = config

        intro = QLabel(
            "Library path and API key are shared with Input & Analysis. "
            "Click Save to copy these fields into the shared configuration."
        )
        intro.setWordWrap(True)

        self._library_edit = QLineEdit()
        self._library_edit.setPlaceholderText("Folder with resumes & notes (PDF/DOCX/TXT)")
        self._library_edit.setText(self._config.library_path)

        library_row = QWidget()
        library_layout = QHBoxLayout(library_row)
        library_layout.setContentsMargins(0, 0, 0, 0)
        library_layout.addWidget(self._library_edit, 1)
        browse_library = QPushButton("Browse…")
        browse_library.clicked.connect(self._on_browse_library)
        library_layout.addWidget(browse_library)

        self._key_edit = QLineEdit()
        self._key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._key_edit.setPlaceholderText("Optional — uses OPENAI_API_KEY if empty")
        self._key_edit.setText(self._config.api_key)

        form = QFormLayout()
        form.addRow("Library folder:", library_row)
        form.addRow("OpenAI API key:", self._key_edit)

        box = QGroupBox("Preferences")
        box_layout = QVBoxLayout(box)
        box_layout.addLayout(form)

        self._save_btn = QPushButton("Save settings")
        self._save_btn.clicked.connect(self._on_save)

        btn_row = QHBoxLayout()
        btn_row.addWidget(self._save_btn)
        btn_row.addStretch(1)

        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.addWidget(intro)
        layout.addWidget(box)
        layout.addLayout(btn_row)
        layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setObjectName("tabScrollArea")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setWidget(inner)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._library_edit.blockSignals(True)
        self._key_edit.blockSignals(True)
        try:
            if self._library_edit.text() != self._config.library_path:
                self._library_edit.setText(self._config.library_path)
            if self._key_edit.text() != self._config.api_key:
                self._key_edit.setText(self._config.api_key)
        finally:
            self._library_edit.blockSignals(False)
            self._key_edit.blockSignals(False)

    def _on_browse_library(self) -> None:
        start = self._library_edit.text().strip() or self._config.library_path
        path = QFileDialog.getExistingDirectory(self, "Select library folder", start)
        if path:
            self._library_edit.setText(path)

    def _on_save(self) -> None:
        self._config.api_key = self._key_edit.text().strip()
        self._config.library_path = self._library_edit.text().strip()
        save_settings(self._config)
        reload_library_feedback_from_disk(self._config)
