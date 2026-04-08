# GC Solver — Geocaching Mystery Cache Raetsel-Loeser

Automatisierter Loesungsassistent fuer Geocaching Mystery Caches. Die App scrapet Listings von geocaching.com, extrahiert Text, Bilder und Hints, reichert bei Bedarf Wikipedia-Kontext an und laesst GPT-4o daraus strukturierte Fakten, Variablen und einen Loesungsversuch ableiten.

## Features

- **Playwright Scraper** — Auto-Login bei geocaching.com, Cookie-Persistenz, Rate-Limiting
- **GPT-4o Vision** — Analysiert Beschreibung, Bilder und Screenshot robust mit Bild-Normalisierung
- **Wikipedia Research Step** — Kontrollierter Recherche-Schritt fuer klare externe Hinweise
- **Strukturierte Faktenernte** — Zeigt relevante Zahlen, Begriffe, externe Fakten und Mapping-Hypothesen
- **Variablen-Aufloesung** — Leitet Kandidaten wie `A = 2` aus den Fakten ab
- **Manueller Fallback** — Offene Variablen koennen per UI eingetragen und erneut gerechnet werden
- **Strukturierte Ableitung** — Finale Loesung wird als JSON erzwungen und im UI aufbereitet
- **Retry** — Erneute Analyse ohne neues Scraping
- **24h Cache** — Doppeltes Scraping vermeiden
- **Dark Theme** — Glassmorphism-UI mit Bild-Lightbox

## Architektur

```text
Browser (localhost:8095)
    |
FastAPI (gc-solver)
    |
    +-- Playwright --> geocaching.com (Login + Scrape)
    +-- OpenAI GPT-4o --> Fakten extrahieren, Variablen aufloesen, Loesung berechnen
    +-- Wikipedia (optional) --> kontrollierter Recherche-Kontext
    +-- SQLite --> Solve-Historie, Fakten, Variablen, strukturierte Loesung
```

## Solve-Flow

1. Cache scrapen
2. Bilder normalisieren und Screenshot erzeugen
3. Optionalen Wikipedia-Kontext laden
4. Strukturierte Fakten extrahieren
5. Variablen aufloesen
6. Finale Ableitung als strukturiertes JSON rechnen
7. Optional offene Variablen manuell eingeben und erneut weiterrechnen

## Setup

```bash
cp .env.example .env
# GC_USERNAME, GC_PASSWORD und OPENAI_API_KEY eintragen

python3 -m uvicorn main:app --host 0.0.0.0 --port 8095
```

## systemd Service

```bash
sudo cp gc-solver.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now gc-solver
```

## Endpoints

| Route | Methode | Beschreibung |
|---|---|---|
| `/` | GET | GC-Code Eingabeformular |
| `/solve` | POST | Cache scrapen und analysieren |
| `/solve/{gc_code}` | GET | Gespeichertes Ergebnis anzeigen |
| `/api/retry/{id}` | POST | Analyse erneut ausfuehren |
| `/api/manual-resolve/{id}` | POST | Mit manuell eingegebenen Variablen weiterrechnen |
| `/history` | GET | Letzte Loesungen anzeigen |

## Auth

- `ADMIN_TOKEN` Env-Variable erforderlich fuer `/api/solve`, `/api/retry`, `/api/manual-resolve`
- Ohne `ADMIN_TOKEN` liefern diese Endpoints `503`
- In `.env` setzen: `ADMIN_TOKEN=<token>`

## Wichtige Grenzen

- Externe Recherche ist aktuell bewusst eng gehalten und auf klare Wikipedia-Hinweise fokussiert.
- Die Variablen-Aufloesung ist noch heuristisch; bei uneindeutigen Film-/Jahresfragen kann ein manueller Override sinnvoll sein.
- Ein Screenshot-Fehler blockiert den Solve nicht mehr; dann laeuft die Analyse ohne Screenshot weiter.

## Tech Stack

- **Backend:** FastAPI, SQLAlchemy, Playwright
- **AI:** GPT-4o via OpenAI API
- **Frontend:** Tailwind CSS, Alpine.js
- **DB:** SQLite
