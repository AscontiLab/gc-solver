from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from database import engine, Base, ensure_schema
from scraper import gc_session
from routes import home, solve, history


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

app.include_router(home.router)
app.include_router(solve.router)
app.include_router(history.router)
