import base64
import io
import json
from pathlib import Path
from typing import Any

from openai import BadRequestError, OpenAI
from PIL import Image, UnidentifiedImageError

from config import settings
from research import external_research

MAX_IMAGES = 5


class PuzzleSolver:
    """OpenAI GPT-4o Vision fuer Geocaching-Raetsel."""

    def __init__(self):
        self.client = OpenAI(api_key=settings.OPENAI_API_KEY)

    def solve(
        self,
        gc_code: str,
        description_text: str,
        hint: str,
        coords: str,
        screenshot_path: str,
        image_paths: list[str],
        difficulty: float,
    ) -> dict:
        """Raetsel analysieren und Koordinaten vorschlagen."""

        system_prompt = """Du bist ein Geocaching-Experte und Raetsel-Loeser. Du analysierst Mystery-Cache-Raetsel
und versuchst, die finalen Koordinaten zu ermitteln.

Du kennst alle gaengigen Raetseltypen:
- Verschluesselungen (Caesar, ROT13, Morse, Binaer, Hex, ASCII, Braille)
- Zahlenraetsel (Quersummen, Primzahlen, Fibonacci, Buchstabenwerte A=1/Z=26)
- Bilderraetsel (versteckte Zahlen, Symbole, Farbcodes, Steganografie-Hinweise)
- Wissensraetsel (Geschichte, Geografie, Naturwissenschaft)
- Logik-Puzzle (Sudoku, Kreuzwortraetsel, Nonogramme)
- Koordinaten-Berechnungen (Formeln mit Variablen A-Z)

Wichtige Regeln:
1. Analysiere ALLE Hinweise: Text, Bilder, Hint, und gepostete Koordinaten
2. Die geposteten Koordinaten sind NICHT die finalen — sie sind oft ein Startpunkt oder enthalten den Grad/Minute-Prefix
3. Arbeite strukturiert und faktenbasiert
4. Gib finale Koordinaten nur an, wenn sie sich belastbar ableiten lassen
5. Bewerte deine Konfidenz ehrlich (0-100%)
6. Wenn externer Recherche-Kontext mitgeliefert wurde, nutze ihn konkret statt nur auf die Quelle zu verweisen
7. Sage NICHT, dass man die externe Quelle erst noch besuchen, nachschlagen oder durchsuchen soll, wenn ihr Inhalt bereits mitgeliefert wurde
8. Wenn externer Kontext vorhanden ist, nenne die relevanten Fakten daraus explizit im Loesungsweg
9. Wenn im Listing konkrete Zahlen genannt oder markiert sind, vergleiche sie explizit mit Fakten aus dem externen Kontext
10. Wenn strukturierte Fakten mitgeliefert wurden, behandle sie als primaere Arbeitsgrundlage fuer deine Schlussfolgerung"""

        research_context = external_research.maybe_fetch_context(description_text, hint)
        research_block = self._research_block(research_context)
        facts_payload = self._extract_facts(
            gc_code=gc_code,
            description_text=description_text,
            hint=hint,
            coords=coords,
            difficulty=difficulty,
            research_block=research_block,
        )
        facts_block = self._facts_block(facts_payload)

        text_block = f"""## Geocache: {gc_code}

**Gepostete Koordinaten:** {coords}
**Schwierigkeit:** {difficulty}/5

### Beschreibung:
{description_text[:5000]}

### Hint (decodiert):
{hint if hint else 'Kein Hint vorhanden'}

---
Analysiere dieses Raetsel und versuche die finalen Koordinaten zu ermitteln.
Antworte AUSSCHLIESSLICH als JSON mit diesen Feldern:
- analysis: kurze faktenbasierte Einordnung
- used_facts: Liste der wirklich verwendeten Fakten
- reasoning_steps: Liste kurzer, konkreter Schlussfolgerungsschritte
- candidate_coordinate_logic: Liste moeglicher Koordinaten- oder Zahlenlogiken
- final_coords: finale Koordinaten im Format N/S DD° MM.MMM E/W DDD° MM.MMM oder leer
- why_not_solved: falls keine harte Loesung moeglich ist, kurze Begruendung
- confidence: Zahl 0-100
- confidence_reason: kurze Begruendung der Konfidenz"""
        if research_block:
            text_block += """

WICHTIG:
- Externer Recherche-Kontext wurde bereits fuer dich geladen.
- Verweise nicht darauf, dass man Wikipedia oder eine andere Quelle erst noch oeffnen soll.
- Arbeite mit dem gelieferten Inhalt und nenne die daraus verwendeten Fakten konkret."""
        if facts_block:
            text_block += """

WICHTIG:
- Es wurden bereits strukturierte Fakten aus Listing und Recherche extrahiert.
- Arbeite primaer mit diesen Fakten.
- Wenn keine belastbare Loesung moeglich ist, begruende anhand der Fakten, was noch fehlt."""
        attempts = [
            self._build_content(text_block, screenshot_path, image_paths, research_block, facts_block),
            self._build_content(text_block, screenshot_path, [], research_block, facts_block),
            self._build_content(text_block, "", [], research_block, facts_block),
        ]

        response = None
        last_error = None
        for content in attempts:
            try:
                response = self.client.chat.completions.create(
                    model=settings.OPENAI_MODEL,
                    max_tokens=4096,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": content},
                    ],
                    response_format={"type": "json_object"},
                )
                break
            except BadRequestError as exc:
                if getattr(exc, "code", None) != "invalid_image_format":
                    raise
                last_error = exc

        if response is None:
            raise last_error or RuntimeError("OpenAI request failed")

        solution_payload = json.loads(response.choices[0].message.content or "{}")
        analysis = self._solution_text(solution_payload)
        solved_coords = self._extract_solution_coords(solution_payload)
        confidence = self._extract_solution_confidence(solution_payload)

        return {
            "analysis": analysis,
            "solved_coords": solved_coords,
            "confidence": confidence,
            "extracted_facts_json": json.dumps(facts_payload, ensure_ascii=True),
            "structured_solution_json": json.dumps(solution_payload, ensure_ascii=True),
            **(research_context.as_result() if research_context else {
                "research_source_type": "",
                "research_url": "",
                "research_summary": "",
                "research_excerpt": "",
            }),
        }

    def _build_content(
        self,
        text_block: str,
        screenshot_path: str,
        image_paths: list[str],
        research_block: str,
        facts_block: str,
    ) -> list[dict]:
        """Message-Content mit optionalen Bildern aufbauen."""
        content = [{"type": "text", "text": text_block}]
        if research_block:
            content.append({"type": "text", "text": research_block})
        if facts_block:
            content.append({"type": "text", "text": facts_block})

        if screenshot_path and Path(screenshot_path).exists():
            image_block = self._image_block(screenshot_path)
            if image_block:
                content.append(image_block)

        for img_path in image_paths[:MAX_IMAGES]:
            if Path(img_path).exists():
                image_block = self._image_block(img_path)
                if image_block:
                    content.append(image_block)

        return content

    def _extract_facts(
        self,
        gc_code: str,
        description_text: str,
        hint: str,
        coords: str,
        difficulty: float,
        research_block: str,
    ) -> dict[str, Any]:
        """Strukturierte Faktenernte vor dem eigentlichen Solve."""
        prompt = f"""Extrahiere aus diesem Geocache-Raetsel nur belastbare Fakten.
Antworte ausschliesslich als JSON mit diesen Feldern:
- puzzle_type: kurzer Typname
- referenced_numbers: Liste relevanter Zahlen aus Listing, Bildbeschreibung oder Hint
- referenced_terms: Liste relevanter Begriffe oder Themen
- coordinate_prefix: erkennbare Teile aus den geposteten Koordinaten oder leer
- external_facts: Liste konkreter Fakten aus dem externen Kontext, die fuer die Loesung relevant sein koennten
- candidate_mappings: Liste kurzer Hypothesen, wie Zahlen/Begriffe zusammenhaengen koennten
- missing_links: Liste dessen, was fuer eine harte Loesung noch fehlt

GC-Code: {gc_code}
Gepostete Koordinaten: {coords}
Schwierigkeit: {difficulty}/5

Beschreibung:
{description_text[:4000]}

Hint:
{hint[:1000]}
"""
        if research_block:
            prompt += f"""

Externer Recherche-Kontext:
{research_block[:3000]}
"""

        response = self.client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "Du extrahierst nur belastbare Fakten fuer ein Geocache-Raetsel. Keine Loesung, keine Anweisungen zum Nachschlagen.",
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=500,
            response_format={"type": "json_object"},
        )
        payload = json.loads(response.choices[0].message.content or "{}")
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _facts_block(payload: dict[str, Any]) -> str:
        if not payload:
            return ""
        parts = ["## Strukturierte Fakten"]

        def add_list(label: str, key: str):
            values = payload.get(key) or []
            if isinstance(values, list) and values:
                parts.append(f"{label}:")
                for value in values[:8]:
                    parts.append(f"- {value}")

        puzzle_type = str(payload.get("puzzle_type") or "").strip()
        if puzzle_type:
            parts.append(f"Raetseltyp: {puzzle_type}")

        coordinate_prefix = str(payload.get("coordinate_prefix") or "").strip()
        if coordinate_prefix:
            parts.append(f"Koordinaten-Prefix: {coordinate_prefix}")

        add_list("Relevante Zahlen", "referenced_numbers")
        add_list("Relevante Begriffe", "referenced_terms")
        add_list("Externe Fakten", "external_facts")
        add_list("Moegliche Zuordnungen", "candidate_mappings")
        add_list("Noch offene Luecken", "missing_links")

        return "\n".join(parts)

    @staticmethod
    def _solution_text(payload: dict[str, Any]) -> str:
        sections = []

        analysis = str(payload.get("analysis") or "").strip()
        if analysis:
            sections.extend(["## Analyse", analysis])

        used_facts = payload.get("used_facts") or []
        if isinstance(used_facts, list) and used_facts:
            sections.extend(["", "## Verwendete Fakten"])
            for fact in used_facts[:8]:
                sections.append(f"- {fact}")

        reasoning_steps = payload.get("reasoning_steps") or []
        if isinstance(reasoning_steps, list) and reasoning_steps:
            sections.extend(["", "## Loesungsweg"])
            for index, step in enumerate(reasoning_steps[:8], start=1):
                sections.append(f"{index}. {step}")

        candidate_coordinate_logic = payload.get("candidate_coordinate_logic") or []
        if isinstance(candidate_coordinate_logic, list) and candidate_coordinate_logic:
            sections.extend(["", "## Moegliche Koordinatenlogik"])
            for item in candidate_coordinate_logic[:6]:
                sections.append(f"- {item}")

        why_not_solved = str(payload.get("why_not_solved") or "").strip()
        if why_not_solved:
            sections.extend(["", "## Offene Punkte", why_not_solved])

        confidence_reason = str(payload.get("confidence_reason") or "").strip()
        confidence = payload.get("confidence")
        if confidence_reason or confidence is not None:
            prefix = ""
            try:
                if confidence is not None:
                    prefix = f"{int(float(confidence))}% — "
            except (TypeError, ValueError):
                prefix = ""
            sections.extend(["", "## Konfidenz", f"{prefix}{confidence_reason}".strip()])

        return "\n".join(section for section in sections if section is not None).strip()

    @staticmethod
    def _extract_solution_coords(payload: dict[str, Any]) -> str:
        final_coords = str(payload.get("final_coords") or "").strip()
        if not final_coords or final_coords.lower() in {"nicht loesbar", "nicht lösbar", "unknown", "none"}:
            return "Nicht ermittelt"
        return final_coords

    @staticmethod
    def _extract_solution_confidence(payload: dict[str, Any]) -> float:
        try:
            return min(max(float(payload.get("confidence", 0) or 0), 0.0), 100.0)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _research_block(research_context) -> str:
        if not research_context:
            return ""
        return f"""## Externe Quelle
Typ: {research_context.source_type}
URL: {research_context.url}
Kurzfassung: {research_context.summary}
Warum diese Quelle: {research_context.reason}

## Externer Kontext
{research_context.excerpt[:2000]}"""

    @staticmethod
    def _image_block(path: str) -> dict | None:
        """Bild als base64 Content-Block fuer OpenAI Vision."""
        data = PuzzleSolver._normalize_image_bytes(path)
        if not data:
            return None
        b64 = base64.standard_b64encode(data).decode("utf-8")

        return {
            "type": "image_url",
            "image_url": {
                "url": f"data:image/png;base64,{b64}",
            },
        }

    @staticmethod
    def _normalize_image_bytes(path: str) -> bytes | None:
        """Bild robust laden und als sauberes PNG re-encodieren."""
        try:
            with Image.open(path) as img:
                normalized = img.convert("RGB")
                buffer = io.BytesIO()
                normalized.save(buffer, format="PNG")
                return buffer.getvalue()
        except (OSError, UnidentifiedImageError, ValueError):
            return None

# Singleton
puzzle_solver = PuzzleSolver()
