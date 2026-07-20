from datetime import date, datetime

import pytest

from app import db, scheduler
from app.models import Offer, SearchCriteria
from app.scrapers.base import BaseScraper, ScraperError


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test.db")
    db.init_db(path)
    return path


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


def make_offer(**overrides) -> Offer:
    payload = dict(
        source="stub_source",
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
        url="https://example.test/oferta/123",
        scraped_at=datetime.now(),
    )
    payload.update(overrides)
    return Offer(**payload)


class StubScraper(BaseScraper):
    source_name = "stub_source"
    request_delay_s = 0.0

    def __init__(self, offers=None, error: Exception | None = None):
        self._offers = offers or []
        self._error = error
        self.call_count = 0

    async def search(self, criteria: SearchCriteria) -> list[Offer]:
        self.call_count += 1
        if self._error is not None:
            raise self._error
        return self._offers


# --- create_scheduler --------------------------------------------------------


@pytest.mark.asyncio
async def test_create_scheduler_registers_jobs():
    sched = scheduler.create_scheduler()
    job_ids = {job.id for job in sched.get_jobs()}

    for time_str in ["07:30", "13:30", "20:30"]:
        assert f"run_all_searches_{time_str}" in job_ids
    assert "cleanup_stale_offers" in job_ids


# --- run_profile ------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_profile_saves_offers_and_detects_deals(db_path, monkeypatch):
    stub = StubScraper(offers=[make_offer()])
    monkeypatch.setattr(scheduler, "SCRAPERS", {"stub_source": stub})

    profile = make_profile(db_path, max_price_per_person=5000)
    await scheduler.run_profile(profile, db_path)

    assert stub.call_count == 1
    offers = db.get_offers_for_profile(profile, db_path)
    assert len(offers) == 1
    assert offers[0]["hotel_name"] == "Hotel Blue Bay"

    saved_deals = db.list_deals(db_path=db_path)
    assert len(saved_deals) == 1
    assert saved_deals[0]["reason"] == "below_budget"

    health = {row["source"]: row for row in db.get_scraper_health(db_path)}
    assert health["stub_source"]["consecutive_failures"] == 0
    assert health["stub_source"]["last_success"] is not None


@pytest.mark.asyncio
async def test_run_profile_records_failure_without_crashing(db_path, monkeypatch):
    stub = StubScraper(error=ScraperError("strona zmieniła strukturę"))
    monkeypatch.setattr(scheduler, "SCRAPERS", {"stub_source": stub})

    profile = make_profile(db_path)
    await scheduler.run_profile(profile, db_path)  # nie powinno rzucić wyjątku

    assert db.get_offers_for_profile(profile, db_path) == []
    health = {row["source"]: row for row in db.get_scraper_health(db_path)}
    assert health["stub_source"]["consecutive_failures"] == 1
    assert "strona zmieniła strukturę" in health["stub_source"]["last_error_message"]


@pytest.mark.asyncio
async def test_run_profile_skips_unhealthy_scraper(db_path, monkeypatch):
    for _ in range(5):
        db.record_scraper_failure("stub_source", "timeout", db_path)

    stub = StubScraper(offers=[make_offer()])
    monkeypatch.setattr(scheduler, "SCRAPERS", {"stub_source": stub})

    profile = make_profile(db_path)
    await scheduler.run_profile(profile, db_path)

    assert stub.call_count == 0  # pominięty - >=5 awarii z rzędu
    assert db.get_offers_for_profile(profile, db_path) == []


# --- run_all_searches / run_now ----------------------------------------------


@pytest.mark.asyncio
async def test_run_all_searches_with_no_active_profiles(db_path):
    await scheduler.run_all_searches(db_path)  # nie powinno rzucić wyjątku


@pytest.mark.asyncio
async def test_run_all_searches_skips_inactive_profiles(db_path, monkeypatch):
    stub = StubScraper(offers=[make_offer()])
    monkeypatch.setattr(scheduler, "SCRAPERS", {"stub_source": stub})

    profile = make_profile(db_path)
    db.set_profile_active(profile.profile_id, False, db_path)

    await scheduler.run_all_searches(db_path)

    assert stub.call_count == 0
    assert db.get_offers_for_profile(profile, db_path) == []


@pytest.mark.asyncio
async def test_run_now_runs_single_profile(db_path, monkeypatch):
    stub = StubScraper(offers=[make_offer()])
    monkeypatch.setattr(scheduler, "SCRAPERS", {"stub_source": stub})

    profile = make_profile(db_path, max_price_per_person=5000)
    await scheduler.run_now(profile.profile_id, db_path)

    assert stub.call_count == 1
    assert len(db.get_offers_for_profile(profile, db_path)) == 1
    assert len(db.list_deals(db_path=db_path)) == 1
    assert db.get_unnotified_deals(db_path) == []  # brak konfiguracji powiadomień = i tak "wysłane"


@pytest.mark.asyncio
async def test_run_now_unknown_profile_raises(db_path):
    with pytest.raises(ValueError):
        await scheduler.run_now(999, db_path)
