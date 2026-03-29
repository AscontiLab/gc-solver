import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from database import engine, Base, ensure_schema
from scraper import gc_session
from routes import home, solve, history

BASE_PREFIX = os.environ.get("BASE_PREFIX", "")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: DB + Browser
    Base.metadata.create_all(bind=engine)
    ensure_schema()
    await gc_session.start()
    yield
    # Shutdown: Browser schliessen
    await gc_session.stop()


app = FastAPI(title="GC Solver", lifespan=lifespan)

app.mount("/static", StaticFiles(directory="static"), name="static")

# Template-Global fuer Base-Prefix (Reverse-Proxy Pfad)
from routes.home import templates as _home_tpl
from routes.solve import templates as _solve_tpl
for _tpl in (_home_tpl, _solve_tpl):
    _tpl.env.globals["config"] = {"BASE_PREFIX": BASE_PREFIX}

app.include_router(home.router)
app.include_router(solve.router)
app.include_router(history.router)
