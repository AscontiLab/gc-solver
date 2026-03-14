from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from database import get_db
from models import PuzzleSolve

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/history", response_class=HTMLResponse)
async def history(request: Request, db: Session = Depends(get_db)):
    solves = (
        db.query(PuzzleSolve)
        .order_by(PuzzleSolve.created_at.desc())
        .limit(50)
        .all()
    )
    return templates.TemplateResponse("history.html", {
        "request": request,
        "solves": solves,
    })
