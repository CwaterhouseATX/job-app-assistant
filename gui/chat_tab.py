"""Tab 3: chat with the model to refine tone, incorporate feedback, and adjust drafts."""

from __future__ import annotations

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import (
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from job_app_assistant.application_documents import library_context_from_path
from job_app_assistant.gui.app_config import AppConfig
from job_app_assistant.openai_client import OpenAIClient, OpenAIClientError

_MAX_JD_CONTEXT = 6_000
_MAX_LIBRARY_CONTEXT = 8_000
_MAX_RESUME_CONTEXT = 6_000
_MAX_COVER_CONTEXT = 4_000
_MAX_SESSION_FEEDBACK_CONTEXT = 6_000
_MAX_HISTORY_MESSAGES = 24


def _clip(text: str, max_chars: int) -> str:
    t = (text or "").strip()
    if len(t) <= max_chars:
        return t
    return t[:max_chars] + "\n…"


def _build_system_prompt(
    analysis_tab: QWidget, preview_tab: QWidget, config: AppConfig
) -> str:
    jd = _clip(analysis_tab.get_job_description(), _MAX_JD_CONTEXT)
    lib = library_context_from_path(config.library_path)
    lib = _clip(lib, _MAX_LIBRARY_CONTEXT)
    resume = _clip(preview_tab.get_resume_text(), _MAX_RESUME_CONTEXT)
    cover = _clip(preview_tab.get_cover_letter_text(), _MAX_COVER_CONTEXT)
    title = analysis_tab.get_job_title().strip()
    company = analysis_tab.get_company().strip()
    meta_lines: list[str] = []
    if title:
        meta_lines.append(f"Target job title: {title}")
    if company:
        meta_lines.append(f"Target company: {company}")
    meta = ("\n".join(meta_lines) + "\n\n") if meta_lines else ""

    sess_fb = _clip(config.feedback_for_prompts(), _MAX_SESSION_FEEDBACK_CONTEXT)
    feedback_section = (
        "--- USER SESSION FEEDBACK (from chat and saved library notes; treat as authoritative corrections) ---\n"
        f"{sess_fb}\n\n"
        if sess_fb.strip()
        else ""
    )

    return (
        "You help refine job-application materials and respond to user feedback in this chat. "
        "Ground every suggestion in the JOB DESCRIPTION and CANDIDATE LIBRARY below. "
        "Do not invent employers, titles, dates, metrics, degrees, or skills. "
        "If something is not in the materials, say so. "
        "When you propose rewritten resume or cover letter text, make it ready to paste and say which section it belongs to.\n\n"
        f"{meta}"
        "--- JOB DESCRIPTION ---\n"
        f"{jd or '(empty)'}\n\n"
        "--- CANDIDATE LIBRARY ---\n"
        f"{lib or '(empty)'}\n\n"
        f"{feedback_section}"
        "--- CURRENT RESUME DRAFT (from Document Preview tab) ---\n"
        f"{resume or '(empty)'}\n\n"
        "--- CURRENT COVER LETTER DRAFT (from Document Preview tab) ---\n"
        f"{cover or '(empty)'}"
    )


class ChatWorker(QThread):
    finished_ok = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(
        self,
        api_key: str,
        messages: list[dict[str, str]],
        system: str,
    ) -> None:
        super().__init__()
        self._api_key = api_key.strip()
        self._messages = messages
        self._system = system

    def run(self) -> None:
        try:
            client = OpenAIClient(api_key=self._api_key or None)
            reply = client.chat(
                self._messages,
                system=self._system,
                temperature=0.2,
                max_tokens=3072,
            )
        except OpenAIClientError as e:
            self.failed.emit(str(e))
            return
        self.finished_ok.emit(reply.strip())


class ChatTab(QWidget):
    """
    Interactive chat: each reply uses up-to-date job description, library text, and
    resume/cover drafts from the other tabs (shared API key from app settings).
    """

    def __init__(
        self,
        analysis_tab: QWidget,
        preview_tab: QWidget,
        config: AppConfig,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._analysis = analysis_tab
        self._preview = preview_tab
        self._config = config
        self._worker: ChatWorker | None = None
        self._history: list[dict[str, str]] = []
        self._last_assistant_reply: str = ""

        intro = QLabel(
            "Ask for tone changes, tighter bullets, or how to address a gap. "
            "Context is refreshed from the Input & Analysis and Document Preview tabs on each send. "
            "API key is shared with Input & Analysis and Settings (or OPENAI_API_KEY if empty)."
        )
        intro.setWordWrap(True)

        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setPlaceholderText("Conversation will appear here.")
        self._log.setMinimumHeight(240)

        log_box = QGroupBox("Conversation")
        log_layout = QVBoxLayout(log_box)
        log_layout.addWidget(self._log)

        self._input = QTextEdit()
        self._input.setPlaceholderText("Type a message… (Shift+Enter for newline)")
        self._input.setMinimumHeight(100)

        self._send_btn = QPushButton("Send")
        self._send_btn.setDefault(True)
        self._send_btn.clicked.connect(self._on_send)

        self._clear_btn = QPushButton("Clear conversation")
        self._clear_btn.clicked.connect(self._on_clear)

        self._copy_btn = QPushButton("Copy last assistant reply")
        self._copy_btn.clicked.connect(self._on_copy_last)
        self._copy_btn.setEnabled(False)

        btn_row = QHBoxLayout()
        btn_row.addWidget(self._send_btn)
        btn_row.addWidget(self._clear_btn)
        btn_row.addWidget(self._copy_btn)
        btn_row.addStretch(1)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setVisible(False)

        input_box = QGroupBox("Your message")
        input_layout = QVBoxLayout(input_box)
        input_layout.addWidget(self._input)

        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.addWidget(intro)
        layout.addWidget(log_box, stretch=2)
        layout.addWidget(input_box)
        layout.addLayout(btn_row)
        layout.addWidget(self._progress)

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

    def _append_log(self, who: str, text: str) -> None:
        block = f"{who}:\n{text.strip()}\n"
        self._log.append(block)

    def _trim_history(self) -> None:
        if len(self._history) > _MAX_HISTORY_MESSAGES:
            self._history = self._history[-_MAX_HISTORY_MESSAGES :]

    def _on_send(self) -> None:
        if self._worker and self._worker.isRunning():
            return
        text = self._input.toPlainText().strip()
        if not text:
            QMessageBox.warning(self, "Message", "Enter a message to send.")
            return
        api_key = self._config.api_key
        try:
            OpenAIClient(api_key=api_key or None)
        except OpenAIClientError as e:
            QMessageBox.critical(self, "API key", str(e))
            return

        self._input.clear()
        self._config.append_session_feedback(text)
        self._append_log("You", text)
        self._history.append({"role": "user", "content": text})
        self._trim_history()

        system = _build_system_prompt(self._analysis, self._preview, self._config)
        self._worker = ChatWorker(api_key, list(self._history), system)
        self._worker.finished_ok.connect(self._on_reply)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(self._on_worker_done)
        self._progress.setVisible(True)
        self._send_btn.setEnabled(False)
        self._worker.start()

    def _on_reply(self, reply: str) -> None:
        self._last_assistant_reply = reply
        self._append_log("Assistant", reply)
        self._history.append({"role": "assistant", "content": reply})
        self._trim_history()
        self._copy_btn.setEnabled(bool(reply.strip()))

    def _on_failed(self, message: str) -> None:
        QMessageBox.critical(self, "Chat failed", message)
        if self._history and self._history[-1].get("role") == "user":
            self._history.pop()

    def _on_worker_done(self) -> None:
        self._progress.setVisible(False)
        self._send_btn.setEnabled(True)

    def _on_clear(self) -> None:
        self._history.clear()
        self._log.clear()
        self._last_assistant_reply = ""
        self._copy_btn.setEnabled(False)

    def _on_copy_last(self) -> None:
        if not self._last_assistant_reply.strip():
            return
        QGuiApplication.clipboard().setText(self._last_assistant_reply)
