import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any
from urllib.parse import quote, unquote, urlparse
from urllib.request import Request, urlopen

from openai import OpenAI

from config import settings

WIKIPEDIA_SUMMARY_API = "https://de.wikipedia.org/api/rest_v1/page/summary/{title}"
WIKIPEDIA_SECTIONS_API = "https://de.wikipedia.org/api/rest_v1/page/mobile-sections/{title}"
USER_AGENT = "gc-solver/1.0 (+https://github.com/AscontiLab/gc-solver)"


@dataclass
class ResearchContext:
    source_type: str = ""
    url: str = ""
    summary: str = ""
    excerpt: str = ""
    reason: str = ""

    def as_result(self) -> dict[str, str]:
        return {
            "research_source_type": self.source_type,
            "research_url": self.url,
            "research_summary": self.summary,
            "research_excerpt": self.excerpt,
        }


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str):
        cleaned = data.strip()
        if cleaned:
            self.parts.append(cleaned)

    def text(self) -> str:
        return " ".join(self.parts)


class ExternalResearch:
    """Kontrollierter Wikipedia-Recherche-Schritt fuer klare externe Hinweise."""

    def __init__(self):
        self.client = OpenAI(api_key=settings.OPENAI_API_KEY)

    def maybe_fetch_context(self, description_text: str, hint: str) -> ResearchContext | None:
        try:
            text = f"{description_text}\n\n{hint}".strip()
            if "wikipedia" not in text.lower():
                return None

            title, reason = self._extract_title_heuristic(text)
            if not title:
                title, reason = self._classify_title_with_llm(description_text, hint)

            if not title:
                return None

            return self._fetch_wikipedia_summary(title, reason, text)
        except Exception:
            return None

    @staticmethod
    def _extract_title_heuristic(text: str) -> tuple[str, str]:
        patterns = [
            r'wikipedia(?:-artikel)?\s+zu\s+[\"“]([^\"”\n]+)[\"”]',
            r'wikipedia(?:-seite)?\s+zu\s+[\"“]([^\"”\n]+)[\"”]',
            r'wiki(?:pedia)?\s*:\s*[\"“]([^\"”\n]+)[\"”]',
            r'wikipedia(?:-artikel)?\s+zu\s+([A-Za-zÄÖÜäöüß0-9 ()-]+?)(?:\s+und\s+|[.!?,;\n]|$)',
            r'wikipedia(?:-seite)?\s+zu\s+([A-Za-zÄÖÜäöüß0-9 ()-]+?)(?:\s+und\s+|[.!?,;\n]|$)',
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                title = match.group(1).strip(" -:()[]")
                if title:
                    return title, "Der Listing-Text verweist direkt auf einen Wikipedia-Artikel."
        return "", ""

    def _classify_title_with_llm(self, description_text: str, hint: str) -> tuple[str, str]:
        prompt = f"""Analysiere, ob fuer dieses Geocache-Raetsel eine Wikipedia-Seite recherchiert werden soll.
Antworte nur als JSON mit den Feldern:
- research_needed: true/false
- wikipedia_title: Titel der Wikipedia-Seite oder leer
- reason: kurze Begruendung

Beschreibung:
{description_text[:3000]}

Hint:
{hint[:1000]}"""

        response = self.client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "Du extrahierst nur strukturierte Recherche-Hinweise fuer Wikipedia."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=200,
            response_format={"type": "json_object"},
        )
        payload = json.loads(response.choices[0].message.content or "{}")
        if not payload.get("research_needed"):
            return "", ""
        return str(payload.get("wikipedia_title") or "").strip(), str(payload.get("reason") or "").strip()

    def _fetch_wikipedia_summary(self, title: str, reason: str, source_text: str) -> ResearchContext | None:
        api_title = self._normalize_title(title)
        if not api_title:
            return None

        data = self._fetch_json(WIKIPEDIA_SUMMARY_API.format(title=quote(api_title, safe="()")))
        sections = self._fetch_json(WIKIPEDIA_SECTIONS_API.format(title=quote(api_title, safe="()")))

        extract_html = str(data.get("extract_html") or "")
        extractor = _TextExtractor()
        extractor.feed(extract_html)
        summary_text = extractor.text()
        article_text = self._extract_section_text(sections)
        excerpt = self._select_relevant_excerpt(
            base_text=summary_text,
            article_text=article_text,
            title=api_title,
            source_text=source_text,
        )[:2200]

        content_urls = data.get("content_urls") or {}
        desktop = content_urls.get("desktop") or {}
        page_url = str(desktop.get("page") or f"https://de.wikipedia.org/wiki/{quote(api_title, safe='()')}")

        return ResearchContext(
            source_type="wikipedia",
            url=page_url,
            summary=str(data.get("title") or api_title),
            excerpt=excerpt,
            reason=reason or "Wikipedia wurde als externe Referenz fuer dieses Raetsel erkannt.",
        )

    @staticmethod
    def _fetch_json(url: str) -> dict[str, Any]:
        req = Request(url, headers={"User-Agent": USER_AGENT})
        with urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))

    @staticmethod
    def _extract_section_text(data: dict[str, Any]) -> str:
        sections = []
        for group in ("lead", "remaining"):
            payload = data.get(group) or {}
            for section in payload.get("sections") or []:
                html = str(section.get("text") or "")
                if not html:
                    continue
                extractor = _TextExtractor()
                extractor.feed(html)
                text = extractor.text()
                if text:
                    sections.append(text)
        return "\n".join(sections)

    @staticmethod
    def _select_relevant_excerpt(base_text: str, article_text: str, title: str, source_text: str) -> str:
        source_numbers = sorted(set(re.findall(r"\d{2,5}", source_text)))
        source_words = {
            word.lower()
            for word in re.findall(r"[A-Za-zÄÖÜäöüß]{4,}", source_text)
            if word.lower() not in {"wikipedia", "artikel", "seite", "cache", "hint"}
        }
        sentences = re.split(r"(?<=[.!?])\s+", article_text)

        preferred: list[str] = []
        keywords = {title.lower(), "monat", "kalender", "tag", "jahr", "gregorianisch"} | source_words
        for sentence in sentences:
            cleaned = sentence.strip()
            if not cleaned:
                continue
            lowered = cleaned.lower()
            if any(keyword in lowered for keyword in keywords):
                preferred.append(cleaned)
                continue
            if any(num in cleaned for num in source_numbers):
                preferred.append(cleaned)

        selected = []
        seen = set()
        for sentence in preferred + re.split(r"(?<=[.!?])\s+", base_text):
            cleaned = sentence.strip()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            selected.append(cleaned)
            if sum(len(s) for s in selected) > 1800:
                break

        if not selected:
            return base_text
        return " ".join(selected)

    @staticmethod
    def _normalize_title(title: str) -> str:
        cleaned = title.strip()
        if not cleaned:
            return ""
        if cleaned.startswith("http://") or cleaned.startswith("https://"):
            parsed = urlparse(cleaned)
            tail = parsed.path.rsplit("/", 1)[-1]
            cleaned = unquote(tail).replace("_", " ")
        return cleaned


external_research = ExternalResearch()
