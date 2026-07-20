import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db import init_db
from app.scheduler import create_scheduler

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    scheduler = create_scheduler()
    scheduler.start()
    app.state.scheduler = scheduler
    yield
    scheduler.shutdown()


app = FastAPI(title="Wakacje Deals Tracker", lifespan=lifespan)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
