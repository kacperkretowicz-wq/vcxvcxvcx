from datetime import date, datetime, timedelta

import pytest

from app import db
from app.models import Deal, Offer, SearchCriteria


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
        scraped_at=datetime(2026, 7, 20, 8, 0, 0),
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


def test_upsert_offer_new(db_path):
    offer = make_offer()
    is_new = db.upsert_offer(offer, db_path)
    assert is_new is True

    rows = db.get_offers_for_profile(make_criteria(), db_path)
    assert len(rows) == 1
    assert rows[0]["current_price_per_person"] == 4444
    assert rows[0]["lowest_price_per_person"] == 4444

    history = db.get_price_history(offer.offer_key, db_path)
    assert len(history) == 1
    assert history[0][1] == 4444


def test_upsert_offer_price_drop_updates_lowest(db_path):
    offer1 = make_offer(scraped_at=datetime(2026, 7, 20, 8, 0, 0), price_per_person=4444)
    offer2 = make_offer(scraped_at=datetime(2026, 7, 21, 8, 0, 0), price_per_person=3800)

    assert db.upsert_offer(offer1, db_path) is True
    assert db.upsert_offer(offer2, db_path) is False

    rows = db.get_offers_for_profile(make_criteria(), db_path)
    assert rows[0]["current_price_per_person"] == 3800
    assert rows[0]["lowest_price_per_person"] == 3800

    history = db.get_price_history(offer1.offer_key, db_path)
    assert [p for _, p in history] == [4444, 3800]


def test_upsert_offer_price_rise_keeps_lowest(db_path):
    offer1 = make_offer(scraped_at=datetime(2026, 7, 20, 8, 0, 0), price_per_person=3800)
    offer2 = make_offer(scraped_at=datetime(2026, 7, 21, 8, 0, 0), price_per_person=4200)

    db.upsert_offer(offer1, db_path)
    db.upsert_offer(offer2, db_path)

    rows = db.get_offers_for_profile(make_criteria(), db_path)
    assert rows[0]["current_price_per_person"] == 4200
    assert rows[0]["lowest_price_per_person"] == 3800


def test_upsert_offer_same_price_within_gap_skips_history(db_path):
    offer1 = make_offer(scraped_at=datetime(2026, 7, 20, 8, 0, 0), price_per_person=4444)
    offer2 = make_offer(scraped_at=datetime(2026, 7, 20, 14, 0, 0), price_per_person=4444)

    db.upsert_offer(offer1, db_path)
    db.upsert_offer(offer2, db_path)

    history = db.get_price_history(offer1.offer_key, db_path)
    assert len(history) == 1


def test_upsert_offer_same_price_after_gap_records_history(db_path):
    offer1 = make_offer(scraped_at=datetime(2026, 7, 20, 8, 0, 0), price_per_person=4444)
    offer2 = make_offer(scraped_at=datetime(2026, 7, 21, 8, 1, 0), price_per_person=4444)

    db.upsert_offer(offer1, db_path)
    db.upsert_offer(offer2, db_path)

    history = db.get_price_history(offer1.offer_key, db_path)
    assert len(history) == 2


def test_get_offers_for_profile_filters(db_path):
    matching = make_offer(external_id="match", date_start=date(2026, 9, 12), date_end=date(2026, 9, 19))
    wrong_country = make_offer(external_id="wc", country="Turcja")
    wrong_dates = make_offer(external_id="wd", date_start=date(2026, 10, 5), date_end=date(2026, 10, 12))
    wrong_duration = make_offer(external_id="wdur", date_start=date(2026, 9, 12), date_end=date(2026, 9, 14))
    wrong_board = make_offer(external_id="wb", board="BB")

    for offer in [matching, wrong_country, wrong_dates, wrong_duration, wrong_board]:
        db.upsert_offer(offer, db_path)

    rows = db.get_offers_for_profile(make_criteria(board="AI"), db_path)
    assert [row["external_id"] for row in rows] == ["match"]


def test_get_offers_for_profile_min_stars_excludes_unknown(db_path):
    known = make_offer(external_id="known", stars=4.5)
    unknown = make_offer(external_id="unknown", stars=None)
    db.upsert_offer(known, db_path)
    db.upsert_offer(unknown, db_path)

    rows = db.get_offers_for_profile(make_criteria(min_stars=4), db_path)
    assert [row["external_id"] for row in rows] == ["known"]


def test_save_and_list_profiles(db_path):
    profile_id = db.save_profile(make_criteria(), db_path)
    assert isinstance(profile_id, int)

    profiles = db.list_profiles(db_path=db_path)
    assert len(profiles) == 1
    assert profiles[0]["id"] == profile_id
    assert profiles[0]["active"] == 1

    db.set_profile_active(profile_id, False, db_path)
    active_profiles = db.list_profiles(active_only=True, db_path=db_path)
    assert active_profiles == []

    db.delete_profile(profile_id, db_path)
    assert db.list_profiles(db_path=db_path) == []


def test_save_profile_update(db_path):
    profile_id = db.save_profile(make_criteria(), db_path)
    db.save_profile(make_criteria(profile_id=profile_id, name="Zmieniona nazwa"), db_path)

    profile = db.get_profile(profile_id, db_path)
    assert profile["name"] == "Zmieniona nazwa"
    assert len(db.list_profiles(db_path=db_path)) == 1


def test_insert_deal_deduplication(db_path):
    offer = make_offer()
    db.upsert_offer(offer, db_path)
    profile_id = db.save_profile(make_criteria(), db_path)

    deal = Deal(
        offer_key=offer.offer_key,
        profile_id=profile_id,
        reason="below_budget",
        detail="test",
        detected_at=datetime(2026, 7, 20, 9, 0, 0),
    )
    assert db.insert_deal(deal, db_path) is True
    assert db.insert_deal(deal, db_path) is False

    deals = db.list_deals(db_path=db_path)
    assert len(deals) == 1


def test_deal_notification_flow(db_path):
    offer = make_offer()
    db.upsert_offer(offer, db_path)
    profile_id = db.save_profile(make_criteria(), db_path)

    deal = Deal(
        offer_key=offer.offer_key,
        profile_id=profile_id,
        reason="price_drop",
        detail="spadek o 18%",
        detected_at=datetime(2026, 7, 20, 9, 0, 0),
    )
    db.insert_deal(deal, db_path)

    unnotified = db.get_unnotified_deals(db_path)
    assert len(unnotified) == 1
    deal_id = unnotified[0]["id"]

    db.mark_deal_notified(deal_id, db_path)
    assert db.get_unnotified_deals(db_path) == []


def test_update_deal_for_renotify(db_path):
    offer = make_offer()
    db.upsert_offer(offer, db_path)
    profile_id = db.save_profile(make_criteria(), db_path)

    deal = Deal(
        offer_key=offer.offer_key,
        profile_id=profile_id,
        reason="price_drop",
        detail="spadek o 12%",
        detected_at=datetime(2026, 7, 20, 9, 0, 0),
    )
    db.insert_deal(deal, db_path)
    db.mark_deal_notified(db.get_unnotified_deals(db_path)[0]["id"], db_path)
    assert db.get_unnotified_deals(db_path) == []

    db.update_deal_for_renotify(
        offer.offer_key, profile_id, "price_drop", "spadek o 20%", db_path
    )
    unnotified = db.get_unnotified_deals(db_path)
    assert len(unnotified) == 1
    assert unnotified[0]["detail"] == "spadek o 20%"


def test_scraper_health(db_path):
    db.record_scraper_failure("wakacje_pl", "timeout", db_path)
    db.record_scraper_failure("wakacje_pl", "timeout", db_path)
    health = db.get_scraper_health(db_path)
    assert health[0]["source"] == "wakacje_pl"
    assert health[0]["consecutive_failures"] == 2

    db.record_scraper_success("wakacje_pl", db_path)
    health = db.get_scraper_health(db_path)
    assert health[0]["consecutive_failures"] == 0
    assert health[0]["last_success"] is not None


def test_delete_stale_offers(db_path):
    fresh = make_offer(external_id="fresh", scraped_at=datetime.now())
    stale = make_offer(external_id="stale", scraped_at=datetime.now() - timedelta(days=20))
    db.upsert_offer(fresh, db_path)
    db.upsert_offer(stale, db_path)

    deleted = db.delete_stale_offers(14, db_path)
    assert deleted == 1

    rows = db.get_offers_for_profile(make_criteria(), db_path)
    assert [row["external_id"] for row in rows] == ["fresh"]
