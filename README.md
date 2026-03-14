# GC Solver — Geocaching Mystery Cache Raetsel-Loeser

Automatisierter Raetsel-Loeser fuer Geocaching Mystery Caches. Scrapet das Listing von geocaching.com, extrahiert Text, Bilder und Hints, und laesst Claude Vision den Loesungsversuch machen.

## Features

- **Playwright Scraper** — Auto-Login bei geocaching.com, Cookie-Persistenz, Rate-Limiting
- **GPT-4o Vision** — Analysiert Beschreibungstext + Bilder, erkennt Raetseltypen, schlaegt Koordinaten vor
- **Konfidenz-Bewertung** — Ehrliche Einschaetzung wie sicher die Loesung ist
- **24h Cache** — Doppeltes Scraping vermeiden
- **Retry** — Claude nochmal analysieren lassen ohne neu zu scrapen
- **Bild-Lightbox** — Raetselbilder vergroessern per Klick
- **Dark Theme** — Glassmorphism-UI (#08080f, Gold #c8aa6e)

## Architektur

```
Browser (localhost:8095)
    |
FastAPI (gc-solver)
    |
    +-- Playwright --> geocaching.com (Login + Scrape)
    +-- OpenAI GPT-4o Vision --> Raetsel analysieren + loesen
    +-- SQLite --> Ergebnisse speichern
```

## Setup

```bash
# .env konfigurieren
cp .env.example .env
# GC_USERNAME, GC_PASSWORD, OPENAI_API_KEY eintragen

# Starten
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
| `/solve` | POST | Cache scrapen + Claude loesen |
| `/solve/{gc_code}` | GET | Gespeichertes Ergebnis anzeigen |
| `/api/retry/{id}` | POST | Claude erneut analysieren |
| `/history` | GET | Alle geloesten Raetsel |

## Tech Stack

- **Backend:** FastAPI, SQLAlchemy, Playwright
- **AI:** GPT-4o (Vision) via OpenAI API
- **Frontend:** Tailwind CSS, Alpine.js
- **DB:** SQLite
