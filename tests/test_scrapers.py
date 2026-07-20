from datetime import date
from pathlib import Path

import pytest

from app.models import SearchCriteria
from app.scrapers.base import (
    extract_float,
    normalize_board,
    parse_date_range,
    parse_price_pln,
)
from app.scrapers.wakacje_pl import WakacjePlScraper

SNAPSHOT_DIR = Path(__file__).parent.parent / "snapshots"


def make_criteria(**overrides) -> SearchCriteria:
    payload = dict(
        name="Grecja wrzesień",
        country="Grecja",
        date_from=date(2026, 9, 1),
        date_to=date(2026, 9, 30),
        adults=2,
        children=0,
    )
    payload.update(overrides)
    return SearchCriteria(**payload)


# --- normalize_board -------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("All Inclusive", "AI"),
        ("all incl.", "AI"),
        ("2 posiłki", "HB"),
        ("Half Board", "HB"),
        ("HB", "HB"),
        ("Śniadania", "BB"),
        ("Bed & Breakfast", "BB"),
        ("BB", "BB"),
        ("Bez wyżywienia", "SC"),
        ("Self catering", "SC"),
        ("Tylko nocleg", "OB"),
        ("Overnight", "OB"),
    ],
)
def test_normalize_board(raw, expected):
    assert normalize_board(raw) == expected


def test_normalize_board_unknown_returns_none():
    assert normalize_board("coś dziwnego") is None


def test_normalize_board_empty_returns_none():
    assert normalize_board(None) is None
    assert normalize_board("") is None


# --- parse_price_pln ---------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("3 444 zł", 3444),
        ("3444 PLN", 3444),
        ("3 444,00 zł", 3444),
        ("4 980 zł/os.", 4980),
        ("1234", 1234),
    ],
)
def test_parse_price_pln(text, expected):
    assert parse_price_pln(text) == expected


def test_parse_price_pln_no_digits_raises():
    with pytest.raises(ValueError):
        parse_price_pln("brak ceny")


# --- parse_date_range --------------------------------------------------------


def test_parse_date_range_with_both_years():
    start, end = parse_date_range("12.09.2026 - 19.09.2026")
    assert start == date(2026, 9, 12)
    assert end == date(2026, 9, 19)


def test_parse_date_range_without_start_year():
    start, end = parse_date_range("12.09 - 19.09.2026")
    assert start == date(2026, 9, 12)
    assert end == date(2026, 9, 19)


def test_parse_date_range_en_dash():
    start, end = parse_date_range("12.09.2026 – 19.09.2026")
    assert start == date(2026, 9, 12)
    assert end == date(2026, 9, 19)


def test_parse_date_range_invalid_raises():
    with pytest.raises(ValueError):
        parse_date_range("brak dat")


# --- extract_float -------------------------------------------------------


def test_extract_float_comma_decimal():
    assert extract_float("8,6/10") == 8.6


def test_extract_float_stars():
    assert extract_float("4*") == 4.0


def test_extract_float_none_when_empty():
    assert extract_float(None) is None
    assert extract_float("") is None


# --- wakacje_pl parser na syntetycznym snapshocie ---------------------------


def test_wakacje_pl_parse_html_snapshot():
    html = (SNAPSHOT_DIR / "wakacje_pl" / "sample_search.html").read_text(encoding="utf-8")
    scraper = WakacjePlScraper()
    offers = scraper.parse_html(html, make_criteria())

    # trzecia karta w snapshocie celowo nie ma ceny - parser ma ją pominąć,
    # a nie wywalić się wyjątkiem
    assert len(offers) == 2

    first = offers[0]
    assert first.source == "wakacje_pl"
    assert first.hotel_name == "Hotel Blue Bay"
    assert first.country == "Grecja"
    assert first.region == "Kreta"
    assert first.stars == 4.0
    assert first.rating == 8.6
    assert first.board == "AI"
    assert first.departure_airport == "Warszawa"
    assert first.date_start == date(2026, 9, 12)
    assert first.date_end == date(2026, 9, 19)
    assert first.price_per_person == 3444
    assert first.price_total == 3444 * 2
    assert first.url == "https://www.wakacje.pl/oferta/hotel-blue-bay-12345"

    second = offers[1]
    assert second.hotel_name == "Hotel Sunny Hill"
    assert second.url == "https://www.wakacje.pl/oferta/hotel-sunny-hill-67890"


def test_wakacje_pl_build_search_url_contains_criteria():
    scraper = WakacjePlScraper()
    url = scraper.build_search_url(make_criteria(region="Kreta", departure_airport="Warszawa"))
    assert "kraj=Grecja" in url
    assert "region=Kreta" in url
    assert "2026-09-01" in url
    assert "2026-09-30" in url
