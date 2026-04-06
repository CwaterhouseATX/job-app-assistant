"""Scan a user library folder and build searchable text context for the AI."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from job_app_assistant.document_processor import DocumentExtractionError, DocumentProcessor

PathLike = str | Path

_CORRECTION_PAT = re.compile(
    r"\b(?:i\s+)?(?:don'?t|do\s+not)\s+have\b|"
    r"\b(?:never|no)\s+(?:used|worked\s+with)\b|"
    r"\blacks?\s+(?:the\s+)?(?:following\s+)?(?:skills?|experience)\b|"
    r"\bnot\s+(?:proficient|experienced|skilled)\s+in\b",
    re.IGNORECASE,
)
_CREDENTIALS_PAT = re.compile(
    r"\b(?:ph\.?d\.?|m\.?s\.?|m\.?b\.?a\.?|b\.?s\.?|b\.?a\.?|associate|bachelor|master|doctorate)\b|"
    r"\b(?:degree|diploma|graduated|certification|certificate|licen[sc]e)\b|"
    r"\bgpa\b|\b(?:university|college)\b",
    re.IGNORECASE,
)
_PREFERENCES_PAT = re.compile(
    r"\b(?:prefer|preference|emphas(?:is|ize)|positioning|highlight|rather\s+than|"
    r"should\s+emphasize|reframe|angle|narrative)\b",
    re.IGNORECASE,
)
_SKILLS_PAT = re.compile(
    r"\bskills?\b|\bproficient\b|\bexperienced\s+(?:in|with)\b|"
    r"\byears?\s+of\s+experience\b|\b(?:strong|deep)\s+(?:background|experience)\s+in\b",
    re.IGNORECASE,
)


def _normalize_memory_key(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().casefold())


def parse_feedback_to_memory(feedback_text: str) -> dict[str, list[str]]:
    """
    Split free-form feedback into structured memory buckets using lightweight heuristics.
    Paragraphs (blank-line separated) are classified independently.
    """
    out: dict[str, list[str]] = {k: [] for k in _DEFAULT_MEMORY}
    text = (feedback_text or "").strip()
    if not text:
        return out
    for chunk in re.split(r"\n\s*\n+", text):
        chunk = chunk.strip()
        if not chunk:
            continue
        key = _classify_feedback_chunk(chunk)
        out[key].append(chunk)
    return out


def _classify_feedback_chunk(chunk: str) -> str:
    if _CORRECTION_PAT.search(chunk):
        return "corrections"
    if _CREDENTIALS_PAT.search(chunk):
        return "credentials_updates"
    if _PREFERENCES_PAT.search(chunk):
        return "preferences"
    if _SKILLS_PAT.search(chunk):
        return "confirmed_skills"
    one_line = "\n" not in chunk and len(chunk) <= 120
    if one_line and re.search(r"[,:+/]", chunk):
        return "confirmed_skills"
    return "preferences"

_SUPPORTED_SUFFIXES = {".pdf", ".docx", ".txt"}
_SKIP_DIR_NAMES = {".git", "__pycache__", ".venv", "venv", "node_modules"}
_LEGACY_FEEDBACK_FILENAME = "_app_feedback_notes.txt"
_SKIP_LIBRARY_FILENAMES = frozenset({_LEGACY_FEEDBACK_FILENAME})
_MEMORY_FILENAME = "memory.json"
_DEFAULT_MEMORY: dict[str, list] = {
    "confirmed_skills": [],
    "corrections": [],
    "preferences": [],
    "credentials_updates": [],
}
_VALID_MEMORY_ENTRY_TYPES = frozenset(_DEFAULT_MEMORY.keys())


@dataclass(frozen=True)
class LibraryDocument:
    """One indexed file under the library root."""

    relative_path: str
    absolute_path: Path
    character_count: int
    modified_timestamp: float


@dataclass(frozen=True)
class SearchHit:
    """A searchable match inside one library document."""

    relative_path: str
    snippet: str
    match_count: int


@dataclass
class ScanResult:
    """Outcome of a library rescan."""

    documents_loaded: int
    errors: list[str] = field(default_factory=list)


class LibraryManager:
    """
    Indexes PDF/DOCX/TXT under a root folder and exposes:

    - A single "personal context" string for prompts (file sections with headers).
    - Keyword search across all indexed text (case-insensitive, all tokens must match).
    """

    def __init__(
        self,
        library_path: PathLike | None = None,
        *,
        processor: DocumentProcessor | None = None,
        recursive: bool = True,
        context_header_template: str = "===== {relative_path} =====",
    ) -> None:
        self._processor = processor or DocumentProcessor()
        self._recursive = recursive
        self._header_template = context_header_template
        self._root: Path | None = None
        self._text_by_rel: dict[str, str] = {}
        self._last_scan = ScanResult(0, [])
        self._memory: dict[str, list] = {k: list(v) for k, v in _DEFAULT_MEMORY.items()}

        if library_path is not None:
            self.set_library_path(library_path)

    @property
    def library_path(self) -> Path | None:
        return self._root

    def set_library_path(self, path: PathLike) -> None:
        root = Path(path).expanduser().resolve()
        if not root.exists():
            raise FileNotFoundError(f"Library folder does not exist: {root}")
        if not root.is_dir():
            raise NotADirectoryError(f"Library path is not a directory: {root}")
        self._root = root
        self.load_memory()
        self.refresh()

    def refresh(self) -> ScanResult:
        """Rescan the library folder and rebuild the in-memory index."""
        if self._root is None:
            self._text_by_rel = {}
            self._last_scan = ScanResult(0, ["No library path set."])
            return self._last_scan

        errors: list[str] = []
        texts: dict[str, str] = {}
        count = 0

        for file_path in self._iter_library_files():
            rel = self._relative_key(file_path)
            try:
                raw = self._processor.extract_from_file(file_path)
            except DocumentExtractionError as e:
                errors.append(f"{rel}: {e}")
                continue
            except OSError as e:
                errors.append(f"{rel}: {e}")
                continue

            texts[rel] = raw
            count += 1

        self._text_by_rel = texts
        self._last_scan = ScanResult(documents_loaded=count, errors=errors)
        return self._last_scan

    @property
    def last_scan(self) -> ScanResult:
        return self._last_scan

    def list_documents(self) -> list[LibraryDocument]:
        """Metadata for each successfully indexed file (after last refresh)."""
        if self._root is None:
            return []

        out: list[LibraryDocument] = []
        for rel, text in sorted(self._text_by_rel.items()):
            abs_path = (self._root / rel).resolve()
            try:
                st = abs_path.stat()
            except OSError:
                continue
            out.append(
                LibraryDocument(
                    relative_path=rel,
                    absolute_path=abs_path,
                    character_count=len(text),
                    modified_timestamp=st.st_mtime,
                )
            )
        return out

    def load_memory(self) -> dict[str, list]:
        """Load persistent user feedback from memory.json under the library root."""
        if self._root is None:
            self._memory = {k: list(v) for k, v in _DEFAULT_MEMORY.items()}
            return self._memory
        path = self._root / _MEMORY_FILENAME
        dirty = False
        if not path.is_file():
            self._memory = {k: list(v) for k, v in _DEFAULT_MEMORY.items()}
            dirty = True
        else:
            try:
                raw = path.read_text(encoding="utf-8")
                data = json.loads(raw) if raw.strip() else {}
            except (OSError, json.JSONDecodeError):
                self._memory = {k: list(v) for k, v in _DEFAULT_MEMORY.items()}
                dirty = True
            else:
                if not isinstance(data, dict):
                    self._memory = {k: list(v) for k, v in _DEFAULT_MEMORY.items()}
                    dirty = True
                else:
                    merged: dict[str, list] = {}
                    for key in _DEFAULT_MEMORY:
                        val = data.get(key, [])
                        merged[key] = list(val) if isinstance(val, list) else []
                    self._memory = merged
        if self._ingest_legacy_feedback_file():
            dirty = True
        if dirty:
            self.save_memory()
        return self._memory

    def save_memory(self) -> None:
        """Write current AI memory to memory.json in the library root."""
        if self._root is None:
            return
        path = self._root / _MEMORY_FILENAME
        payload = {k: list(self._memory.get(k, [])) for k in _DEFAULT_MEMORY}
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def _dedupe_append(self, key: str, value: Any) -> bool:
        """Append one item to a memory list if not a duplicate (normalized). Returns True if appended."""
        if key not in _VALID_MEMORY_ENTRY_TYPES:
            return False
        v = str(value).strip()
        if not v:
            return False
        norm = _normalize_memory_key(v)
        existing = {_normalize_memory_key(str(x)) for x in self._memory.get(key, [])}
        if norm in existing:
            return False
        self._memory.setdefault(key, []).append(v)
        return True

    def _merge_parsed_into_memory(self, parsed: dict[str, list]) -> int:
        """Append parsed bucket items with deduplication. Returns count of new entries."""
        n = 0
        for key in _DEFAULT_MEMORY:
            for item in parsed.get(key, []):
                if self._dedupe_append(key, item):
                    n += 1
        return n

    def _ingest_legacy_feedback_file(self) -> bool:
        """Migrate _app_feedback_notes.txt into structured memory and remove the legacy file."""
        assert self._root is not None
        legacy = self._root / _LEGACY_FEEDBACK_FILENAME
        if not legacy.is_file():
            return False
        changed = False
        try:
            blob = legacy.read_text(encoding="utf-8")
        except OSError:
            blob = ""
        if blob.strip():
            parsed = parse_feedback_to_memory(blob)
            if self._merge_parsed_into_memory(parsed):
                changed = True
        try:
            legacy.unlink()
        except OSError:
            return changed
        return changed

    def append_feedback_text(self, feedback_text: str) -> None:
        """Parse free-form feedback, merge into memory with deduplication, and persist."""
        if self._root is None:
            return
        t = (feedback_text or "").strip()
        if not t:
            return
        parsed = parse_feedback_to_memory(t)
        self._merge_parsed_into_memory(parsed)
        self.save_memory()

    def update_memory(self, entry_type: str, value) -> None:
        """Append one feedback item to a memory bucket and persist (skipped if duplicate)."""
        if entry_type not in _VALID_MEMORY_ENTRY_TYPES:
            raise ValueError(
                f"entry_type must be one of {sorted(_VALID_MEMORY_ENTRY_TYPES)}, got {entry_type!r}"
            )
        if self._dedupe_append(entry_type, value):
            self.save_memory()

    def _format_memory_context(self) -> str:
        lines: list[str] = []
        labels = (
            ("confirmed_skills", "Confirmed skills"),
            ("corrections", "Corrections"),
            ("preferences", "Preferences"),
            ("credentials_updates", "Credentials & education"),
        )
        for key, label in labels:
            items = self._memory.get(key, [])
            if not items:
                continue
            lines.append(f"{label}:")
            for item in items:
                lines.append(f"- {item}")
        if not lines:
            return ""
        header = "===== AI memory (user feedback) ====="
        return f"{header}\n" + "\n".join(lines)

    def build_personal_context(self) -> str:
        """
        One string aggregating all library text, suitable for system/user prompts.

        Each file is wrapped with a clear header so the model can refer to sources.
        """
        parts: list[str] = []
        for rel in sorted(self._text_by_rel.keys()):
            header = self._header_template.format(relative_path=rel)
            body = self._text_by_rel[rel].strip()
            parts.append(f"{header}\n{body}")

        memory_block = self._format_memory_context()
        if memory_block:
            parts.append(memory_block)

        if not parts:
            return ""
        return "\n\n".join(parts)

    def search(self, query: str, *, limit: int = 25) -> list[SearchHit]:
        """
        Case-insensitive search across indexed documents.

        The query is split on whitespace; every token must appear somewhere in the
        document (order-independent). Results are ranked by total substring matches,
        then by path.
        """
        tokens = _tokenize_query(query)
        if not tokens:
            return []

        hits: list[SearchHit] = []
        for rel in sorted(self._text_by_rel.keys()):
            text = self._text_by_rel[rel]
            folded = text.casefold()
            if not all(t in folded for t in tokens):
                continue

            match_count = sum(folded.count(t) for t in tokens)
            pos = _first_match_position(folded, tokens)
            snippet = _make_snippet(text, pos)
            hits.append(
                SearchHit(
                    relative_path=rel,
                    snippet=snippet,
                    match_count=match_count,
                )
            )

        hits.sort(key=lambda h: (-h.match_count, h.relative_path))
        return hits[:limit]

    def get_document_text(self, relative_path: str) -> str | None:
        """Return full text for one indexed relative path, or None if unknown."""
        return self._text_by_rel.get(relative_path)

    def _iter_library_files(self) -> Iterator[Path]:
        assert self._root is not None
        root = self._root

        if self._recursive:
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = [d for d in dirnames if d not in _SKIP_DIR_NAMES and not d.startswith(".")]
                for name in filenames:
                    if name.startswith("."):
                        continue
                    if name in _SKIP_LIBRARY_FILENAMES:
                        continue
                    p = Path(dirpath) / name
                    if p.suffix.lower() in _SUPPORTED_SUFFIXES:
                        yield p
        else:
            for p in root.iterdir():
                if p.is_file() and not p.name.startswith(".") and p.suffix.lower() in _SUPPORTED_SUFFIXES:
                    if p.name in _SKIP_LIBRARY_FILENAMES:
                        continue
                    yield p

    def _relative_key(self, file_path: Path) -> str:
        assert self._root is not None
        try:
            return str(file_path.resolve().relative_to(self._root))
        except ValueError:
            return file_path.name


def _tokenize_query(query: str) -> list[str]:
    q = query.strip()
    if not q:
        return []
    parts = re.split(r"\s+", q)
    return [p.casefold() for p in parts if p]


def _first_match_position(original: str, tokens: list[str]) -> int:
    folded = original.casefold()
    positions: list[int] = []
    for t in tokens:
        idx = folded.find(t)
        if idx >= 0:
            positions.append(idx)
    return min(positions) if positions else 0


def _make_snippet(text: str, center: int, radius: int = 90) -> str:
    t = text.replace("\r\n", "\n")
    if not t:
        return ""
    center = max(0, min(center, len(t) - 1))
    start = max(0, center - radius)
    end = min(len(t), center + radius)
    chunk = t[start:end]
    chunk = re.sub(r"\s+", " ", chunk.replace("\n", " ")).strip()
    prefix = "... " if start > 0 else ""
    suffix = " ..." if end < len(t) else ""
    return prefix + chunk + suffix
