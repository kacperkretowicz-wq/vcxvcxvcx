"""Scraper wakacje.pl — agregator ofert większości polskich touroperatorów.

STATUS: SZKIELET NIEZWERYFIKOWANY NA ŻYWEJ STRONIE.

Ten moduł powstał w środowisku bez dostępu do ogólnego internetu (polityka
sieciowa środowiska blokowała ruch poza pypi/npm/github/anthropic.com),
więc nie dało się przejść procedury z PLAN.md sekcja 7.2 (podgląd karty
Network w DevTools na żywej stronie wakacje.pl). Cała logika parsowania
tekstu (ceny, daty, gwiazdki, ocena, normalizacja wyżywienia) jest w pełni
zaimplementowana i przetestowana (zob. tests/test_scrapers.py), ale
SELECTORS i SEARCH_URL_TEMPLATE poniżej są PRZYBLIŻENIEM i wymagają
weryfikacji/poprawek na żywej stronie, zanim scraper zacznie zwracać
prawdziwe wyniki. Snapshot użyty w testach
(snapshots/wakacje_pl/sample_search.html) jest SYNTETYCZNY — napisany
ręcznie tak, by pasował do SELECTORS poniżej, a NIE jest prawdziwym
zrzutem strony.

Aby dokończyć ten scraper:
1. Otwórz https://www.wakacje.pl w przeglądarce z DevTools (karta Network).
2. Wykonaj wyszukiwanie (kraj, daty, osoby, wyżywienie) i zaobserwuj URL
   wyników — zaktualizuj `build_search_url` (parametry query mogą się
   nazywać inaczej niż tu założono).
3. Sprawdź, czy istnieje żądanie XHR/Fetch zwracające JSON z ofertami —
   jeśli tak, to zdecydowanie łatwiejsza i stabilniejsza ścieżka niż
   parsowanie HTML; przepisz `search()`, żeby wołać ten endpoint przez
   httpx zamiast Playwright.
4. Jeśli trzeba zostać przy HTML: w DevTools zbadaj prawdziwe klasy CSS
   kart ofert i zaktualizuj słownik SELECTORS poniżej (jedno miejsce).
5. Zapisz realny zrzut HTML/JSON do snapshots/wakacje_pl/ i zaktualizuj
   test w tests/test_scrapers.py, żeby operował na nim zamiast (albo obok)
   syntetycznego przykładu.
"""

import argparse
import asyncio
import logging
from datetime import datetime
from urllib.parse import urlencode

from bs4 import BeautifulSoup

from app.models import Offer, SearchCriteria
from app.scrapers.base import (
    HtmlCardScraper,
    extract_float,
    normalize_board,
    parse_date_range,
    parse_price_pln,
)

logger = logging.getLogger(__name__)

# TODO: ZWERYFIKOWAĆ na żywej stronie (PLAN.md sekcja 7.2). Każdy selektor to
# lista alternatyw (przecinek = CSS "or") — parser bierze pierwsze trafienie.
SELECTORS = {
    "card": "div.offer-tile, article.offer, li.search-result",
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


class WakacjePlScraper(HtmlCardScraper):
    source_name = "wakacje_pl"
    base_url = "https://www.wakacje.pl"
    card_selector = SELECTORS["card"]
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

    def parse_card(self, card_html: str, criteria: SearchCriteria) -> Offer | None:
        soup = BeautifulSoup(card_html, "html.parser")

        hotel_el = soup.select_one(SELECTORS["hotel_name"])
        price_el = soup.select_one(SELECTORS["price_per_person"])
        dates_el = soup.select_one(SELECTORS["date_range"])
        link_el = soup.select_one(SELECTORS["link"])

        if not (hotel_el and price_el and dates_el and link_el):
            return None

        hotel_name = hotel_el.get_text(strip=True)
        try:
            price_per_person = parse_price_pln(price_el.get_text(strip=True))
            date_start, date_end = parse_date_range(dates_el.get_text(strip=True))
        except ValueError:
            logger.warning(
                "wakacje_pl: nie udało się sparsować ceny/dat oferty %r", hotel_name
            )
            return None

        stars_el = soup.select_one(SELECTORS["stars"])
        rating_el = soup.select_one(SELECTORS["rating"])
        board_el = soup.select_one(SELECTORS["board"])
        region_el = soup.select_one(SELECTORS["region"])
        airport_el = soup.select_one(SELECTORS["departure_airport"])

        url = link_el.get("href", "") or ""
        if url.startswith("/"):
            url = self.base_url + url

        board_raw = board_el.get_text(strip=True) if board_el else None
        airport = airport_el.get_text(strip=True) if airport_el else criteria.departure_airport

        party_size = max(criteria.adults + criteria.children, 1)
        price_total = price_per_person * party_size

        external_id = self.make_external_id(
            hotel_name,
            date_start.isoformat(),
            date_end.isoformat(),
            board_raw or "",
            airport or "",
        )

        return Offer(
            source=self.source_name,
            external_id=external_id,
            hotel_name=hotel_name,
            country=criteria.country,
            region=region_el.get_text(strip=True) if region_el else criteria.region,
            stars=extract_float(stars_el.get_text(strip=True)) if stars_el else None,
            rating=extract_float(rating_el.get_text(strip=True)) if rating_el else None,
            board=normalize_board(board_raw),
            departure_airport=airport,
            date_start=date_start,
            date_end=date_end,
            price_total=price_total,
            price_per_person=price_per_person,
            url=url,
            scraped_at=datetime.now(),
        )


async def _run_cli(criteria: SearchCriteria) -> None:
    scraper = WakacjePlScraper()
    try:
        offers = await scraper.search(criteria)
    except Exception as exc:
        print(f"BŁĄD: {exc}")
        return

    if not offers:
        print("Brak ofert (0 wyników — patrz ostrzeżenia w logu).")
        return

    for offer in offers:
        print(
            f"{offer.hotel_name} | {offer.stars}* | {offer.board} | "
            f"{offer.date_start} - {offer.date_end} | {offer.price_per_person} PLN/os | {offer.url}"
        )


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Ręczny test scrapera wakacje.pl")
    parser.add_argument("--country", required=True)
    parser.add_argument("--date-from", required=True)
    parser.add_argument("--date-to", required=True)
    parser.add_argument("--adults", type=int, default=2)
    parser.add_argument("--children", type=int, default=0)
    parser.add_argument("--board", default=None)
    args = parser.parse_args()

    criteria = SearchCriteria(
        name="cli",
        country=args.country,
        date_from=args.date_from,
        date_to=args.date_to,
        adults=args.adults,
        children=args.children,
        board=args.board,
    )
    asyncio.run(_run_cli(criteria))


if __name__ == "__main__":
    main()
