"""JSON workspace save/load (v1) — application content only, not settings."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

WORKSPACE_VERSION = 1


def _as_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def build_payload(
    *,
    job_title: str,
    company: str,
    job_description: str,
    analysis_report: str,
    hr_research: str,
    resume_draft: str,
    cover_letter_draft: str,
) -> dict[str, Any]:
    return {
        "version": WORKSPACE_VERSION,
        "job_title": job_title,
        "company": company,
        "job_description": job_description,
        "analysis_report": analysis_report,
        "hr_research": hr_research,
        "resume_draft": resume_draft,
        "cover_letter_draft": cover_letter_draft,
    }


def save_workspace(path: str | Path, payload: dict[str, Any]) -> None:
    p = Path(path)
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    p.write_text(text, encoding="utf-8")


def load_workspace(path: str | Path) -> dict[str, str] | None:
    p = Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, UnicodeError):
        return None
    if not isinstance(data, dict):
        return None
    return {
        "job_title": _as_str(data.get("job_title")),
        "company": _as_str(data.get("company")),
        "job_description": _as_str(data.get("job_description")),
        "analysis_report": _as_str(data.get("analysis_report")),
        "hr_research": _as_str(data.get("hr_research")),
        "resume_draft": _as_str(data.get("resume_draft")),
        "cover_letter_draft": _as_str(data.get("cover_letter_draft")),
        "version": _as_str(data.get("version")),
    }
