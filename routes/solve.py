import json
import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Header, HTTPException, Request, Depends, Form
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from models import PuzzleSolve
from scraper import gc_session
from solver import puzzle_solver

router = APIRouter()
templates = Jinja2Templates(directory="templates")
logger = logging.getLogger(__name__)

CACHE_HOURS = 24


def _require_admin_token(authorization: str | None = Header(None)) -> None:
    """Prueft den Admin-Token fuer kostenverursachende Endpoints."""
    if not settings.ADMIN_TOKEN:
        raise HTTPException(status_code=503, detail="ADMIN_TOKEN nicht konfiguriert")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization-Header fehlt")
    token = authorization.removeprefix("Bearer ").strip()
    if token != settings.ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Ungueltiger Token")


def _parse_json_blob(value: str | None) -> dict:
    try:
        payload = json.loads(value or "{}")
        return payload if isinstance(payload, dict) else {}
    except json.JSONDecodeError:
        return {}


def _template_context(request: Request, solve: PuzzleSolve, images: list[str], cached: bool) -> dict:
    return {
        "request": request,
        "solve": solve,
        "images": images,
        "cached": cached,
        "facts": _parse_json_blob(solve.extracted_facts_json),
        "variable_resolution": _parse_json_blob(solve.variable_resolution_json),
        "structured_solution": _parse_json_blob(solve.structured_solution_json),
    }


def _clean_manual_overrides(payload: dict) -> dict[str, str]:
    cleaned: dict[str, str] = {}
    for key, value in payload.items():
        key = str(key).strip().upper()
        if not key:
            continue
        text = str(value).strip()
        if text:
            cleaned[key] = text
    return cleaned


@router.post("/solve", response_class=HTMLResponse)
async def solve_cache(
    request: Request,
    gc_code: str = Form(...),
    db: Session = Depends(get_db),
    _auth: None = Depends(_require_admin_token),
):
    gc_code = gc_code.strip().upper()

    # Duplikat-Check: weniger als 24h alt?
    cutoff = datetime.utcnow() - timedelta(hours=CACHE_HOURS)
    existing = (
        db.query(PuzzleSolve)
        .filter(PuzzleSolve.gc_code == gc_code, PuzzleSolve.created_at > cutoff)
        .order_by(PuzzleSolve.created_at.desc())
        .first()
    )
    if existing:
        return templates.TemplateResponse(
            "result.html",
            _template_context(request, existing, json.loads(existing.image_paths or "[]"), True),
        )

    try:
        # Scrapen
        cache_data = await gc_session.scrape_cache(gc_code)

        # Claude loesen lassen
        result = await run_in_threadpool(
            puzzle_solver.solve,
            gc_code=gc_code,
            description_text=cache_data.get("description_text", ""),
            hint=cache_data.get("hint_decoded", ""),
            coords=cache_data.get("posted_coords", ""),
            screenshot_path=cache_data.get("screenshot_path", ""),
            image_paths=cache_data.get("image_paths", []),
            difficulty=cache_data.get("difficulty", 0),
        )

        # In DB speichern
        solve = PuzzleSolve(
            gc_code=gc_code,
            cache_name=cache_data.get("cache_name", ""),
            cache_type=cache_data.get("cache_type", ""),
            difficulty=cache_data.get("difficulty", 0),
            terrain=cache_data.get("terrain", 0),
            owner=cache_data.get("owner", ""),
            posted_coords=cache_data.get("posted_coords", ""),
            description_text=cache_data.get("description_text", ""),
            description_html=cache_data.get("description_html", ""),
            hint_decoded=cache_data.get("hint_decoded", ""),
            image_paths=json.dumps(cache_data.get("image_paths", [])),
            screenshot_path=cache_data.get("screenshot_path", ""),
            claude_analysis=result["analysis"],
            solved_coords=result["solved_coords"],
            confidence=result["confidence"],
            research_source_type=result.get("research_source_type", ""),
            research_url=result.get("research_url", ""),
            research_summary=result.get("research_summary", ""),
            research_excerpt=result.get("research_excerpt", ""),
            extracted_facts_json=result.get("extracted_facts_json", ""),
            variable_resolution_json=result.get("variable_resolution_json", ""),
            structured_solution_json=result.get("structured_solution_json", ""),
            solve_status="solved" if result["solved_coords"] != "Nicht ermittelt" else "failed",
        )
        db.add(solve)
        db.commit()
        db.refresh(solve)

        return templates.TemplateResponse(
            "result.html",
            _template_context(request, solve, cache_data.get("image_paths", []), False),
        )

    except ValueError as e:
        return templates.TemplateResponse("home.html", {
            "request": request,
            "error": str(e),
        })
    except Exception as e:
        logger.exception("Unexpected solve error for %s", gc_code)
        return templates.TemplateResponse("home.html", {
            "request": request,
            "error": "Fehler beim Analysieren des Cache-Listings. Bitte spaeter erneut versuchen.",
        })


@router.get("/solve/{gc_code}", response_class=HTMLResponse)
async def view_solve(request: Request, gc_code: str, db: Session = Depends(get_db)):
    gc_code = gc_code.strip().upper()
    solve = (
        db.query(PuzzleSolve)
        .filter(PuzzleSolve.gc_code == gc_code)
        .order_by(PuzzleSolve.created_at.desc())
        .first()
    )
    if not solve:
        return templates.TemplateResponse("home.html", {
            "request": request,
            "error": f"Kein Ergebnis fuer {gc_code} gefunden",
        })

    return templates.TemplateResponse(
        "result.html",
        _template_context(request, solve, json.loads(solve.image_paths or "[]"), True),
    )


@router.post("/api/retry/{solve_id}", response_class=JSONResponse)
async def retry_solve(solve_id: int, db: Session = Depends(get_db), _auth: None = Depends(_require_admin_token)):
    solve = db.get(PuzzleSolve, solve_id)
    if not solve:
        return JSONResponse({"error": "Nicht gefunden"}, status_code=404)

    try:
        result = await run_in_threadpool(
            puzzle_solver.solve,
            gc_code=solve.gc_code,
            description_text=solve.description_text or "",
            hint=solve.hint_decoded or "",
            coords=solve.posted_coords or "",
            screenshot_path=solve.screenshot_path or "",
            image_paths=json.loads(solve.image_paths or "[]"),
            difficulty=solve.difficulty or 0,
        )

        solve.claude_analysis = result["analysis"]
        solve.solved_coords = result["solved_coords"]
        solve.confidence = result["confidence"]
        solve.research_source_type = result.get("research_source_type", "")
        solve.research_url = result.get("research_url", "")
        solve.research_summary = result.get("research_summary", "")
        solve.research_excerpt = result.get("research_excerpt", "")
        solve.extracted_facts_json = result.get("extracted_facts_json", "")
        solve.variable_resolution_json = result.get("variable_resolution_json", "")
        solve.structured_solution_json = result.get("structured_solution_json", "")
        solve.solve_status = "solved" if result["solved_coords"] != "Nicht ermittelt" else "failed"
        db.commit()

        return JSONResponse({
            "analysis": result["analysis"],
            "solved_coords": result["solved_coords"],
            "confidence": result["confidence"],
            "status": solve.solve_status,
            "facts": _parse_json_blob(solve.extracted_facts_json),
            "variable_resolution": _parse_json_blob(solve.variable_resolution_json),
            "structured_solution": _parse_json_blob(solve.structured_solution_json),
        })

    except Exception as e:
        logger.exception("Retry solve failed for id=%s", solve_id)
        return JSONResponse({"error": "Analyse konnte nicht erneut ausgefuehrt werden."}, status_code=500)


@router.post("/api/manual-resolve/{solve_id}", response_class=JSONResponse)
async def manual_resolve(solve_id: int, request: Request, db: Session = Depends(get_db), _auth: None = Depends(_require_admin_token)):
    solve = db.get(PuzzleSolve, solve_id)
    if not solve:
        return JSONResponse({"error": "Nicht gefunden"}, status_code=404)

    payload = await request.json()
    manual_overrides = _clean_manual_overrides(payload if isinstance(payload, dict) else {})
    if not manual_overrides:
        return JSONResponse({"error": "Keine gueltigen Variablenwerte uebergeben"}, status_code=400)

    try:
        result = await run_in_threadpool(
            puzzle_solver.solve_with_manual_variables,
            gc_code=solve.gc_code,
            description_text=solve.description_text or "",
            hint=solve.hint_decoded or "",
            coords=solve.posted_coords or "",
            screenshot_path=solve.screenshot_path or "",
            image_paths=json.loads(solve.image_paths or "[]"),
            difficulty=solve.difficulty or 0,
            facts_payload=_parse_json_blob(solve.extracted_facts_json),
            variable_payload=_parse_json_blob(solve.variable_resolution_json),
            manual_overrides=manual_overrides,
            research_data={
                "research_source_type": solve.research_source_type or "",
                "research_url": solve.research_url or "",
                "research_summary": solve.research_summary or "",
                "research_excerpt": solve.research_excerpt or "",
            },
        )

        solve.claude_analysis = result["analysis"]
        solve.solved_coords = result["solved_coords"]
        solve.confidence = result["confidence"]
        solve.research_source_type = result.get("research_source_type", "")
        solve.research_url = result.get("research_url", "")
        solve.research_summary = result.get("research_summary", "")
        solve.research_excerpt = result.get("research_excerpt", "")
        solve.extracted_facts_json = result.get("extracted_facts_json", "")
        solve.variable_resolution_json = result.get("variable_resolution_json", "")
        solve.structured_solution_json = result.get("structured_solution_json", "")
        solve.solve_status = "solved" if result["solved_coords"] != "Nicht ermittelt" else "failed"
        db.commit()

        return JSONResponse({
            "analysis": result["analysis"],
            "solved_coords": result["solved_coords"],
            "confidence": result["confidence"],
            "status": solve.solve_status,
            "facts": _parse_json_blob(solve.extracted_facts_json),
            "variable_resolution": _parse_json_blob(solve.variable_resolution_json),
            "structured_solution": _parse_json_blob(solve.structured_solution_json),
        })
    except Exception:
        logger.exception("Manual resolve failed for id=%s", solve_id)
        return JSONResponse({"error": "Manuelle Weiterrechnung konnte nicht ausgefuehrt werden."}, status_code=500)
