"""Wspólna infrastruktura dla wszystkich scraperów (sekcja 7 planu)."""

import asyncio
import glob
import hashlib
import logging
import os
import re
from abc import ABC, abstractmethod
from datetime import date, datetime

from bs4 import BeautifulSoup
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

from app.models import Offer, SearchCriteria

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
REQUEST_TIMEOUT_S = 30.0
MAX_RESULT_PAGES = 3
RETRY_DELAYS_S = [2, 4, 8]


class ScraperError(Exception):
    """Błąd scrapera — awaria pobierania lub parsowania strony."""


class BaseScraper(ABC):
    source_name: str
    request_delay_s: float = 7.0

    @abstractmethod
    async def search(self, criteria: SearchCriteria) -> list[Offer]:
        """Zwraca listę ofert dla podanych kryteriów. Rzuca ScraperError przy awarii."""

    def make_external_id(self, *parts: str) -> str:
        raw = "|".join(str(p) for p in parts)
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def resolve_chromium_executable() -> str | None:
    """Znajduje wstępnie zainstalowaną przeglądarkę Chromium (jeśli jest), inaczej
    zwraca None i Playwright użyje domyślnej ścieżki (wymaga `playwright install chromium`)."""
    override = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE")
    if override:
        return override
    browsers_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if browsers_path:
        matches = sorted(glob.glob(os.path.join(browsers_path, "chromium-*", "chrome-linux", "chrome")))
        if matches:
            return matches[-1]
    return None


class HtmlCardScraper(BaseScraper):
    """Bazowa implementacja dla scraperów typu "wejdź na stronę wyników, poczekaj na
    karty ofert, sparsuj DOM" (ścieżka B z procedury 7.2). Podklasa dostarcza
    `build_search_url`, `card_selector`/`SELECTORS` i `parse_card`."""

    base_url: str
    card_selector: str
    wait_selector: str | None = None
    page_load_timeout_ms: int = 20000

    def build_search_url(self, criteria: SearchCriteria) -> str:
        raise NotImplementedError

    def parse_card(self, card_html: str, criteria: SearchCriteria) -> Offer | None:
        raise NotImplementedError

    async def fetch_html(self, url: str) -> str:
        executable = resolve_chromium_executable()
        async with async_playwright() as p:
            launch_kwargs: dict = {"headless": True}
            if executable:
                launch_kwargs["executable_path"] = executable
            browser = await p.chromium.launch(**launch_kwargs)
            try:
                context = await browser.new_context(user_agent=DEFAULT_USER_AGENT, locale="pl-PL")
                page = await context.new_page()
                page.set_default_timeout(self.page_load_timeout_ms)
                await page.goto(url, wait_until="domcontentloaded", timeout=self.page_load_timeout_ms)
                wait_for = self.wait_selector or self.card_selector
                try:
                    await page.wait_for_selector(wait_for, timeout=self.page_load_timeout_ms)
                except PlaywrightTimeoutError as exc:
                    raise ScraperError(
                        f"{self.source_name}: selektor '{wait_for}' nie pojawił się na stronie "
                        f"{url}. Strona mogła zmienić strukturę albo zablokować dostęp — "
                        "zweryfikuj SELECTORS wg procedury z PLAN.md sekcja 7.2."
                    ) from exc
                return await page.content()
            finally:
                await browser.close()

    def parse_html(self, html: str, criteria: SearchCriteria) -> list[Offer]:
        soup = BeautifulSoup(html, "html.parser")
        cards = soup.select(self.card_selector)
        offers: list[Offer] = []
        for card in cards:
            try:
                offer = self.parse_card(str(card), criteria)
            except Exception:
                logger.exception(
                    "%s: błąd parsowania pojedynczej karty oferty — pomijam", self.source_name
                )
                continue
            if offer is not None:
                offers.append(offer)
        return offers

    async def search(self, criteria: SearchCriteria) -> list[Offer]:
        url = self.build_search_url(criteria)
        html = await self._fetch_html_with_retry(url)

        offers = self.parse_html(html, criteria)
        if not offers:
            logger.warning(
                "%s: strona się załadowała, ale nie sparsowano żadnej oferty — "
                "prawdopodobnie SELECTORS wymaga aktualizacji (PLAN.md sekcja 7.2)",
                self.source_name,
            )
        return offers

    async def _fetch_html_with_retry(self, url: str) -> str:
        """Ponawia pobranie strony przy błędach (sieciowych lub timeout na
        selektorze) z rosnącym opóźnieniem: 2s, 4s, 8s (sekcja 8 planu)."""
        last_error: ScraperError | None = None
        total_attempts = len(RETRY_DELAYS_S) + 1

        for attempt in range(1, total_attempts + 1):
            try:
                return await self.fetch_html(url)
            except ScraperError as exc:
                last_error = exc
            except Exception as exc:
                last_error = ScraperError(f"{self.source_name}: błąd pobierania strony {url}: {exc}")

            if attempt <= len(RETRY_DELAYS_S):
                delay = RETRY_DELAYS_S[attempt - 1]
                logger.warning(
                    "%s: próba %d/%d nieudana (%s) — ponawiam za %ds",
                    self.source_name,
                    attempt,
                    total_attempts,
                    last_error,
                    delay,
                )
                await asyncio.sleep(delay)

        assert last_error is not None
        raise last_error


def _select_optional(soup: BeautifulSoup, selector: str | None):
    if not selector:
        return None
    return soup.select_one(selector)


class GenericSelectorCardScraper(HtmlCardScraper):
    """HtmlCardScraper z gotową implementacją parse_card sterowaną słownikiem
    SELECTORS (wymagane klucze: hotel_name, price_per_person, date_range, link;
    opcjonalne: stars, rating, board, region, departure_airport). Podklasa
    dostarcza tylko SELECTORS, base_url, card_selector i build_search_url —
    patrz wakacje_pl.py dla przykładu."""

    SELECTORS: dict[str, str] = {}

    def parse_card(self, card_html: str, criteria: SearchCriteria) -> Offer | None:
        soup = BeautifulSoup(card_html, "html.parser")
        sel = self.SELECTORS

        hotel_el = soup.select_one(sel["hotel_name"])
        price_el = soup.select_one(sel["price_per_person"])
        dates_el = soup.select_one(sel["date_range"])
        link_el = soup.select_one(sel["link"])

        if not (hotel_el and price_el and dates_el and link_el):
            return None

        hotel_name = hotel_el.get_text(strip=True)
        try:
            price_per_person = parse_price_pln(price_el.get_text(strip=True))
            date_start, date_end = parse_date_range(dates_el.get_text(strip=True))
        except ValueError:
            logger.warning(
                "%s: nie udało się sparsować ceny/dat oferty %r", self.source_name, hotel_name
            )
            return None

        stars_el = _select_optional(soup, sel.get("stars"))
        rating_el = _select_optional(soup, sel.get("rating"))
        board_el = _select_optional(soup, sel.get("board"))
        region_el = _select_optional(soup, sel.get("region"))
        airport_el = _select_optional(soup, sel.get("departure_airport"))

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


# ---------------------------------------------------------------------------
# Parsowanie pól tekstowych — wspólne dla wszystkich scraperów HTML.
# ---------------------------------------------------------------------------

_FLOAT_RE = re.compile(r"(\d+(?:[.,]\d+)?)")


def extract_float(text: str | None) -> float | None:
    if not text:
        return None
    match = _FLOAT_RE.search(text)
    if not match:
        return None
    return float(match.group(1).replace(",", "."))


def parse_price_pln(text: str) -> int:
    """Wyciąga liczbę całkowitą PLN z tekstu typu '3 444 zł' / '3444 PLN' / '3 444,00 zł'."""
    if not text:
        raise ValueError("pusty tekst ceny")
    cleaned = text.replace(" ", " ")
    cleaned = re.sub(r"[.,]\d{2}(?!\d)", "", cleaned)  # usuń grosze, np. ",00"
    digits = re.sub(r"[^\d]", "", cleaned)
    if not digits:
        raise ValueError(f"nie znaleziono cyfr w tekście ceny: {text!r}")
    return int(digits)


_DATE_RANGE_RE = re.compile(
    r"(?P<d1>\d{1,2})\.(?P<m1>\d{1,2})(?:\.(?P<y1>\d{4}))?\s*[-–—]\s*"
    r"(?P<d2>\d{1,2})\.(?P<m2>\d{1,2})\.(?P<y2>\d{4})"
)


def parse_date_range(text: str) -> tuple[date, date]:
    """Parsuje zakres dat typu '12.09.2026 - 19.09.2026' lub '12.09 - 19.09.2026'
    (rok wylotu domyślnie taki sam jak rok powrotu, jeśli nie podany)."""
    if not text:
        raise ValueError("pusty tekst zakresu dat")
    match = _DATE_RANGE_RE.search(text)
    if not match:
        raise ValueError(f"nie rozpoznano zakresu dat: {text!r}")
    year2 = int(match.group("y2"))
    year1 = int(match.group("y1")) if match.group("y1") else year2
    date_start = date(year1, int(match.group("m1")), int(match.group("d1")))
    date_end = date(year2, int(match.group("m2")), int(match.group("d2")))
    return date_start, date_end


_BOARD_AI = ("all inclusive", "all incl")
_BOARD_HB = ("2 posiłki", "śniadania i obiadokolacje", "half board", "hb")
_BOARD_BB = ("śniadani", "bed & breakfast", "bb")
_BOARD_SC = ("bez wyżywienia", "self", "sc")
_BOARD_OB = ("tylko nocleg", "overnight", "ob")


def normalize_board(raw: str | None) -> str | None:
    """Normalizuje surowy opis wyżywienia do jednej z: AI, HB, BB, SC, OB (sekcja 4.1)."""
    if not raw:
        return None
    text = raw.strip().lower()
    if any(p in text for p in _BOARD_AI):
        return "AI"
    if any(p in text for p in _BOARD_HB):
        return "HB"
    if any(p in text for p in _BOARD_BB):
        return "BB"
    if any(p in text for p in _BOARD_SC):
        return "SC"
    if any(p in text for p in _BOARD_OB):
        return "OB"
    logger.warning("normalize_board: nierozpoznany typ wyżywienia: %r", raw)
    return None
