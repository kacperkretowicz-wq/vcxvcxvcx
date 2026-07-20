"""Scraper lastminuter.pl (agregator ofert last minute).

STATUS: SZKIELET NIEZWERYFIKOWANY NA ŻYWEJ STRONIE — patrz uwaga na górze
app/scrapers/wakacje_pl.py (te same ograniczenia i ta sama procedura
dokończenia dotyczą tego pliku; PLAN.md sekcja 7.2).
"""

from urllib.parse import urlencode

from app.models import SearchCriteria
from app.scrapers.base import GenericSelectorCardScraper

# TODO: ZWERYFIKOWAĆ na żywej stronie (PLAN.md sekcja 7.2).
SELECTORS = {
    "card": "div.offer-tile, article.offer-item, li.result-item",
    "hotel_name": ".offer-tile__hotel-name, .hotel-name",
    "stars": ".offer-tile__stars, .stars",
    "rating": ".offer-tile__rating, .rating",
    "board": ".offer-tile__board, .board",
    "region": ".offer-tile__region, .region",
    "date_range": ".offer-tile__dates, .dates",
    "departure_airport": ".offer-tile__airport, .airport",
    "price_per_person": ".offer-tile__price, .price",
    "link": "a.offer-tile__link, a.offer-link",
}


class LastminuterScraper(GenericSelectorCardScraper):
    source_name = "lastminuter"
    base_url = "https://www.lastminuter.pl"
    card_selector = SELECTORS["card"]
    SELECTORS = SELECTORS
    request_delay_s = 7.0

    def build_search_url(self, criteria: SearchCriteria) -> str:
        # TODO: ZWERYFIKOWAĆ prawdziwy format URL/parametrów wyszukiwania.
        params = {
            "kraj": criteria.country,
            "data-od": criteria.date_from.isoformat(),
            "data-do": criteria.date_to.isoformat(),
            "dlugosc-pobytu-od": criteria.duration_min,
            "dlugosc-pobytu-do": criteria.duration_max,
            "dorosli": criteria.adults,
            "dzieci": criteria.children,
        }
        if criteria.region:
            params["region"] = criteria.region
        if criteria.departure_airport:
            params["lotnisko"] = criteria.departure_airport
        return f"{self.base_url}/szukaj?{urlencode(params)}"
