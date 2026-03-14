import json
from datetime import datetime, timedelta

from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from database import get_db
from models import PuzzleSolve
from scraper import gc_session
from solver import puzzle_solver

router = APIRouter()
templates = Jinja2Templates(directory="templates")

CACHE_HOURS = 24


@router.post("/solve", response_class=HTMLResponse)
async def solve_cache(
    request: Request,
    gc_code: str = Form(...),
    db: Session = Depends(get_db),
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
        return templates.TemplateResponse("result.html", {
            "request": request,
            "solve": existing,
            "images": json.loads(existing.image_paths or "[]"),
            "cached": True,
        })

    try:
        # Scrapen
        cache_data = await gc_session.scrape_cache(gc_code)

        # Claude loesen lassen
        result = puzzle_solver.solve(
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
            solve_status="solved" if result["solved_coords"] != "Nicht ermittelt" else "failed",
        )
        db.add(solve)
        db.commit()
        db.refresh(solve)

        return templates.TemplateResponse("result.html", {
            "request": request,
            "solve": solve,
            "images": cache_data.get("image_paths", []),
            "cached": False,
        })

    except ValueError as e:
        return templates.TemplateResponse("home.html", {
            "request": request,
            "error": str(e),
        })
    except Exception as e:
        return templates.TemplateResponse("home.html", {
            "request": request,
            "error": f"Fehler: {e}",
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

    return templates.TemplateResponse("result.html", {
        "request": request,
        "solve": solve,
        "images": json.loads(solve.image_paths or "[]"),
        "cached": True,
    })


@router.post("/api/retry/{solve_id}", response_class=JSONResponse)
async def retry_solve(solve_id: int, db: Session = Depends(get_db)):
    solve = db.get(PuzzleSolve, solve_id)
    if not solve:
        return JSONResponse({"error": "Nicht gefunden"}, status_code=404)

    try:
        result = puzzle_solver.solve(
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
        solve.solve_status = "solved" if result["solved_coords"] != "Nicht ermittelt" else "failed"
        db.commit()

        return JSONResponse({
            "analysis": result["analysis"],
            "solved_coords": result["solved_coords"],
            "confidence": result["confidence"],
            "status": solve.solve_status,
        })

    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
