"""Tab: HR / hiring-contact research from Input & Analysis context."""

from __future__ import annotations

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QGroupBox,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from job_app_assistant.gui.app_config import AppConfig
from job_app_assistant.hr_researcher import HRResearchReport, HRResearcher, HRResearchError
from job_app_assistant.openai_client import OpenAIClient, OpenAIClientError


class HRResearchWorker(QThread):
    finished_ok = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(
        self,
        company: str,
        job_title: str,
        job_description: str,
        api_key: str,
    ) -> None:
        super().__init__()
        self._company = company.strip()
        self._job_title = job_title.strip()
        self._job_description = job_description.strip()
        self._api_key = api_key.strip()

    def run(self) -> None:
        if not self._company:
            self.failed.emit(
                "Company is required. Enter it on the Input & Analysis tab."
            )
            return
        client = None
        try:
            client = OpenAIClient(api_key=self._api_key or None)
        except OpenAIClientError:
            pass
        researcher = HRResearcher(openai_client=client)
        try:
            report = researcher.research(
                self._company,
                job_title=self._job_title or None,
                job_description=self._job_description or None,
            )
        except HRResearchError as e:
            self.failed.emit(str(e))
            return
        except Exception as e:  # pragma: no cover - network / search backends
            self.failed.emit(str(e))
            return
        self.finished_ok.emit(report)


def format_hr_report(report: HRResearchReport) -> str:
    lines: list[str] = []
    lines.append(f"Source tier: {report.tier}")
    if report.queries_tried:
        lines.append("")
        lines.append("Queries tried")
        for q in report.queries_tried:
            lines.append(f"  • {q}")
    lines.append("")
    lines.append("Search results")
    if report.hits:
        for i, h in enumerate(report.hits, 1):
            lines.append(f"  {i}. {h.title}")
            lines.append(f"     {h.url}")
            lines.append(f"     ({h.source_engine}) {h.snippet}")
            lines.append("")
    else:
        lines.append("  (none)")
        lines.append("")
    lines.append("AI insights")
    if report.ai_insights:
        ai = report.ai_insights
        lines.append("  Likely hiring titles")
        for t in ai.likely_hiring_titles or ["(none)"]:
            lines.append(f"    • {t}")
        lines.append("  Likely departments")
        for d in ai.likely_departments or ["(none)"]:
            lines.append(f"    • {d}")
        lines.append("  Suggested search queries")
        for q in ai.search_queries or ["(none)"]:
            lines.append(f"    • {q}")
        lines.append(f"  Disclaimer: {ai.disclaimer}")
    else:
        lines.append("  (none — web results were used or AI fallback unavailable)")
    if report.warnings:
        lines.append("")
        lines.append("Notes")
        for w in report.warnings:
            lines.append(f"  • {w}")
    return "\n".join(lines)


class HRResearchTab(QWidget):
    """Run HRResearcher using company, title, and job description from Analysis tab."""

    def __init__(self, analysis_tab: QWidget, config: AppConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._analysis = analysis_tab
        self._config = config
        self._worker: HRResearchWorker | None = None

        intro = QLabel(
            "Uses company, job title, and job description from Input & Analysis. "
            "Searches public pages for hiring clues; AI fallback uses your OpenAI key when needed."
        )
        intro.setWordWrap(True)

        self._run_btn = QPushButton("Run HR research")
        self._run_btn.clicked.connect(self._on_run)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setVisible(False)

        self._output = QTextEdit()
        self._output.setReadOnly(True)
        self._output.setPlaceholderText("Search results and AI insights will appear here.")
        self._output.setMinimumHeight(280)

        self._copy_btn = QPushButton("Copy results")
        self._copy_btn.setEnabled(False)
        self._copy_btn.clicked.connect(self._on_copy_results)

        out_box = QGroupBox("Results")
        out_layout = QVBoxLayout(out_box)
        out_layout.addWidget(self._copy_btn)
        out_layout.addWidget(self._output)

        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.addWidget(intro)
        layout.addWidget(self._run_btn)
        layout.addWidget(self._progress)
        layout.addWidget(out_box, stretch=1)

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

    def _on_run(self) -> None:
        if self._worker and self._worker.isRunning():
            return
        company = self._analysis.get_company()
        if not (company or "").strip():
            QMessageBox.warning(
                self,
                "Company",
                "Enter a company on the Input & Analysis tab first.",
            )
            return
        self._output.clear()
        self._copy_btn.setEnabled(False)
        self._run_btn.setEnabled(False)
        self._progress.setVisible(True)
        self._worker = HRResearchWorker(
            company,
            self._analysis.get_job_title(),
            self._analysis.get_job_description(),
            self._config.api_key,
        )
        self._worker.finished_ok.connect(self._on_ok)
        self._worker.failed.connect(self._on_fail)
        self._worker.finished.connect(self._on_done)
        self._worker.start()

    def _on_copy_results(self) -> None:
        QApplication.clipboard().setText(self._output.toPlainText())

    def _on_ok(self, report: object) -> None:
        assert isinstance(report, HRResearchReport)
        self._output.setPlainText(format_hr_report(report))
        self._copy_btn.setEnabled(True)
        self._output.moveCursor(QTextCursor.MoveOperation.Start)
        self._output.verticalScrollBar().setValue(0)

    def _on_fail(self, message: str) -> None:
        QMessageBox.critical(self, "HR research failed", message)

    def _on_done(self) -> None:
        self._progress.setVisible(False)
        self._run_btn.setEnabled(True)

    def get_hr_research(self) -> str:
        return self._output.toPlainText()

    def set_hr_research(self, text: str) -> None:
        self._output.setPlainText(text)
        self._copy_btn.setEnabled(bool(text.strip()))
