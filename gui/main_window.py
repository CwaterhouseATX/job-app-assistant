"""Main application window: tabs for workflow (Phase 3+)."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QIcon, QPixmap
from PyQt6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from job_app_assistant.gui.analysis_tab import AnalysisTab
from job_app_assistant.gui.app_config import AppConfig, load_settings
from job_app_assistant.gui.chat_tab import ChatTab
from job_app_assistant.gui.document_preview_tab import DocumentPreviewTab
from job_app_assistant.gui.hr_research_tab import HRResearchTab
from job_app_assistant.gui.settings_tab import SettingsTab
from job_app_assistant.gui.workspace import build_payload, load_workspace, save_workspace

_APP_STYLESHEET = """
QWidget { font-size: 13px; }
QLabel { color: #1e293b; }
QWidget#centralRoot {
    background-color: #e8ecf0;
}
QWidget#appHeader {
    background-color: #ffffff;
    border: 1px solid #c5ced9;
    border-radius: 8px;
}
QLabel#appSubtitle {
    color: #64748b;
    font-size: 12px;
    padding-top: 2px;
}
QTabWidget#mainTabs::pane {
    border: 1px solid #8b97a8;
    border-radius: 0 6px 6px 6px;
    top: -1px;
    background: #ffffff;
    padding: 2px;
}
QTabWidget#mainTabs QTabBar::tab {
    padding: 10px 18px;
    margin-right: 5px;
    min-width: 5em;
    background: #dde3eb;
    color: #475569;
    border: 1px solid #8b97a8;
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    margin-top: 3px;
}
QTabWidget#mainTabs QTabBar::tab:selected {
    background: #ffffff;
    color: #0f172a;
    border: 1px solid #8b97a8;
    border-bottom: 2px solid #ffffff;
    margin-top: 0;
    padding-top: 11px;
    padding-bottom: 9px;
    font-weight: 600;
}
QTabWidget#mainTabs QTabBar::tab:hover:!selected {
    background: #eceff4;
    color: #334155;
}
QTabWidget#mainTabs QTabBar::tab:!selected {
    border-bottom: 1px solid #8b97a8;
}
QGroupBox {
    font-weight: 600;
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    margin-top: 14px;
    padding-top: 10px;
    padding-bottom: 8px;
    background: #ffffff;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: #334155;
}
QPushButton {
    padding: 6px 14px;
    border-radius: 5px;
    border: 1px solid #cbd5e1;
    background: #f8fafc;
}
QPushButton:hover {
    background: #e2e8f0;
    border-color: #94a3b8;
}
QPushButton:pressed {
    background: #cbd5e1;
}
QPushButton#primaryButton {
    background-color: #1e40af;
    color: #ffffff;
    border: 1px solid #1e3a8a;
    font-weight: 600;
    padding: 10px 22px;
    font-size: 14px;
    min-height: 22px;
}
QPushButton#primaryButton:hover {
    background-color: #1d4ed8;
    border-color: #1e40af;
}
QPushButton#primaryButton:pressed {
    background-color: #1e3a8a;
}
QPushButton#primaryButton:disabled {
    background-color: #94a3b8;
    border-color: #64748b;
    color: #e2e8f0;
}
QLineEdit, QTextEdit {
    border: 1px solid #cbd5e1;
    border-radius: 4px;
    padding: 4px 6px;
    background: #ffffff;
}
QLineEdit:focus, QTextEdit:focus {
    border: 1px solid #3b82f6;
}
QProgressBar {
    border: 1px solid #cbd5e1;
    border-radius: 4px;
    text-align: center;
    min-height: 14px;
    background: #f1f5f9;
}
QProgressBar::chunk {
    background: #3b82f6;
    border-radius: 3px;
}
QScrollArea#tabScrollArea {
    border: none;
    background: transparent;
}
"""


def _resolve_logo_path() -> Path | None:
    root = Path(__file__).resolve().parent.parent / "assets"
    preferred = root / "logo.png"
    if preferred.is_file():
        return preferred
    if not root.is_dir():
        return None
    for ext in (".png", ".jpg", ".jpeg", ".webp"):
        candidates = sorted(root.glob(f"*{ext}"))
        if candidates:
            return candidates[0]
    return None


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("SignalMatch")
        self.resize(960, 780)
        self.setStyleSheet(_APP_STYLESHEET)

        self._config = AppConfig()
        load_settings(self._config)

        tabs = QTabWidget()
        tabs.setObjectName("mainTabs")
        tabs.setDocumentMode(True)

        self._analysis = AnalysisTab(self._config)
        tabs.addTab(self._analysis, "Input & Analysis")
        self._preview = DocumentPreviewTab(self._analysis)
        tabs.addTab(self._preview, "Document Preview")
        self._hr_research = HRResearchTab(self._analysis, self._config)
        tabs.addTab(self._hr_research, "HR Research")
        self._chat = ChatTab(self._analysis, self._preview, self._config)
        tabs.addTab(self._chat, "Chat & Feedback")
        self._settings = SettingsTab(self._config)
        tabs.addTab(self._settings, "Settings")

        logo_path = _resolve_logo_path()
        if logo_path is not None:
            ic = QIcon(str(logo_path))
            self.setWindowIcon(ic)

        header_block = QWidget()
        header_block.setObjectName("appHeader")
        hb_layout = QVBoxLayout(header_block)
        hb_layout.setContentsMargins(16, 14, 16, 14)
        hb_layout.setSpacing(10)

        header_row = QHBoxLayout()
        header_row.setSpacing(12)
        wordmark_ok = False
        if logo_path is not None:
            pix = QPixmap(str(logo_path))
            if not pix.isNull():
                logo_lbl = QLabel()
                logo_lbl.setPixmap(
                    pix.scaledToHeight(
                        48,
                        mode=Qt.TransformationMode.SmoothTransformation,
                    )
                )
                logo_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                header_row.addWidget(logo_lbl, alignment=Qt.AlignmentFlag.AlignLeft)
                wordmark_ok = True
        if not wordmark_ok:
            title_lbl = QLabel("SignalMatch")
            title_font = title_lbl.font()
            title_font.setPointSize(max(title_font.pointSize(), 15))
            title_font.setBold(True)
            title_lbl.setFont(title_font)
            title_lbl.setStyleSheet("color: #0f172a; letter-spacing: -0.3px;")
            header_row.addWidget(title_lbl)
        header_row.addStretch(1)

        subtitle = QLabel("Job fit analysis and application drafting")
        subtitle.setObjectName("appSubtitle")
        subtitle.setWordWrap(True)

        hb_layout.addLayout(header_row)
        hb_layout.addWidget(subtitle)

        central = QWidget()
        central.setObjectName("centralRoot")
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(12, 10, 12, 10)
        central_layout.setSpacing(12)
        central_layout.addWidget(header_block)
        central_layout.addWidget(tabs, stretch=1)
        self.setCentralWidget(central)

        file_menu = self.menuBar().addMenu("&File")
        act_save = QAction("Save Application…", self)
        act_save.triggered.connect(self._on_save_application)
        file_menu.addAction(act_save)
        act_open = QAction("Open Application…", self)
        act_open.triggered.connect(self._on_open_application)
        file_menu.addAction(act_open)

    def _on_save_application(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save application",
            str(Path.home() / "application_workspace.json"),
            "JSON workspace (*.json);;All files (*.*)",
        )
        if not path:
            return
        low = path.lower()
        if not low.endswith(".json"):
            path += ".json"
        payload = build_payload(
            job_title=self._analysis.get_job_title(),
            company=self._analysis.get_company(),
            job_description=self._analysis.get_job_description(),
            analysis_report=self._analysis.get_analysis_report(),
            hr_research=self._hr_research.get_hr_research(),
            resume_draft=self._preview.get_resume_text(),
            cover_letter_draft=self._preview.get_cover_letter_text(),
        )
        try:
            save_workspace(path, payload)
        except OSError as e:
            QMessageBox.critical(self, "Could not save", str(e))
            return
        QMessageBox.information(self, "Saved", f"Wrote:\n{path}")

    def _on_open_application(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open application",
            str(Path.home()),
            "JSON workspace (*.json);;All files (*.*)",
        )
        if not path:
            return
        data = load_workspace(path)
        if data is None:
            QMessageBox.critical(
                self,
                "Invalid workspace",
                "The file could not be read or is not valid JSON.",
            )
            return
        self._analysis.set_job_title(data["job_title"])
        self._analysis.set_company(data["company"])
        self._analysis.set_job_description(data["job_description"])
        self._analysis.set_analysis_report(data["analysis_report"])
        self._hr_research.set_hr_research(data["hr_research"])
        self._preview.set_resume_draft(data["resume_draft"])
        self._preview.set_cover_letter_draft(data["cover_letter_draft"])
