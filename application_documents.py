"""Generate resume and cover letter text from job description + personal library (OpenAI)."""

from __future__ import annotations

from typing import Literal

from job_app_assistant.library_manager import LibraryManager
from job_app_assistant.openai_client import OpenAIClient, OpenAIClientError

_MAX_LIBRARY_CHARS = 18_000
_MAX_JD_CHARS = 24_000
_MAX_SESSION_FEEDBACK_CHARS = 8_000

RESUME_SYSTEM = (
    "You draft ATS-friendly resume content as Markdown. "
    "Use clear headings: a single top line for the candidate name, then ## Summary, "
    "## Experience, ## Education, ## Skills (adjust section titles if needed). "
    "Use bullet points under roles. Standard fonts will be applied later; do not use tables or images. "
    "Prioritize and reorder library-backed content to foreground the clearest matches to this posting's "
    "core responsibilities, keywords, and business needs; reframe bullets using JD language only when it "
    "accurately describes the same supported facts. "
    "Ground every fact about the candidate in the candidate library below; "
    "do not infer, fabricate, or overstate employers, titles, dates, metrics, degrees, skills, "
    "responsibilities, or results. "
    "Use the job description only to tailor emphasis and wording—never to invent or guess candidate "
    "history that the library does not explicitly support. "
    "You may present transferable or adjacent experience when the library supports the underlying facts, but "
    "do not upgrade that into direct claims of hands-on implementation, ownership, delivery, or completed "
    "work unless the materials explicitly say so—avoid meta-phrasing like "
    "'demonstrating my ability to implement/build/deliver' (or close variants) when the library does not "
    "state that execution happened. "
    "If information is missing, omit it or say 'Not provided in materials' in Summary only."
)

COVER_LETTER_SYSTEM = (
    "You write a professional cover letter as plain text with short paragraphs (blank line between). "
    "No mailing address block unless present in the library. "
    "Ground every statement about the candidate's background, impact, and qualifications in the "
    "candidate library; do not infer, fabricate, or overstate wins, scope, responsibilities, or credentials. "
    "Use the job description for role and company context and to explain fit, but never as a substitute "
    "for library evidence about what the candidate actually did or has. "
    "Structure the letter around the posting's main responsibilities and needs, leading with library "
    "evidence that maps to those themes and weaving in JD keywords where they genuinely reflect the same facts. "
    "Adjacent or transferable experience is fine when grounded, but do not cast it as direct implementation, "
    "ownership, or completed outcomes unless the library explicitly records that work—avoid rhetorical bridges "
    "(e.g. 'demonstrating my ability to implement…' and similar) that imply execution not stated in the materials. "
    "Be specific to the job description where the evidence allows."
)


class ApplicationDocumentError(Exception):
    """Raised when resume or cover letter generation fails."""


class ApplicationDocumentGenerator:
    """Generate resume and cover letter drafts grounded in the personal library."""

    _ADAPTATION_STRATEGY = (
        "--- ADAPTATION RULES ---\n"
        "IF company_context indicates startup:\n"
        "- Rewrite summary to emphasize:\n"
        "  - ownership, building from zero, adaptability\n"
        "- Prioritize:\n"
        "  - Synack experience\n"
        "  - growth metrics\n"
        "  - cross-functional work\n"
        "- De-emphasize:\n"
        "  - large enterprise structure language\n"
        "- Use verbs:\n"
        "  - built, created, drove, scaled, led from zero\n"
        "\n"
        "IF company_context indicates enterprise:\n"
        "- Rewrite summary to emphasize:\n"
        "  - scale, governance, stakeholder alignment\n"
        "- Prioritize:\n"
        "  - United Airlines experience\n"
        "  - large org coordination\n"
        "  - risk and compliance\n"
        "- Use language:\n"
        "  - scaled, standardized, aligned, governed, optimized\n"
        "\n"
        "CRITICAL:\n"
        "- Summary MUST change between contexts\n"
        "- Bullet point ordering MUST change based on context\n"
        "- Emphasis MUST shift, not just wording\n\n"
    )

    def __init__(self, client: OpenAIClient, *, temperature: float = 0.2) -> None:
        self._client = client
        self._temperature = temperature

    def _company_context_and_strategy_block(self, company_context: str | None) -> str:
        cc = _clip(company_context or "", 12_000).strip()
        company_part = (
            f"--- COMPANY CONTEXT ---\n{cc}\n\n" if cc else ""
        )
        return f"{company_part}{self._ADAPTATION_STRATEGY}"

    def generate_resume(
        self,
        job_description: str,
        library_context: str,
        *,
        job_title: str | None = None,
        company: str | None = None,
        company_context: str | None = None,
        session_feedback: str | None = None,
        mode: Literal["strict", "standard", "executive"] = "standard",
    ) -> str:
        jd = _clip(job_description, _MAX_JD_CHARS)
        lib = _clip(library_context, _MAX_LIBRARY_CHARS)
        if not lib.strip():
            raise ApplicationDocumentError(
                "Personal library is empty. Set a library folder on the first tab and add documents."
            )

        meta = []
        if job_title:
            meta.append(f"Target job title: {job_title.strip()}")
        if company:
            meta.append(f"Target company: {company.strip()}")
        meta_block = "\n".join(meta) + "\n\n" if meta else ""
        company_strategy = self._company_context_and_strategy_block(company_context)
        feedback_block = _session_feedback_block(session_feedback)

        user = (
            f"{meta_block}"
            f"{company_strategy}"
            "--- JOB DESCRIPTION (tailor toward this role) ---\n"
            f"{jd}\n\n"
            "--- CANDIDATE LIBRARY (only source of truth for facts) ---\n"
            f"{lib}\n\n"
            f"{feedback_block}"
            "Write the resume Markdown now. Do not add a disclaimer block; output only the resume."
        )

        try:
            return self._client.complete(
                user,
                system=RESUME_SYSTEM,
                mode=mode,
                temperature=self._temperature,
                max_tokens=4096,
            ).strip()
        except OpenAIClientError as e:
            raise ApplicationDocumentError(str(e)) from e

    def generate_cover_letter(
        self,
        job_description: str,
        library_context: str,
        *,
        job_title: str | None = None,
        company: str | None = None,
        company_context: str | None = None,
        session_feedback: str | None = None,
        mode: Literal["strict", "standard", "executive"] = "standard",
    ) -> str:
        jd = _clip(job_description, _MAX_JD_CHARS)
        lib = _clip(library_context, _MAX_LIBRARY_CHARS)
        if not lib.strip():
            raise ApplicationDocumentError(
                "Personal library is empty. Set a library folder on the first tab and add documents."
            )

        meta = []
        if job_title:
            meta.append(f"Job title: {job_title.strip()}")
        if company:
            meta.append(f"Company: {company.strip()}")
        meta_block = "\n".join(meta) + "\n\n" if meta else ""
        company_strategy = self._company_context_and_strategy_block(company_context)
        feedback_block = _session_feedback_block(session_feedback)

        user = (
            f"{meta_block}"
            f"{company_strategy}"
            "--- JOB DESCRIPTION ---\n"
            f"{jd}\n\n"
            "--- CANDIDATE LIBRARY ---\n"
            f"{lib}\n\n"
            f"{feedback_block}"
            "Write the cover letter now. Output only the letter text."
        )

        try:
            return self._client.complete(
                user,
                system=COVER_LETTER_SYSTEM,
                mode=mode,
                temperature=self._temperature,
                max_tokens=3072,
            ).strip()
        except OpenAIClientError as e:
            raise ApplicationDocumentError(str(e)) from e


def _session_feedback_block(session_feedback: str | None) -> str:
    raw = (session_feedback or "").strip()
    if not raw:
        return ""
    fb = _clip(raw, _MAX_SESSION_FEEDBACK_CHARS)
    return (
        "--- USER SESSION FEEDBACK (authoritative corrections and clarifications from this session; "
        "takes precedence over wording or emphasis inferred from the job description alone; "
        "supplements but does not replace the candidate library as the source of factual claims) ---\n"
        f"{fb}\n\n"
    )


def library_context_from_path(library_path: str) -> str:
    """Load aggregated text from a library folder (empty string if path invalid)."""
    p = (library_path or "").strip()
    if not p:
        return ""
    try:
        lib = LibraryManager(p)
    except (OSError, FileNotFoundError, NotADirectoryError):
        return ""
    return lib.build_personal_context()


def _clip(text: str, max_chars: int) -> str:
    t = (text or "").strip()
    if len(t) <= max_chars:
        return t
    return t[:max_chars] + "\n…"
