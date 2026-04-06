"""Compare a job description to the candidate library: pros, cons, success rating."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from typing import Any

from job_app_assistant.library_manager import LibraryManager
from job_app_assistant.openai_client import OpenAIClient, OpenAIClientError

ANALYSIS_SYSTEM_PROMPT = (
    "You are an expert recruiter assistant. Compare the job description to the "
    "candidate's own materials (resume, notes, etc.). "
    "Use only evidence from the provided job text and library content. "
    "If the library is empty or thin, say what cannot be assessed and avoid guessing. "
    "Do not invent skills, employers, or credentials. "
    "Cons must be material: only include weaknesses that are clearly relevant to succeeding in this role, "
    "grounded in explicit JD requirements or clear gaps between JD and library—omit nitpicks, speculative "
    "concerns, or cons invented to balance the list. Do not add filler cons because there are few cons or "
    "to mirror the number of pros. If USER SESSION FEEDBACK says a point is not a real weakness, treat that "
    "as authoritative unless the job description states it as a required qualification or hard constraint. "
    "Prefer fewer, stronger cons over many weak ones. "
    "Do not generalize total career length into specialized domains. "
    "Only count years within the specific domain evidenced in the library (e.g., cybersecurity, legal, eDiscovery). "
    "Do not inflate experience by combining unrelated career phases. "
    "When mapping adjacent experience (e.g., AI, risk, compliance), label it as transferable or adjacent, "
    "not direct experience. "
    "Respond with a single JSON object only, no markdown fences or commentary."
)

JSON_INSTRUCTIONS = """Return exactly one JSON object with these keys:
- "pros": array of short strings (strengths / alignment from the library; each item must be clearly either (1) direct same-domain experience with explicit evidence, or (2) adjacent/portable fit—prefix adjacent items with a clear marker such as "Adjacent / transferable:" or "Transferable from …" and never describe adjacent fit as direct specialized tenure or sum unrelated years into the job domain)
- "cons": array of short strings (only material gaps: each must tie to something explicit in the job description or a concrete mismatch with the library; no invented cons, no low-impact items, no replacements for removed items; if only one or two real cons exist, return only those—do not pad the list; empty array is allowed if none are material)
- "success_rating": number from 0 to 100 (reflect remaining genuine gaps only—do not lower the score to compensate for a short cons list or to force symmetry with pros)
- "rationale": one short paragraph explaining the rating
"""

JSON_INSTRUCTIONS_CLARIFICATION = """
- "clarification_questions": array of 0 to 2 short strings—include only when the library is empty or critically thin OR confidence in the assessment is low because required candidate facts are missing or ambiguous; each question must target one concrete, answerable gap; use [] when not needed; never more than 2; one-shot only (do not assume follow-up turns)
"""


class JobAnalysisError(Exception):
    """Raised when analysis fails or the model output cannot be parsed."""


@dataclass(frozen=True)
class JobAnalysisResult:
    """Structured job-vs-library analysis."""

    pros: list[str]
    cons: list[str]
    success_rating: float
    rationale: str
    raw_response: str | None = None
    warnings: list[str] = field(default_factory=list)
    clarification_questions: list[str] = field(default_factory=list)


class JobAnalyzer:
    """
    Uses the OpenAI API to produce pros/cons and a 0–100 success rating.

    Pass ``library_context`` from ``LibraryManager.build_personal_context()`` or use
    ``analyze_with_library``.
    """

    def __init__(
        self,
        client: OpenAIClient,
        *,
        analysis_temperature: float = 0.2,
    ) -> None:
        self._client = client
        self._analysis_temperature = analysis_temperature

    def analyze(
        self,
        job_description: str,
        library_context: str,
        *,
        job_title: str | None = None,
        company: str | None = None,
        session_feedback: str | None = None,
        allow_clarification: bool = False,
    ) -> JobAnalysisResult:
        """
        Compare ``job_description`` to ``library_context`` and return structured analysis.

        ``job_description`` should be plain text (e.g. from ``DocumentProcessor``).
        """
        jd = (job_description or "").strip()
        if not jd:
            raise JobAnalysisError("Job description is empty.")

        lib = (library_context or "").strip()
        warnings: list[str] = []
        if not lib:
            warnings.append(
                "No personal library text was provided; analysis is limited to the job description."
            )

        meta_parts = []
        if job_title:
            meta_parts.append(f"Job title (if known): {job_title.strip()}")
        if company:
            meta_parts.append(f"Company (if known): {company.strip()}")
        meta_block = "\n".join(meta_parts) + "\n\n" if meta_parts else ""

        fb = (session_feedback or "").strip()
        feedback_block = (
            "--- USER SESSION FEEDBACK (authoritative corrections and clarifications from this session; "
            "takes precedence over guessed gaps or cons; do not list cons that contradict explicit user corrections; "
            "still do not invent candidate facts the user did not state) ---\n"
            f"{fb}\n\n"
            if fb
            else ""
        )

        user_prompt = (
            f"{meta_block}"
            "--- JOB DESCRIPTION ---\n"
            f"{jd}\n\n"
            "--- CANDIDATE LIBRARY (resumes, notes, etc.) ---\n"
            f"{lib if lib else '(empty)'}\n\n"
            f"{feedback_block}"
            f"{JSON_INSTRUCTIONS}"
            f"{JSON_INSTRUCTIONS_CLARIFICATION if allow_clarification else ''}"
        )

        try:
            raw = self._client.chat(
                [{"role": "user", "content": user_prompt}],
                system=ANALYSIS_SYSTEM_PROMPT,
                temperature=self._analysis_temperature,
                response_format={"type": "json_object"},
                max_tokens=4096,
            )
        except OpenAIClientError as e:
            raise JobAnalysisError(str(e)) from e

        try:
            result = _parse_analysis_json(raw, warnings=warnings, raw_response=raw)
        except JobAnalysisError:
            repaired = _try_extract_json_object(raw)
            if repaired != raw:
                result = _parse_analysis_json(repaired, warnings=warnings, raw_response=raw)
            else:
                raise
        if not allow_clarification:
            result = replace(result, clarification_questions=[])
        return result

    def analyze_with_library(
        self,
        job_description: str,
        library: LibraryManager,
        **kwargs: Any,
    ) -> JobAnalysisResult:
        """Run analysis using the current index from ``LibraryManager``."""
        extra: list[str] = []
        if library.library_path is None:
            extra.append("Library path is not set; context is empty.")
            ctx = ""
        else:
            ctx = library.build_personal_context()
            if not ctx.strip():
                extra.append(
                    f"No supported documents found under {library.library_path}."
                )

        result = self.analyze(job_description, ctx, **kwargs)
        if not extra:
            return result
        return JobAnalysisResult(
            pros=result.pros,
            cons=result.cons,
            success_rating=result.success_rating,
            rationale=result.rationale,
            raw_response=result.raw_response,
            warnings=[*extra, *result.warnings],
            clarification_questions=result.clarification_questions,
        )


def _parse_analysis_json(
    text: str,
    *,
    warnings: list[str],
    raw_response: str | None,
) -> JobAnalysisResult:
    data = json.loads(text)
    if not isinstance(data, dict):
        raise JobAnalysisError("Model returned JSON that is not an object.")

    pros = _as_str_list(data.get("pros"))
    cons = _as_str_list(data.get("cons"))
    rationale = _as_nonempty_str(data.get("rationale"), "rationale")
    rating = _as_rating(data.get("success_rating"))

    clarification_questions = _as_clarification_questions_list(data.get("clarification_questions"))

    return JobAnalysisResult(
        pros=pros,
        cons=cons,
        success_rating=rating,
        rationale=rationale,
        raw_response=raw_response,
        warnings=list(warnings),
        clarification_questions=clarification_questions,
    )


def _as_clarification_questions_list(value: Any) -> list[str]:
    """Parse optional clarification_questions; never raises (max 2 strings)."""
    if value is None:
        return []
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
        elif isinstance(item, (int, float)):
            out.append(str(item))
        if len(out) >= 2:
            break
    return out


def _as_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise JobAnalysisError('Expected "pros" / "cons" to be JSON arrays.')
    out: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
        elif isinstance(item, (int, float)):
            out.append(str(item))
    return out


def _as_nonempty_str(value: Any, key: str) -> str:
    if value is None:
        raise JobAnalysisError(f'Missing "{key}" in JSON.')
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise JobAnalysisError(f'Invalid "{key}" in JSON.')


def _as_rating(value: Any) -> float:
    if value is None:
        raise JobAnalysisError('Missing "success_rating" in JSON.')
    if isinstance(value, bool):
        raise JobAnalysisError('Invalid "success_rating" type.')
    if isinstance(value, (int, float)):
        r = float(value)
        return max(0.0, min(100.0, r))
    raise JobAnalysisError('Invalid "success_rating" in JSON.')


def _try_extract_json_object(text: str) -> str:
    """If the model wrapped JSON in prose or fences, pull out the first {...} block."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        return text[start : end + 1]
    return text
