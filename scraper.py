import asyncio
import io
import json
import os
import re
import time
from pathlib import Path
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from PIL import Image, UnidentifiedImageError

from config import settings

COOKIE_PATH = Path("gc_cookies.json")
IMAGE_DIR = Path("static/images")
SCREENSHOT_DIR = Path("static/screenshots")
SUPPORTED_IMAGE_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
}


class GCSession:
    """Singleton Playwright-Session fuer geocaching.com"""

    def __init__(self):
        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._last_request: float = 0
        self._lock = asyncio.Lock()

    async def start(self):
        """Browser starten und Cookies laden falls vorhanden."""
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=settings.PLAYWRIGHT_HEADLESS,
        )
        self._context = await self._browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        # Cookies laden
        if COOKIE_PATH.exists():
            try:
                cookies = json.loads(COOKIE_PATH.read_text())
                await self._context.add_cookies(cookies)
            except Exception:
                pass

    async def stop(self):
        """Browser schliessen."""
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def _save_cookies(self):
        """Cookies persistent speichern."""
        if self._context:
            cookies = await self._context.cookies()
            COOKIE_PATH.write_text(json.dumps(cookies, indent=2))

    async def _rate_limit(self):
        """Mindestens RATE_LIMIT_SECONDS zwischen Requests."""
        async with self._lock:
            now = time.time()
            wait = settings.RATE_LIMIT_SECONDS - (now - self._last_request)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request = time.time()

    async def _login(self, page: Page):
        """Bei geocaching.com einloggen."""
        if not settings.GC_USERNAME or not settings.GC_PASSWORD:
            raise ValueError("GC_USERNAME und GC_PASSWORD muessen in .env gesetzt sein")

        await page.goto("https://www.geocaching.com/account/signin", wait_until="domcontentloaded", timeout=60000)
        await page.fill("#UsernameOrEmail", settings.GC_USERNAME)
        await page.fill("#Password", settings.GC_PASSWORD)
        await page.click("#SignIn")
        await page.wait_for_load_state("domcontentloaded", timeout=60000)

        # Pruefen ob Login erfolgreich
        if "/account/signin" in page.url.lower():
            raise RuntimeError("Login fehlgeschlagen — Username/Passwort pruefen oder 2FA aktiv?")

        await self._save_cookies()

    async def _ensure_logged_in(self, page: Page) -> bool:
        """Pruefen ob eingeloggt, sonst neu einloggen."""
        await self._rate_limit()
        await page.goto("https://www.geocaching.com/account/dashboard", wait_until="domcontentloaded", timeout=60000)

        if "/account/signin" in page.url.lower():
            await self._login(page)
            return True
        return False

    async def scrape_cache(self, gc_code: str) -> dict:
        """Cache-Listing scrapen und alle Daten extrahieren."""
        gc_code = gc_code.strip().upper()
        if not gc_code.startswith("GC"):
            raise ValueError(f"Ungueltiger GC-Code: {gc_code}")

        page = await self._context.new_page()
        try:
            await self._ensure_logged_in(page)
            await self._rate_limit()

            # Cache-Seite laden
            url = f"https://www.geocaching.com/geocache/{gc_code}"
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)

            # 404 pruefen
            if "cache not found" in (await page.content()).lower() or page.url.endswith("/404"):
                raise ValueError(f"Cache {gc_code} nicht gefunden")

            # Daten extrahieren
            data = {"gc_code": gc_code}

            # Name
            name_el = page.locator("#ctl00_ContentBody_CacheName")
            data["cache_name"] = await name_el.text_content() if await name_el.count() else "Unbekannt"

            # Koordinaten
            coords_el = page.locator("#uxLatLon")
            data["posted_coords"] = await coords_el.text_content() if await coords_el.count() else ""

            # Cache-Typ
            cache_type_el = page.locator("#ctl00_ContentBody_mcd1 .CacheType")
            if await cache_type_el.count():
                data["cache_type"] = await cache_type_el.text_content()
            else:
                # Alternativ aus Breadcrumb oder Title
                data["cache_type"] = "Mystery Cache"

            # D/T Bewertung
            data["difficulty"] = await self._parse_stars(page, "ContentBody_uxLegendScale")
            data["terrain"] = await self._parse_stars(page, "ContentBody_Localize6")

            # Owner
            owner_el = page.locator("#ctl00_ContentBody_mcd1 a[href*='/profile/']")
            if await owner_el.count():
                data["owner"] = await owner_el.first.text_content()
            else:
                data["owner"] = ""

            # Beschreibung HTML + Text
            desc_el = page.locator("#ctl00_ContentBody_LongDescription")
            if await desc_el.count():
                data["description_html"] = await desc_el.inner_html()
                data["description_text"] = await desc_el.inner_text()
            else:
                data["description_html"] = ""
                data["description_text"] = ""

            # Hint (ROT13 decodieren)
            hint_el = page.locator("#div_hint")
            if await hint_el.count():
                hint_raw = await hint_el.text_content()
                data["hint_decoded"] = self._decode_rot13(hint_raw.strip())
            else:
                data["hint_decoded"] = ""

            # Bilder herunterladen
            data["image_paths"] = await self._download_images(page, gc_code)

            # Screenshot der Beschreibung
            screenshot_path = str(SCREENSHOT_DIR / f"{gc_code}.png")
            if await desc_el.count():
                await desc_el.screenshot(path=screenshot_path)
            else:
                await page.screenshot(path=screenshot_path, full_page=False)
            data["screenshot_path"] = screenshot_path

            await self._save_cookies()
            return data

        finally:
            await page.close()

    async def _parse_stars(self, page: Page, element_id: str) -> float:
        """D/T Sterne-Bewertung parsen."""
        try:
            img = page.locator(f"#ctl00_{element_id} img")
            if await img.count():
                alt = await img.first.get_attribute("alt") or ""
                # "3 out of 5" oder "2.5 out of 5"
                match = re.search(r"([\d.]+)\s+out\s+of", alt)
                if match:
                    return float(match.group(1))
                # Deutsch: "3 von 5"
                match = re.search(r"([\d.]+)\s+von", alt)
                if match:
                    return float(match.group(1))
        except Exception:
            pass
        return 0.0

    async def _download_images(self, page: Page, gc_code: str) -> list[str]:
        """Alle Bilder aus der Beschreibung herunterladen."""
        paths = []
        desc_el = page.locator("#ctl00_ContentBody_LongDescription")
        if not await desc_el.count():
            return paths

        images = desc_el.locator("img")
        count = min(await images.count(), 10)  # Max 10 Bilder

        for i in range(count):
            try:
                src = await images.nth(i).get_attribute("src")
                if not src or "smilies" in src.lower() or "icons" in src.lower():
                    continue

                # Absoluter URL
                if src.startswith("//"):
                    src = "https:" + src
                elif src.startswith("/"):
                    src = "https://www.geocaching.com" + src

                # Herunterladen via Playwright
                response = await self._context.request.get(src)
                if response.ok:
                    content_type = (response.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
                    if content_type not in SUPPORTED_IMAGE_TYPES:
                        continue
                    body = await response.body()
                    normalized = self._normalize_image_bytes(body)
                    if not normalized:
                        continue
                    filename = f"{gc_code}_{i}.png"
                    filepath = str(IMAGE_DIR / filename)
                    with open(filepath, "wb") as f:
                        f.write(normalized)
                    paths.append(filepath)
            except Exception:
                continue

        return paths

    @staticmethod
    def _normalize_image_bytes(data: bytes) -> bytes | None:
        """Bilddaten validieren und als PNG normalisieren."""
        try:
            with Image.open(io.BytesIO(data)) as img:
                normalized = img.convert("RGB")
                buffer = io.BytesIO()
                normalized.save(buffer, format="PNG")
                return buffer.getvalue()
        except (OSError, UnidentifiedImageError, ValueError):
            return None

    @staticmethod
    def _decode_rot13(text: str) -> str:
        """ROT13 decodieren."""
        result = []
        for c in text:
            if "a" <= c <= "z":
                result.append(chr((ord(c) - ord("a") + 13) % 26 + ord("a")))
            elif "A" <= c <= "Z":
                result.append(chr((ord(c) - ord("A") + 13) % 26 + ord("A")))
            else:
                result.append(c)
        return "".join(result)


# Singleton-Instanz
gc_session = GCSession()
