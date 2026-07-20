from datetime import date, datetime

from pydantic import BaseModel


class SearchCriteria(BaseModel):
    """Kryteria jednego profilu wyszukiwania — to wypełnia użytkownik w UI."""

    profile_id: int | None = None
    name: str
    country: str
    region: str | None = None
    date_from: date
    date_to: date
    duration_min: int = 6
    duration_max: int = 8
    adults: int = 2
    children: int = 0
    board: str | None = None
    max_price_per_person: int | None = None
    min_hotel_rating: float | None = None
    min_stars: int | None = None
    departure_airport: str | None = None


class Offer(BaseModel):
    """Jedna oferta zwrócona przez scraper. Wszystkie scrapery zwracają TEN format."""

    source: str
    external_id: str
    hotel_name: str
    country: str
    region: str | None = None
    stars: float | None = None
    rating: float | None = None
    board: str | None = None
    departure_airport: str | None = None
    date_start: date
    date_end: date
    price_total: int
    price_per_person: int
    url: str
    scraped_at: datetime

    @property
    def offer_key(self) -> str:
        return f"{self.source}:{self.external_id}"


class Deal(BaseModel):
    """Wykryta okazja powiązana z ofertą i profilem."""

    offer_key: str
    profile_id: int
    reason: str
    detail: str
    detected_at: datetime
