import base64
import io
import re
from pathlib import Path

from openai import BadRequestError, OpenAI
from PIL import Image, UnidentifiedImageError

from config import settings

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
3. Zeige deinen kompletten Loesungsweg
4. Gib die finalen Koordinaten im Format N/S DD° MM.MMM E/W DDD° MM.MMM an
5. Bewerte deine Konfidenz ehrlich (0-100%)"""

        text_block = f"""## Geocache: {gc_code}

**Gepostete Koordinaten:** {coords}
**Schwierigkeit:** {difficulty}/5

### Beschreibung:
{description_text[:5000]}

### Hint (decodiert):
{hint if hint else 'Kein Hint vorhanden'}

---
Analysiere dieses Raetsel und versuche die finalen Koordinaten zu ermitteln.
Antworte in diesem Format:

## Analyse
[Was fuer ein Raetseltyp ist das? Was faellt dir auf?]

## Loesungsweg
[Schritt-fuer-Schritt Loesung]

## Koordinaten
[Finale Koordinaten im Format N/S DD° MM.MMM E/W DDD° MM.MMM oder "Nicht loesbar" mit Begruendung]

## Konfidenz
[0-100]% — [Begruendung]"""
        attempts = [
            self._build_content(text_block, screenshot_path, image_paths),
            self._build_content(text_block, screenshot_path, []),
            self._build_content(text_block, "", []),
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
                )
                break
            except BadRequestError as exc:
                if getattr(exc, "code", None) != "invalid_image_format":
                    raise
                last_error = exc

        if response is None:
            raise last_error or RuntimeError("OpenAI request failed")

        analysis = response.choices[0].message.content

        # Koordinaten und Konfidenz extrahieren
        solved_coords = self._extract_coords(analysis)
        confidence = self._extract_confidence(analysis)

        return {
            "analysis": analysis,
            "solved_coords": solved_coords,
            "confidence": confidence,
        }

    def _build_content(
        self,
        text_block: str,
        screenshot_path: str,
        image_paths: list[str],
    ) -> list[dict]:
        """Message-Content mit optionalen Bildern aufbauen."""
        content = [{"type": "text", "text": text_block}]

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

    @staticmethod
    def _extract_coords(text: str) -> str:
        """Koordinaten aus Antwort extrahieren."""
        # Format: N 52° 31.123 E 013° 24.456 (oder S/W)
        pattern = r"[NS]\s*\d{1,2}°?\s*\d{1,2}[.,]\d{1,3}\s*[EW]\s*\d{1,3}°?\s*\d{1,2}[.,]\d{1,3}"
        matches = re.findall(pattern, text, re.IGNORECASE)
        if matches:
            return matches[-1].strip()

        # Alternativ: Dezimalformat
        pattern_dec = r"[NS]?\s*-?\d{1,2}[.,]\d{3,6}[°]?\s*[,/]\s*[EW]?\s*-?\d{1,3}[.,]\d{3,6}"
        matches_dec = re.findall(pattern_dec, text, re.IGNORECASE)
        if matches_dec:
            return matches_dec[-1].strip()

        return "Nicht ermittelt"

    @staticmethod
    def _extract_confidence(text: str) -> float:
        """Konfidenz-Prozent aus Antwort extrahieren."""
        conf_section = text.split("## Konfidenz")[-1] if "## Konfidenz" in text else text
        match = re.search(r"(\d{1,3})\s*%", conf_section)
        if match:
            return min(float(match.group(1)), 100.0)
        return 0.0


# Singleton
puzzle_solver = PuzzleSolver()
