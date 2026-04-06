"""Tab 1: job input (URL / file) and Pros/Cons analysis report."""

from __future__ import annotations

import re
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QShowEvent
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from job_app_assistant.document_processor import DocumentExtractionError, DocumentProcessor
from job_app_assistant.gui.app_config import AppConfig, reload_library_feedback_from_disk
from job_app_assistant.job_analyzer import JobAnalysisError, JobAnalysisResult, JobAnalyzer
from job_app_assistant.library_manager import LibraryManager
from job_app_assistant.openai_client import OpenAIClient, OpenAIClientError


def _infer_title_company_from_job_description(job_text: str) -> tuple[str, str]:
    """Role/company from explicit labeled lines in the job description only (not generated text)."""
    title_guess, company_guess = "", ""
    for line in job_text.splitlines()[:80]:
        s = line.strip()
        if not s:
            continue
        mt = re.match(
            r"(?i)^(job\s*title|title|position|role)\s*[:.-]\s*(.+)$",
            s,
        )
        if mt and not title_guess:
            title_guess = mt.group(2).strip().rstrip(".,;")
        mc = re.match(
            r"(?i)^(company|employer|organization)\s*[:.-]\s*(.+)$",
            s,
        )
        if mc and not company_guess:
            company_guess = mc.group(2).strip().rstrip(".,;")

    return title_guess[:200], company_guess[:200]


class UrlFetchWorker(QThread):
    finished_ok = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, url: str) -> None:
        super().__init__()
        self._url = url.strip()

    def run(self) -> None:
        try:
            text = DocumentProcessor().extract_from_url(self._url)
            self.finished_ok.emit(text)
        except DocumentExtractionError as e:
            self.failed.emit(str(e))
        except Exception as e:  # pragma: no cover - network
            self.failed.emit(str(e))


class AnalysisWorker(QThread):
    finished_ok = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(
        self,
        job_text: str,
        library_path: str,
        api_key: str,
        job_title: str,
        company: str,
        session_feedback: str,
    ) -> None:
        super().__init__()
        self._job_text = job_text.strip()
        self._library_path = library_path.strip()
        self._api_key = api_key.strip()
        self._job_title = job_title.strip()
        self._company = company.strip()
        self._session_feedback = session_feedback.strip()

    def run(self) -> None:
        if not self._job_text:
            self.failed.emit("Job description is empty. Load a URL, open a file, or paste text.")
            return
        try:
            client = OpenAIClient(api_key=self._api_key or None)
        except OpenAIClientError as e:
            self.failed.emit(str(e))
            return

        if self._library_path:
            try:
                lib = LibraryManager(self._library_path)
            except (OSError, FileNotFoundError, NotADirectoryError) as e:
                self.failed.emit(f"Library folder: {e}")
                return
        else:
            lib = LibraryManager()

        analyzer = JobAnalyzer(client)
        try:
            result = analyzer.analyze_with_library(
                self._job_text,
                lib,
                job_title=self._job_title or None,
                company=self._company or None,
                session_feedback=self._session_feedback or None,
            )
        except JobAnalysisError as e:
            self.failed.emit(str(e))
            return
        self.finished_ok.emit(result)


class MemoryCorrectionWorker(QThread):
    finished_ok = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, library_path: str, correction: str) -> None:
        super().__init__()
        self._library_path = library_path.strip()
        self._correction = correction.strip()

    def run(self) -> None:
        try:
            lib = LibraryManager(self._library_path)
            lib.update_memory("corrections", self._correction)
        except (OSError, ValueError) as e:
            self.failed.emit(str(e))
            return
        self.finished_ok.emit()


def format_analysis_report(r: JobAnalysisResult) -> str:
    lines: list[str] = []
    lines.append(f"Success rating: {r.success_rating:.0f} / 100")
    lines.append("")
    lines.append("Rationale")
    lines.append(r.rationale.strip())
    lines.append("")
    lines.append("Pros")
    if r.pros:
        for p in r.pros:
            lines.append(f"  • {p}")
    else:
        lines.append("  (none listed)")
    lines.append("")
    lines.append("Cons")
    if r.cons:
        for c in r.cons:
            lines.append(f"  • {c}")
    else:
        lines.append("  (none listed)")
    if r.warnings:
        lines.append("")
        lines.append("Notes")
        for w in r.warnings:
            lines.append(f"  • {w}")
    return "\n".join(lines)


class AnalysisTab(QWidget):
    """URL/file input, optional library path, and Pros/Cons display."""

    def __init__(self, config: AppConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self._url_worker: UrlFetchWorker | None = None
        self._analysis_worker: AnalysisWorker | None = None
        self._memory_correction_worker: MemoryCorrectionWorker | None = None
        self._busy_ops = 0

        self._job_edit = QTextEdit()
        self._job_edit.setPlaceholderText(
            "Paste a job description here, or use “Fetch from URL” / “Open file…” above."
        )
        self._job_edit.setMinimumHeight(220)

        self._url_edit = QLineEdit()
        self._url_edit.setPlaceholderText("https://…")
        self._fetch_btn = QPushButton("Fetch from URL")
        self._fetch_btn.clicked.connect(self._on_fetch_url)

        file_btn = QPushButton("Open file…")
        file_btn.clicked.connect(self._on_open_file)

        url_row = QHBoxLayout()
        url_row.addWidget(QLabel("URL:"))
        url_row.addWidget(self._url_edit, stretch=1)
        url_row.addWidget(self._fetch_btn)
        url_row.addWidget(file_btn)

        job_box = QGroupBox("Job description")
        job_layout = QVBoxLayout(job_box)
        job_layout.addLayout(url_row)
        job_layout.addWidget(self._job_edit)

        self._library_edit = QLineEdit()
        self._library_edit.setPlaceholderText("Folder with resumes & notes (PDF/DOCX/TXT)")
        lib_btn = QPushButton("Browse…")
        lib_btn.clicked.connect(self._on_browse_library)

        lib_row = QHBoxLayout()
        lib_row.addWidget(self._library_edit, stretch=1)
        lib_row.addWidget(lib_btn)

        lib_box = QGroupBox("Personal library")
        lib_layout = QVBoxLayout(lib_box)
        lib_layout.addLayout(lib_row)

        self._title_edit = QLineEdit()
        self._title_edit.setPlaceholderText("Job title (optional)")
        self._company_edit = QLineEdit()
        self._company_edit.setPlaceholderText("Company (optional)")

        meta_grid = QGridLayout()
        meta_grid.addWidget(QLabel("Job title:"), 0, 0)
        meta_grid.addWidget(self._title_edit, 0, 1)
        meta_grid.addWidget(QLabel("Company:"), 1, 0)
        meta_grid.addWidget(self._company_edit, 1, 1)

        meta_box = QGroupBox("Optional context for analysis")
        meta_box.setLayout(meta_grid)

        self._key_edit = QLineEdit()
        self._key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._key_edit.setPlaceholderText("Optional — uses OPENAI_API_KEY if empty")
        self._library_edit.textChanged.connect(self._on_library_text_changed)
        self._key_edit.textChanged.connect(self._on_key_text_changed)

        key_box = QGroupBox("OpenAI API key")
        key_layout = QVBoxLayout(key_box)
        key_layout.addWidget(self._key_edit)

        self._analyze_btn = QPushButton("Run analysis")
        self._analyze_btn.setObjectName("primaryButton")
        self._analyze_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._analyze_btn.setDefault(True)
        self._analyze_btn.clicked.connect(self._on_analyze)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setVisible(False)

        self._report = QTextEdit()
        self._report.setReadOnly(True)
        self._report.setPlaceholderText("Pros, cons, and success rating will appear here.")
        self._report.setMinimumHeight(200)

        report_box = QGroupBox("Analysis report")
        report_layout = QVBoxLayout(report_box)
        report_layout.addWidget(self._report)

        correction_box = QGroupBox("Correct or add context")
        correction_layout = QVBoxLayout(correction_box)
        self._correction_edit = QTextEdit()
        self._correction_edit.setPlaceholderText(
            "e.g. fix a misread skill, nuance for this role, or facts the model should remember"
        )
        self._correction_edit.setMaximumHeight(96)
        self._correction_submit = QPushButton("Submit correction to memory")
        self._correction_submit.clicked.connect(self._on_submit_correction)
        self._correction_status = QLabel("")
        self._correction_status.setStyleSheet("color: #64748b;")
        correction_layout.addWidget(self._correction_edit)
        correction_row = QHBoxLayout()
        correction_row.addStretch(1)
        correction_row.addWidget(self._correction_submit)
        correction_layout.addLayout(correction_row)
        correction_layout.addWidget(self._correction_status)
        report_layout.addWidget(correction_box)

        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.addWidget(job_box)
        layout.addWidget(lib_box)
        layout.addWidget(meta_box)
        layout.addWidget(key_box)
        layout.addWidget(self._analyze_btn)
        layout.addWidget(self._progress)
        layout.addWidget(report_box, stretch=1)

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

        self._sync_edits_from_config()

    def _on_library_text_changed(self, text: str) -> None:
        self._config.library_path = text
        reload_library_feedback_from_disk(self._config)

    def _on_key_text_changed(self, text: str) -> None:
        self._config.api_key = text

    def _sync_edits_from_config(self) -> None:
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

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._sync_edits_from_config()

    def _begin_busy(self) -> None:
        self._busy_ops += 1
        self._progress.setVisible(True)

    def _end_busy(self) -> None:
        self._busy_ops = max(0, self._busy_ops - 1)
        self._progress.setVisible(self._busy_ops > 0)

    def _set_analysis_running(self, running: bool) -> None:
        self._analyze_btn.setEnabled(not running)

    def _on_fetch_url(self) -> None:
        url = self._url_edit.text().strip()
        if not url:
            QMessageBox.warning(self, "URL", "Enter a job posting URL.")
            return
        if self._url_worker and self._url_worker.isRunning():
            return
        self._fetch_btn.setEnabled(False)
        self._begin_busy()
        self._url_worker = UrlFetchWorker(url)
        self._url_worker.finished_ok.connect(self._on_url_ok)
        self._url_worker.failed.connect(self._on_url_fail)
        self._url_worker.finished.connect(self._on_url_thread_done)
        self._url_worker.start()

    def _on_url_ok(self, text: str) -> None:
        self._job_edit.setPlainText(text)

    def _on_url_fail(self, message: str) -> None:
        QMessageBox.critical(self, "Could not load URL", message)

    def _on_url_thread_done(self) -> None:
        self._fetch_btn.setEnabled(True)
        self._end_busy()

    def _on_open_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open job description",
            "",
            "Documents (*.pdf *.docx *.txt);;All files (*.*)",
        )
        if not path:
            return
        try:
            text = DocumentProcessor().extract_from_file(Path(path))
            self._job_edit.setPlainText(text)
        except DocumentExtractionError as e:
            QMessageBox.critical(self, "Could not read file", str(e))

    def _on_browse_library(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select library folder")
        if path:
            self._library_edit.setText(path)

    def _on_analyze(self) -> None:
        if self._analysis_worker and self._analysis_worker.isRunning():
            return
        self._report.clear()
        self._correction_edit.clear()
        self._correction_status.clear()
        self._set_analysis_running(True)
        self._begin_busy()
        self._analysis_worker = AnalysisWorker(
            self._job_edit.toPlainText(),
            self._config.library_path,
            self._config.api_key,
            self._title_edit.text(),
            self._company_edit.text(),
            self._config.feedback_for_prompts(),
        )
        self._analysis_worker.finished_ok.connect(self._on_analysis_ok)
        self._analysis_worker.failed.connect(self._on_analysis_fail)
        self._analysis_worker.finished.connect(self._on_analysis_thread_done)
        self._analysis_worker.start()

    def _on_analysis_ok(self, result: object) -> None:
        assert isinstance(result, JobAnalysisResult)
        self._report.setPlainText(format_analysis_report(result))

    def _on_analysis_fail(self, message: str) -> None:
        QMessageBox.critical(self, "Analysis failed", message)

    def _on_analysis_thread_done(self) -> None:
        self._set_analysis_running(False)
        self._end_busy()

    def _on_submit_correction(self) -> None:
        if self._memory_correction_worker and self._memory_correction_worker.isRunning():
            return
        text = self._correction_edit.toPlainText().strip()
        if not text:
            return
        lib_p = (self._config.library_path or "").strip()
        if not lib_p:
            self._correction_status.setText("Set a library folder above to save corrections.")
            QTimer.singleShot(5000, self._correction_status.clear)
            return
        self._correction_submit.setEnabled(False)
        self._memory_correction_worker = MemoryCorrectionWorker(lib_p, text)
        self._memory_correction_worker.finished_ok.connect(self._on_memory_correction_ok)
        self._memory_correction_worker.failed.connect(self._on_memory_correction_fail)
        self._memory_correction_worker.finished.connect(self._on_memory_correction_thread_done)
        self._memory_correction_worker.start()

    def _on_memory_correction_ok(self) -> None:
        self._correction_edit.clear()
        self._correction_status.setText("Saved to library memory.")
        QTimer.singleShot(4000, self._correction_status.clear)

    def _on_memory_correction_fail(self, message: str) -> None:
        self._correction_status.setText(f"Could not save: {message}")

    def _on_memory_correction_thread_done(self) -> None:
        self._correction_submit.setEnabled(True)
        self._memory_correction_worker = None

    def get_job_description(self) -> str:
        return self._job_edit.toPlainText()

    def apply_inferred_job_metadata_from_job_description(self) -> None:
        """Fill blank title/company from JD label lines only; never overwrites user-entered text."""
        inf_title, inf_company = _infer_title_company_from_job_description(
            self.get_job_description(),
        )
        if not self._title_edit.text().strip() and inf_title:
            self._title_edit.setText(inf_title)
        if not self._company_edit.text().strip() and inf_company:
            self._company_edit.setText(inf_company)

    def get_job_metadata_for_export(self) -> tuple[str, str]:
        """Shared title/company for filenames: same resolution as generation (UI + JD backfill)."""
        self.apply_inferred_job_metadata_from_job_description()
        return self.get_job_title(), self.get_company()

    def get_job_title(self) -> str:
        return self._title_edit.text()

    def get_company(self) -> str:
        return self._company_edit.text()

    def get_posting_url(self) -> str:
        return self._url_edit.text()

    def get_library_path(self) -> str:
        return self._config.library_path

    def get_api_key(self) -> str:
        return self._config.api_key

    def get_session_feedback(self) -> str:
        return self._config.feedback_for_prompts()

    def set_job_title(self, text: str) -> None:
        self._title_edit.setText(text)

    def set_company(self, text: str) -> None:
        self._company_edit.setText(text)

    def set_job_description(self, text: str) -> None:
        self._job_edit.setPlainText(text)

    def get_analysis_report(self) -> str:
        return self._report.toPlainText()

    def set_analysis_report(self, text: str) -> None:
        self._report.setPlainText(text)
