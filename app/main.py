import logging
from contextlib import asynccontextmanager
from datetime import date

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import db, scheduler
from app.constants import BOARD_OPTIONS, COUNTRIES, DEPARTURE_AIRPORTS, REASON_LABELS
from app.db import init_db
from app.models import SearchCriteria
from app.scheduler import create_scheduler

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    sched = create_scheduler()
    sched.start()
    app.state.scheduler = sched
    yield
    sched.shutdown()


app = FastAPI(title="Wakacje Deals Tracker", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


# --- profile / lista głowna ---------------------------------------------


@app.get("/")
def index(request: Request):
    rows = []
    for profile_row in db.list_profiles():
        criteria = SearchCriteria.from_row(profile_row)
        offers = db.get_offers_for_profile(criteria)
        lowest = min((o["current_price_per_person"] for o in offers), default=None)
        rows.append({"profile": profile_row, "offer_count": len(offers), "lowest_price": lowest})
    return templates.TemplateResponse(request, "profiles.html", {"rows": rows})


@app.get("/profiles/new")
def new_profile_form(request: Request):
    return templates.TemplateResponse(
        request,
        "profile_form.html",
        {
            "profile": None,
            "countries": COUNTRIES,
            "airports": DEPARTURE_AIRPORTS,
            "board_options": BOARD_OPTIONS,
        },
    )


@app.get("/profiles/{profile_id}/edit")
def edit_profile_form(request: Request, profile_id: int):
    row = db.get_profile(profile_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Nie znaleziono profilu")
    return templates.TemplateResponse(
        request,
        "profile_form.html",
        {
            "profile": row,
            "countries": COUNTRIES,
            "airports": DEPARTURE_AIRPORTS,
            "board_options": BOARD_OPTIONS,
        },
    )


def _parse_optional_int(value: str) -> int | None:
    value = (value or "").strip()
    return int(value) if value else None


def _parse_optional_float(value: str) -> float | None:
    value = (value or "").strip()
    return float(value) if value else None


def _criteria_from_form(
    profile_id: int | None,
    name: str,
    country: str,
    region: str,
    date_from: date,
    date_to: date,
    duration_min: int,
    duration_max: int,
    adults: int,
    children: int,
    board: str,
    max_price_per_person: str,
    min_hotel_rating: str,
    min_stars: str,
    departure_airport: str,
) -> SearchCriteria:
    return SearchCriteria(
        profile_id=profile_id,
        name=name,
        country=country,
        region=region.strip() or None,
        date_from=date_from,
        date_to=date_to,
        duration_min=duration_min,
        duration_max=duration_max,
        adults=adults,
        children=children,
        board=board.strip() or None,
        max_price_per_person=_parse_optional_int(max_price_per_person),
        min_hotel_rating=_parse_optional_float(min_hotel_rating),
        min_stars=_parse_optional_int(min_stars),
        departure_airport=departure_airport.strip() or None,
    )


@app.post("/profiles")
def create_profile(
    name: str = Form(...),
    country: str = Form(...),
    region: str = Form(""),
    date_from: date = Form(...),
    date_to: date = Form(...),
    duration_min: int = Form(6),
    duration_max: int = Form(8),
    adults: int = Form(2),
    children: int = Form(0),
    board: str = Form(""),
    max_price_per_person: str = Form(""),
    min_hotel_rating: str = Form(""),
    min_stars: str = Form(""),
    departure_airport: str = Form(""),
):
    criteria = _criteria_from_form(
        None,
        name,
        country,
        region,
        date_from,
        date_to,
        duration_min,
        duration_max,
        adults,
        children,
        board,
        max_price_per_person,
        min_hotel_rating,
        min_stars,
        departure_airport,
    )
    db.save_profile(criteria)
    return RedirectResponse(url="/", status_code=303)


@app.post("/profiles/{profile_id}")
def update_profile(
    profile_id: int,
    name: str = Form(...),
    country: str = Form(...),
    region: str = Form(""),
    date_from: date = Form(...),
    date_to: date = Form(...),
    duration_min: int = Form(6),
    duration_max: int = Form(8),
    adults: int = Form(2),
    children: int = Form(0),
    board: str = Form(""),
    max_price_per_person: str = Form(""),
    min_hotel_rating: str = Form(""),
    min_stars: str = Form(""),
    departure_airport: str = Form(""),
):
    if db.get_profile(profile_id) is None:
        raise HTTPException(status_code=404, detail="Nie znaleziono profilu")
    criteria = _criteria_from_form(
        profile_id,
        name,
        country,
        region,
        date_from,
        date_to,
        duration_min,
        duration_max,
        adults,
        children,
        board,
        max_price_per_person,
        min_hotel_rating,
        min_stars,
        departure_airport,
    )
    db.save_profile(criteria)
    return RedirectResponse(url="/", status_code=303)


@app.post("/profiles/{profile_id}/delete")
def delete_profile_route(profile_id: int):
    db.delete_profile(profile_id)
    return RedirectResponse(url="/", status_code=303)


@app.post("/profiles/{profile_id}/toggle-active")
def toggle_profile_active(profile_id: int):
    row = db.get_profile(profile_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Nie znaleziono profilu")
    db.set_profile_active(profile_id, not bool(row["active"]))
    return RedirectResponse(url="/", status_code=303)


@app.post("/profiles/{profile_id}/run")
async def run_profile_now(profile_id: int):
    try:
        await scheduler.run_now(profile_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Nie znaleziono profilu")
    return RedirectResponse(url=f"/profiles/{profile_id}/offers", status_code=303)


# --- wyniki / historia cen ---------------------------------------------


@app.get("/profiles/{profile_id}/offers")
def profile_offers(request: Request, profile_id: int):
    row = db.get_profile(profile_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Nie znaleziono profilu")
    criteria = SearchCriteria.from_row(row)
    offers = db.get_offers_for_profile(criteria)

    enriched = []
    for offer in offers:
        history = db.get_price_history(offer["offer_key"])
        trend = None
        if len(history) >= 2:
            prev_price = history[-2][1]
            current_price = offer["current_price_per_person"]
            if current_price < prev_price:
                trend = {"direction": "down", "pct": (prev_price - current_price) / prev_price * 100}
            elif current_price > prev_price:
                trend = {"direction": "up", "pct": (current_price - prev_price) / prev_price * 100}
        enriched.append({"offer": offer, "trend": trend})

    return templates.TemplateResponse(
        request, "offers.html", {"profile": row, "offers": enriched}
    )


@app.get("/offers/{offer_key}/history")
def offer_history(request: Request, offer_key: str):
    history = db.get_price_history(offer_key)
    if not history:
        raise HTTPException(status_code=404, detail="Brak historii dla tej oferty")
    return templates.TemplateResponse(
        request, "price_history.html", {"offer_key": offer_key, "history": history}
    )


# --- okazje / status ---------------------------------------------------


@app.get("/deals")
def deals_page(request: Request):
    deal_rows = db.list_deals()
    return templates.TemplateResponse(
        request, "deals.html", {"deals": deal_rows, "reason_labels": REASON_LABELS}
    )


@app.get("/status")
def status_page(request: Request):
    health = db.get_scraper_health()
    return templates.TemplateResponse(request, "status.html", {"health": health})
