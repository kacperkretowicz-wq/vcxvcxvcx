from datetime import date, datetime, timedelta

import pytest

from app import db, deals
from app.models import Offer, SearchCriteria


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test.db")
    db.init_db(path)
    return path


def make_offer(**overrides) -> Offer:
    payload = dict(
        source="wakacje_pl",
        external_id="abc123",
        hotel_name="Hotel Blue Bay",
        country="Grecja",
        region="Kreta",
        stars=4.0,
        rating=8.6,
        board="AI",
        departure_airport="Warszawa",
        date_start=date(2026, 9, 12),
        date_end=date(2026, 9, 19),
        price_total=8888,
        price_per_person=4444,
        url="https://www.wakacje.pl/oferta/123",
        scraped_at=datetime.now(),
    )
    payload.update(overrides)
    return Offer(**payload)


def make_criteria(**overrides) -> SearchCriteria:
    payload = dict(
        name="Grecja wrzesień",
        country="Grecja",
        date_from=date(2026, 9, 1),
        date_to=date(2026, 9, 30),
        duration_min=6,
        duration_max=8,
        adults=2,
    )
    payload.update(overrides)
    return SearchCriteria(**payload)


def make_profile(db_path, **overrides) -> SearchCriteria:
    criteria = make_criteria(**overrides)
    profile_id = db.save_profile(criteria, db_path)
    return make_criteria(profile_id=profile_id, **overrides)


# --- below_budget ------------------------------------------------------------


def test_below_budget_exact_equal_triggers(db_path):
    profile = make_profile(db_path, max_price_per_person=4444)
    db.upsert_offer(make_offer(price_per_person=4444), db_path)

    found = deals.detect_deals(profile, db_path)
    assert [d.reason for d in found] == ["below_budget"]
    assert "4444 PLN/os" in found[0].detail
    assert "4444 PLN" in found[0].detail  # budżet w treści


def test_below_budget_above_budget_not_triggered(db_path):
    profile = make_profile(db_path, max_price_per_person=4000)
    db.upsert_offer(make_offer(price_per_person=4001), db_path)

    found = deals.detect_deals(profile, db_path)
    assert found == []


def test_no_budget_set_means_no_below_budget_check(db_path):
    profile = make_profile(db_path, max_price_per_person=None)
    db.upsert_offer(make_offer(price_per_person=1), db_path)

    found = deals.detect_deals(profile, db_path)
    assert all(d.reason != "below_budget" for d in found)


# --- price_drop ----------------------------------------------------------


def test_price_drop_exact_threshold_triggers(db_path):
    profile = make_profile(db_path)
    now = datetime.now()
    db.upsert_offer(make_offer(scraped_at=now - timedelta(hours=48), price_per_person=4200), db_path)
    db.upsert_offer(make_offer(scraped_at=now, price_per_person=3780), db_path)  # dokładnie -10%

    found = deals.detect_deals(profile, db_path)
    reasons = {d.reason: d for d in found}
    assert "price_drop" in reasons
    assert reasons["price_drop"].detail == "spadek o 10% (4200 → 3780 PLN/os)"


def test_price_drop_below_threshold_not_triggered(db_path):
    profile = make_profile(db_path)
    now = datetime.now()
    db.upsert_offer(make_offer(scraped_at=now - timedelta(hours=48), price_per_person=4200), db_path)
    db.upsert_offer(make_offer(scraped_at=now, price_per_person=3790), db_path)  # ok. -9.8%

    found = deals.detect_deals(profile, db_path)
    assert all(d.reason != "price_drop" for d in found)


def test_price_drop_reference_outside_72h_window_not_used(db_path):
    profile = make_profile(db_path)
    now = datetime.now()
    db.upsert_offer(make_offer(scraped_at=now - timedelta(hours=100), price_per_person=4200), db_path)
    db.upsert_offer(make_offer(scraped_at=now, price_per_person=3000), db_path)

    found = deals.detect_deals(profile, db_path)
    # jedyny wpis w oknie 72h to bieżący odczyt (3000) - brak prawdziwego punktu
    # odniesienia, więc mimo pozornie dużej różnicy do wpisu sprzed 100h reguła
    # nie powinna się odpalić
    assert all(d.reason != "price_drop" for d in found)


# --- historical_low --------------------------------------------------------


def test_historical_low_requires_at_least_3_entries(db_path):
    profile = make_profile(db_path)
    now = datetime.now()
    db.upsert_offer(make_offer(scraped_at=now - timedelta(hours=24), price_per_person=4500), db_path)
    db.upsert_offer(make_offer(scraped_at=now, price_per_person=4300), db_path)

    found = deals.detect_deals(profile, db_path)
    assert all(d.reason != "historical_low" for d in found)


def test_historical_low_triggers_with_3_entries_at_minimum(db_path):
    profile = make_profile(db_path)
    now = datetime.now()
    db.upsert_offer(make_offer(scraped_at=now - timedelta(hours=48), price_per_person=4500), db_path)
    db.upsert_offer(make_offer(scraped_at=now - timedelta(hours=24), price_per_person=4300), db_path)
    db.upsert_offer(make_offer(scraped_at=now, price_per_person=4300), db_path)

    found = deals.detect_deals(profile, db_path)
    reasons = {d.reason: d for d in found}
    assert "historical_low" in reasons
    assert reasons["historical_low"].detail == "historyczne minimum: 4300 PLN/os"


# --- deduplikacja ------------------------------------------------------------


def test_detect_deals_does_not_duplicate_on_repeated_run(db_path):
    profile = make_profile(db_path, max_price_per_person=5000)
    db.upsert_offer(make_offer(price_per_person=4444), db_path)

    first_run = deals.detect_deals(profile, db_path)
    assert len(first_run) == 1

    second_run = deals.detect_deals(profile, db_path)
    assert second_run == []
    assert len(db.list_deals(db_path=db_path)) == 1


# --- renotyfikacja przy dalszym spadku ceny ---------------------------------


def test_renotify_after_further_5pct_drop(db_path):
    profile = make_profile(db_path, max_price_per_person=5000)
    db.upsert_offer(make_offer(scraped_at=datetime.now(), price_per_person=4800), db_path)

    first_run = deals.detect_deals(profile, db_path)
    assert len(first_run) == 1
    detected_at = first_run[0].detected_at

    unnotified = db.get_unnotified_deals(db_path)
    assert len(unnotified) == 1
    db.mark_deal_notified(unnotified[0]["id"], db_path)
    assert db.get_unnotified_deals(db_path) == []

    # kolejny odczyt, wyraźnie później niż detekcja pierwszej okazji: 4800 -> 4500 (-6.25%)
    db.upsert_offer(
        make_offer(scraped_at=detected_at + timedelta(hours=1), price_per_person=4500), db_path
    )

    second_run = deals.detect_deals(profile, db_path)
    assert second_run == []  # to nie jest nowa okazja - insert_deal ją zignorował

    unnotified_again = db.get_unnotified_deals(db_path)
    assert len(unnotified_again) == 1
    assert "4500" in unnotified_again[0]["detail"]


def test_no_renotify_below_5pct_drop(db_path):
    profile = make_profile(db_path, max_price_per_person=5000)
    db.upsert_offer(make_offer(scraped_at=datetime.now(), price_per_person=4800), db_path)

    first_run = deals.detect_deals(profile, db_path)
    detected_at = first_run[0].detected_at

    db.mark_deal_notified(db.get_unnotified_deals(db_path)[0]["id"], db_path)
    assert db.get_unnotified_deals(db_path) == []

    # spadek tylko o ok. 2% - poniżej progu renotyfikacji (5%)
    db.upsert_offer(
        make_offer(scraped_at=detected_at + timedelta(hours=1), price_per_person=4700), db_path
    )

    second_run = deals.detect_deals(profile, db_path)
    assert second_run == []
    assert db.get_unnotified_deals(db_path) == []
