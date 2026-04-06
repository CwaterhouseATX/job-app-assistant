"""Shared application configuration — single mutable object, owned by MainWindow."""

from __future__ import annotations

import json
import os
from pathlib import Path

LIBRARY_FEEDBACK_FILENAME = "_app_feedback_notes.txt"
_MAX_SESSION_FEEDBACK_CHARS = 24_000
_MAX_LIBRARY_FEEDBACK_FILE_CHARS = 48_000


def _feedback_chunk_is_duplicate(existing: str, chunk: str) -> bool:
    c = chunk.strip()
    if not c:
        return True
    for part in (existing or "").split("\n\n"):
        if part.strip() == c:
            return True
    return False


def _trim_feedback(blob: str, max_chars: int) -> str:
    t = (blob or "").strip()
    if len(t) <= max_chars:
        return t
    parts = [p.strip() for p in t.split("\n\n") if p.strip()]
    while parts and len("\n\n".join(parts)) > max_chars:
        parts.pop(0)
    return "\n\n".join(parts)


class AppConfig:
    """Holds user-editable settings. Mutated explicitly (e.g. Settings tab save)."""

    def __init__(self) -> None:
        self._suppress_library_persist: bool = False
        self._library_path: str = ""
        self.remember_library: bool = True
        self.api_key: str = ""
        self.session_feedback: str = ""
        self.library_feedback_notes: str = ""

    @property
    def library_path(self) -> str:
        return self._library_path

    @library_path.setter
    def library_path(self, value: str) -> None:
        v = str(value or "")
        if v == self._library_path:
            return
        self._library_path = v
        if self._suppress_library_persist or not self.remember_library:
            return
        save_settings(self)

    def feedback_for_prompts(self) -> str:
        """Text appended to analysis / generation prompts: file-backed notes or in-memory only."""
        if (self.library_path or "").strip():
            return (self.library_feedback_notes or "").strip()
        return (self.session_feedback or "").strip()

    def append_session_feedback(self, text: str) -> None:
        """Append chat guidance; with a library folder, also persists to LIBRARY_FEEDBACK_FILENAME."""
        t = (text or "").strip()
        if not t:
            return
        lib_p = (self.library_path or "").strip()
        if lib_p:
            if _feedback_chunk_is_duplicate(self.library_feedback_notes, t):
                return
            _persist_feedback_chunk_to_library(self, lib_p, t)
            return
        if _feedback_chunk_is_duplicate(self.session_feedback, t):
            return
        if self.session_feedback:
            self.session_feedback = f"{self.session_feedback.rstrip()}\n\n{t}"
        else:
            self.session_feedback = t
        if len(self.session_feedback) > _MAX_SESSION_FEEDBACK_CHARS:
            self.session_feedback = _trim_feedback(
                self.session_feedback, _MAX_SESSION_FEEDBACK_CHARS
            )


def _persist_feedback_chunk_to_library(config: AppConfig, library_path: str, chunk: str) -> None:
    t = chunk.strip()
    if not t:
        return
    root = Path(library_path)
    if not root.is_dir():
        return
    fp = root / LIBRARY_FEEDBACK_FILENAME
    try:
        existing = fp.read_text(encoding="utf-8").strip() if fp.is_file() else ""
    except OSError:
        existing = ""
    if _feedback_chunk_is_duplicate(existing, t):
        return
    new_body = f"{existing}\n\n{t}".strip() if existing else t
    if len(new_body) > _MAX_LIBRARY_FEEDBACK_FILE_CHARS:
        new_body = _trim_feedback(new_body, _MAX_LIBRARY_FEEDBACK_FILE_CHARS)
    try:
        fp.write_text(new_body + "\n", encoding="utf-8")
    except OSError:
        return
    config.library_feedback_notes = new_body


def reload_library_feedback_from_disk(config: AppConfig) -> None:
    """Load app-owned feedback notes for the current library_path (if any)."""
    p = (config.library_path or "").strip()
    if not p:
        config.library_feedback_notes = ""
        return
    fp = Path(p) / LIBRARY_FEEDBACK_FILENAME
    try:
        config.library_feedback_notes = (
            fp.read_text(encoding="utf-8").strip() if fp.is_file() else ""
        )
    except OSError:
        config.library_feedback_notes = ""
    dangling = (config.session_feedback or "").strip()
    if dangling:
        for chunk in dangling.split("\n\n"):
            c = chunk.strip()
            if c:
                _persist_feedback_chunk_to_library(config, p, c)
        config.session_feedback = ""


def _settings_path() -> Path:
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        root = Path(base) / "job_app_assistant" if base else Path.home() / ".job_app_assistant"
    else:
        xdg = os.environ.get("XDG_DATA_HOME")
        if xdg:
            root = Path(xdg) / "job_app_assistant"
        else:
            root = Path.home() / ".local" / "share" / "job_app_assistant"
    return root / "settings.json"


def load_settings(config: AppConfig) -> None:
    path = _settings_path()
    if not path.is_file():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, UnicodeError):
        return
    if not isinstance(data, dict):
        return
    config._suppress_library_persist = True
    try:
        if "remember_library" in data:
            config.remember_library = bool(data["remember_library"])
        else:
            config.remember_library = True
        raw_lib = str(data.get("library_path") or "")
        config.library_path = raw_lib if config.remember_library else ""
        config.api_key = str(data.get("api_key") or "")
    finally:
        config._suppress_library_persist = False
    reload_library_feedback_from_disk(config)


def save_settings(config: AppConfig) -> None:
    path = _settings_path()
    payload = {
        "library_path": config.library_path,
        "api_key": config.api_key,
        "remember_library": config.remember_library,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError:
        pass
