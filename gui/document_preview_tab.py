"""Tab 2: preview and download generated resume and cover letter (DOCX)."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QStandardPaths, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from job_app_assistant.application_documents import (
    ApplicationDocumentError,
    ApplicationDocumentGenerator,
    library_context_from_path,
)
from job_app_assistant.document_architect import DocumentArchitect, DocumentArchitectError
from job_app_assistant.openai_client import OpenAIClient, OpenAIClientError


def _job_title_safe_for_filename(title: str) -> str:
    """Return title for export basename segments; empty if value looks like prose, not a role name."""
    t = (title or "").strip()
    if not t:
        return ""
    low = t.lower()
    prose_starts = (
        "i am writing",
        "i am applying",
        "i am pleased",
        "dear ",
        "to whom it may",
        "dear hiring",
        "thank you for",
    )
    if any(low.startswith(p) for p in prose_starts):
        return ""
    if low.startswith("i am ") and "express" in low[:100]:
        return ""
    if t.count(",") >= 2 and len(t) > 60:
        return ""
    if len(t) > 120:
        return ""
    return t


class GenerateDocumentsWorker(QThread):
    finished_ok = pyqtSignal(str, str)
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
            self.failed.emit(
                "Job description is empty. Add it on the “Input & Analysis” tab."
            )
            return

        lib_ctx = library_context_from_path(self._library_path)
        if not lib_ctx.strip():
            self.failed.emit(
                "No personal library text found. Set a library folder on the first tab "
                "and ensure it contains PDF, DOCX, or TXT files."
            )
            return

        try:
            client = OpenAIClient(api_key=self._api_key or None)
        except OpenAIClientError as e:
            self.failed.emit(str(e))
            return

        gen = ApplicationDocumentGenerator(client)
        try:
            resume = gen.generate_resume(
                self._job_text,
                lib_ctx,
                job_title=self._job_title or None,
                company=self._company or None,
                session_feedback=self._session_feedback or None,
            )
            cover = gen.generate_cover_letter(
                self._job_text,
                lib_ctx,
                job_title=self._job_title or None,
                company=self._company or None,
                session_feedback=self._session_feedback or None,
            )
        except ApplicationDocumentError as e:
            self.failed.emit(str(e))
            return

        self.finished_ok.emit(resume, cover)


class DocumentPreviewTab(QWidget):
    """
    Shows editable previews for resume and cover letter and exports ATS-friendly DOCX.
    Uses job description, library path, and API key from the analysis tab.
    """

    def __init__(self, analysis_tab: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._analysis = analysis_tab
        self._worker: GenerateDocumentsWorker | None = None

        hint = QLabel(
            "Uses the job description, library folder, optional title/company, and API key from "
            "“Input & Analysis”. Edit the text below before downloading."
        )
        hint.setWordWrap(True)

        self._gen_btn = QPushButton("Generate resume & cover letter")
        self._gen_btn.clicked.connect(self._on_generate)

        self._resume_dl = QPushButton("Download resume (.docx)…")
        self._resume_dl.clicked.connect(lambda: self._on_download(resume=True))
        self._cover_dl = QPushButton("Download cover letter (.docx)…")
        self._cover_dl.clicked.connect(lambda: self._on_download(resume=False))

        btn_row = QHBoxLayout()
        btn_row.addWidget(self._gen_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(self._resume_dl)
        btn_row.addWidget(self._cover_dl)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setVisible(False)

        self._resume_edit = QTextEdit()
        self._resume_edit.setPlaceholderText("Resume preview will appear here after generation.")
        self._resume_edit.setMinimumHeight(200)

        self._cover_edit = QTextEdit()
        self._cover_edit.setPlaceholderText("Cover letter preview will appear here after generation.")
        self._cover_edit.setMinimumHeight(200)

        resume_box = QGroupBox("Resume")
        rv = QVBoxLayout(resume_box)
        rv.addWidget(self._resume_edit)

        cover_box = QGroupBox("Cover letter")
        cv = QVBoxLayout(cover_box)
        cv.addWidget(self._cover_edit)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(resume_box)
        splitter.addWidget(cover_box)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)

        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.addWidget(hint)
        layout.addLayout(btn_row)
        layout.addWidget(self._progress)
        layout.addWidget(splitter, stretch=1)

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

    def _get_analysis_fields(self) -> tuple[str, str, str, str, str]:
        """Reads shared fields from AnalysisTab via duck-typed methods."""
        at = self._analysis
        job = at.get_job_description()
        lib = at.get_library_path()
        key = at.get_api_key()
        title = at.get_job_title()
        company = at.get_company()
        return job, lib, key, title, company

    def _set_generating(self, active: bool) -> None:
        self._progress.setVisible(active)
        self._gen_btn.setEnabled(not active)

    def _on_generate(self) -> None:
        if self._worker and self._worker.isRunning():
            return
        self._analysis.apply_inferred_job_metadata_from_job_description()
        job, lib, key, title, company = self._get_analysis_fields()
        feedback = self._analysis.get_session_feedback()
        self._worker = GenerateDocumentsWorker(
            job, lib, key, title, company, feedback
        )
        self._worker.finished_ok.connect(self._on_generated)
        self._worker.failed.connect(self._on_generate_failed)
        self._worker.finished.connect(self._on_worker_done)
        self._set_generating(True)
        self._worker.start()

    def _on_generated(self, resume: str, cover: str) -> None:
        self._resume_edit.setMarkdown(resume)
        self._cover_edit.setPlainText(cover)
        self._analysis.apply_inferred_job_metadata_from_job_description()

    def _on_generate_failed(self, message: str) -> None:
        QMessageBox.critical(self, "Generation failed", message)

    def _on_worker_done(self) -> None:
        self._set_generating(False)

    def _on_download(self, *, resume: bool) -> None:
        edit = self._resume_edit if resume else self._cover_edit
        text = (edit.toMarkdown() if resume else edit.toPlainText()).strip()
        if not text:
            QMessageBox.warning(
                self,
                "Nothing to save",
                "Generate or paste content first.",
            )
            return

        def _slug(value: str) -> str:
            raw = value.strip()
            if not raw:
                return ""
            raw = raw.replace(",", "")
            cleaned = "".join(
                c if c not in '<>:"/\\|?*' and ord(c) >= 32 else "_" for c in raw
            )
            slug = "_".join(cleaned.split()).lower()
            while "__" in slug:
                slug = slug.replace("__", "_")
            return slug.strip("_")

        job_title, company = self._analysis.get_job_metadata_for_export()
        cpart, tpart = _slug(company), _slug(_job_title_safe_for_filename(job_title))
        kind = "resume" if resume else "cover_letter"
        name_parts = [p for p in (cpart, tpart, kind) if p]
        default_name = (
            f"{'_'.join(name_parts)}.docx"
            if cpart or tpart
            else f"{kind}.docx"
        )
        dl = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.DownloadLocation
        )
        default_dir = Path(dl) if dl else Path.home() / "Downloads"
        default_path = str(default_dir / default_name)

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Word document",
            default_path,
            "Word document (*.docx)",
        )
        if not path:
            return
        if not path.lower().endswith(".docx"):
            path += ".docx"
        try:
            DocumentArchitect().write_from_ai_text(text, path, content_format="auto")
        except DocumentArchitectError as e:
            QMessageBox.critical(self, "Could not save", str(e))
            return
        QMessageBox.information(self, "Saved", f"Wrote:\n{path}")

    def get_resume_text(self) -> str:
        return self._resume_edit.toMarkdown()

    def get_cover_letter_text(self) -> str:
        return self._cover_edit.toPlainText()

    def set_resume_draft(self, text: str) -> None:
        self._resume_edit.setMarkdown(text)

    def set_cover_letter_draft(self, text: str) -> None:
        self._cover_edit.setPlainText(text)
