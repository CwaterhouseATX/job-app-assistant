"""Find public hiring-contact clues: DuckDuckGo search, optional SerpApi, then AI fallback."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import urlparse

import requests

from job_app_assistant.openai_client import OpenAIClient, OpenAIClientError

try:
    from ddgs import DDGS
except ImportError:  # pragma: no cover - legacy package name
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        DDGS = None  # type: ignore[misc, assignment]

SERPAPI_SEARCH_URL = "https://serpapi.com/search.json"
DEFAULT_MAX_RESULTS = 8
MIN_WEB_HITS = 1

FALLBACK_SYSTEM_PROMPT = (
    "You assist with job-application research when live web search is unavailable or empty. "
    "Using only the job description and company name, suggest typical hiring-manager job titles "
    "and departments or functions that often own this kind of role. "
    "Do not invent real people's names, email addresses, phone numbers, or LinkedIn URLs. "
    "Respond with a single JSON object only, no markdown."
)

FALLBACK_JSON_INSTRUCTIONS = """JSON keys:
- "likely_hiring_titles": array of strings (e.g. "Director of Engineering", "Talent Acquisition Partner")
- "likely_departments": array of strings (e.g. "People Operations", "R&D")
- "search_queries": array of 2–4 example web/LinkedIn search phrases the candidate could paste into a search box
- "disclaimer": one short sentence that these are generic suggestions, not verified contacts
"""


class HRResearchError(Exception):
    """Invalid input or configuration for HR research."""


@dataclass(frozen=True)
class WebSearchHit:
    """One public search result (title, URL, snippet)."""

    title: str
    url: str
    snippet: str
    source_engine: Literal["duckduckgo", "serpapi"]


@dataclass(frozen=True)
class AIResearchInsights:
    """Structured guesses when web search does not return useful public listings."""

    likely_hiring_titles: list[str]
    likely_departments: list[str]
    search_queries: list[str]
    disclaimer: str
    raw_response: str | None = None


@dataclass(frozen=True)
class HRResearchReport:
    """Outcome of HR / hiring-contact research."""

    tier: Literal["duckduckgo", "serpapi", "ai_fallback"]
    queries_tried: list[str]
    hits: list[WebSearchHit]
    ai_insights: AIResearchInsights | None
    warnings: list[str] = field(default_factory=list)


class HRResearcher:
    """
    Tiered research:

    1. **DuckDuckGo** via ``ddgs`` / ``duckduckgo_search`` (no API key).
    2. **SerpApi** if ``SERPAPI_API_KEY`` is set or ``serpapi_key`` is passed.
    3. **AI fallback** using ``OpenAIClient`` and the job description to suggest departments/titles
       and example search queries (no invented people or contact details).
    """

    def __init__(
        self,
        openai_client: OpenAIClient | None = None,
        *,
        serpapi_key: str | None = None,
        max_results: int = DEFAULT_MAX_RESULTS,
        min_web_hits: int = MIN_WEB_HITS,
        ddg_timeout: float | None = 20.0,
    ) -> None:
        self._client = openai_client
        self._serpapi_key = serpapi_key or os.environ.get("SERPAPI_API_KEY")
        self._max_results = max(1, max_results)
        self._min_hits = max(1, min_web_hits)
        self._ddg_timeout = ddg_timeout

    def research(
        self,
        company: str,
        *,
        job_title: str | None = None,
        job_description: str | None = None,
    ) -> HRResearchReport:
        """
        Search for public pages that may identify recruiters, hiring managers, or TA contacts.

        This does **not** scrape LinkedIn in violation of terms; it only uses public search APIs
        and returns search snippets and links for manual review.
        """
        name = (company or "").strip()
        if not name:
            raise HRResearchError("company is required.")

        queries = _build_queries(name, job_title)
        warnings: list[str] = []
        tried: list[str] = []

        if DDGS is None:
            warnings.append(
                "ddgs/duckduckgo_search is not installed; skipping DuckDuckGo. "
                "Install with: pip install ddgs"
            )
        else:
            for q in queries:
                tried.append(q)
                hits = self._search_ddg(q)
                if len(hits) >= self._min_hits:
                    return HRResearchReport(
                        tier="duckduckgo",
                        queries_tried=list(tried),
                        hits=hits[: self._max_results],
                        ai_insights=None,
                        warnings=list(warnings),
                    )
        if not tried:
            tried.extend(queries)

        if self._serpapi_key:
            for q in queries:
                if q not in tried:
                    tried.append(q)
                hits = self._search_serpapi(q)
                if len(hits) >= self._min_hits:
                    return HRResearchReport(
                        tier="serpapi",
                        queries_tried=list(dict.fromkeys(tried)),
                        hits=hits[: self._max_results],
                        ai_insights=None,
                        warnings=list(warnings),
                    )
        else:
            warnings.append("SerpApi key not set; skipped Google-backed search (SERPAPI_API_KEY).")

        insights, w2 = self._ai_fallback(name, job_title, job_description)
        warnings.extend(w2)
        return HRResearchReport(
            tier="ai_fallback",
            queries_tried=list(dict.fromkeys(tried)),
            hits=[],
            ai_insights=insights,
            warnings=warnings,
        )

    def _search_ddg(self, query: str) -> list[WebSearchHit]:
        if DDGS is None:
            return []
        hits: list[WebSearchHit] = []
        seen: set[str] = set()
        try:
            kwargs: dict[str, Any] = {"max_results": self._max_results}
            if self._ddg_timeout is not None:
                kwargs["timeout"] = int(self._ddg_timeout)

            with DDGS() as ddgs:
                stream = ddgs.text(query, **kwargs)
                for item in stream:
                    url = (item.get("href") or item.get("url") or "").strip()
                    title = (item.get("title") or "").strip()
                    body = (item.get("body") or item.get("snippet") or "").strip()
                    if not url or not _http_url(url):
                        continue
                    key = _normalize_url_key(url)
                    if key in seen:
                        continue
                    seen.add(key)
                    hits.append(
                        WebSearchHit(
                            title=title or "(no title)",
                            url=url,
                            snippet=body,
                            source_engine="duckduckgo",
                        )
                    )
        except Exception:
            return hits
        return hits

    def _search_serpapi(self, query: str) -> list[WebSearchHit]:
        if not self._serpapi_key:
            return []
        params = {
            "engine": "google",
            "q": query,
            "api_key": self._serpapi_key,
            "num": min(self._max_results, 10),
        }
        try:
            r = requests.get(SERPAPI_SEARCH_URL, params=params, timeout=40)
            r.raise_for_status()
            data = r.json()
        except (requests.RequestException, ValueError, json.JSONDecodeError):
            return []

        organic = data.get("organic_results") or []
        hits: list[WebSearchHit] = []
        for row in organic:
            url = (row.get("link") or "").strip()
            title = (row.get("title") or "").strip()
            snippet = (row.get("snippet") or row.get("snippet_highlighted_words") or "")
            if isinstance(snippet, list):
                snippet = " ".join(str(x) for x in snippet)
            snippet = str(snippet).strip()
            if not url:
                continue
            hits.append(
                WebSearchHit(
                    title=title or "(no title)",
                    url=url,
                    snippet=snippet,
                    source_engine="serpapi",
                )
            )
        return hits

    def _ai_fallback(
        self,
        company: str,
        job_title: str | None,
        job_description: str | None,
    ) -> tuple[AIResearchInsights | None, list[str]]:
        warn: list[str] = []
        if self._client is None:
            warn.append(
                "Web search returned no usable results. Pass OpenAIClient(...) for AI fallback "
                "suggestions (titles, departments, example queries)."
            )
            return None, warn

        jd = (job_description or "").strip()
        if len(jd) > 12000:
            jd = jd[:12000] + "\n…"

        user = (
            f"Company: {company}\n"
            f"Role title (if known): {job_title or '(unknown)'}\n\n"
            f"Job description:\n{jd or '(not provided)'}\n\n"
            f"{FALLBACK_JSON_INSTRUCTIONS}"
        )

        try:
            raw = self._client.chat(
                [{"role": "user", "content": user}],
                system=FALLBACK_SYSTEM_PROMPT,
                temperature=0.2,
                response_format={"type": "json_object"},
                max_tokens=1200,
            )
        except OpenAIClientError as e:
            warn.append(f"AI fallback failed: {e}")
            return None, warn

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            repaired = _extract_json_object(raw)
            try:
                data = json.loads(repaired)
            except json.JSONDecodeError:
                warn.append("AI fallback returned invalid JSON.")
                return None, warn

        if not isinstance(data, dict):
            warn.append("AI fallback JSON was not an object.")
            return None, warn

        titles = _as_str_list(data.get("likely_hiring_titles"))
        depts = _as_str_list(data.get("likely_departments"))
        queries = _as_str_list(data.get("search_queries"))
        disc = data.get("disclaimer")
        disclaimer = disc.strip() if isinstance(disc, str) and disc.strip() else (
            "These are generic research suggestions, not verified contacts."
        )

        insights = AIResearchInsights(
            likely_hiring_titles=titles,
            likely_departments=depts,
            search_queries=queries,
            disclaimer=disclaimer,
            raw_response=raw,
        )
        return insights, warn


def _build_queries(company: str, job_title: str | None) -> list[str]:
    """Ordered list of search queries to try."""
    c = company.strip()
    jt = (job_title or "").strip()
    out: list[str] = []
    if jt:
        out.append(f'"{jt}" hiring manager OR recruiter {c}')
    out.append(f"{c} talent acquisition OR recruiting site:linkedin.com/in")
    out.append(f"{c} hiring manager recruiter LinkedIn")
    out.append(f'"{c}" "people operations" OR recruiting')
    # dedupe preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for q in out:
        if q not in seen:
            seen.add(q)
            unique.append(q)
    return unique


def _http_url(url: str) -> bool:
    try:
        p = urlparse(url)
        return p.scheme in ("http", "https") and bool(p.netloc)
    except Exception:
        return False


def _normalize_url_key(url: str) -> str:
    p = urlparse(url)
    host = (p.netloc or "").lower()
    path = (p.path or "").rstrip("/")
    return f"{host}{path}"


def _as_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for x in value:
        if isinstance(x, str) and x.strip():
            out.append(x.strip())
    return out


def _extract_json_object(text: str) -> str:
    t = text.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", t, re.IGNORECASE)
    if m:
        t = m.group(1).strip()
    a, b = t.find("{"), t.rfind("}")
    if a >= 0 and b > a:
        return t[a : b + 1]
    return t

