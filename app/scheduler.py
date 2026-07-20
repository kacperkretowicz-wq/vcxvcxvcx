"""Harmonogram cyklicznego sprawdzania ofert (sekcja 8 planu)."""

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app import db, deals, notify
from app.config import settings
from app.models import SearchCriteria
from app.scrapers import SCRAPERS
from app.scrapers.base import ScraperError

logger = logging.getLogger(__name__)

MAX_CONSECUTIVE_FAILURES = 5
STALE_OFFER_DAYS = 14


def _profile_from_row(row: dict) -> SearchCriteria:
    return SearchCriteria(
        profile_id=row["id"],
        name=row["name"],
        country=row["country"],
        region=row["region"],
        date_from=row["date_from"],
        date_to=row["date_to"],
        duration_min=row["duration_min"],
        duration_max=row["duration_max"],
        adults=row["adults"],
        children=row["children"],
        board=row["board"],
        max_price_per_person=row["max_price_per_person"],
        min_hotel_rating=row["min_hotel_rating"],
        min_stars=row["min_stars"],
        departure_airport=row["departure_airport"],
    )


def _healthy_scrapers(db_path: str | None = None) -> dict:
    health = {row["source"]: row for row in db.get_scraper_health(db_path)}
    healthy = {}
    skipped = []
    for source, scraper in SCRAPERS.items():
        row = health.get(source)
        if row is not None and row["consecutive_failures"] >= MAX_CONSECUTIVE_FAILURES:
            skipped.append(source)
        else:
            healthy[source] = scraper
    if skipped:
        logger.warning(
            "Pomijam niesprawne scrapery (>=%d awarii z rzędu): %s",
            MAX_CONSECUTIVE_FAILURES,
            skipped,
        )
    return healthy


async def _run_scraper_for_profile(
    source: str, scraper, profile: SearchCriteria, db_path: str | None
) -> int:
    """Odpytuje jeden scraper dla jednego profilu, zapisuje wyniki. Zwraca
    liczbę pobranych ofert (0 przy błędzie — błąd jest łapany, nie propagowany,
    żeby awaria jednego serwisu nie przerywała całego cyklu)."""
    try:
        offers = await scraper.search(profile)
    except ScraperError as exc:
        logger.warning("Scraper %s zawiódł dla profilu %r: %s", source, profile.name, exc)
        db.record_scraper_failure(source, str(exc), db_path)
        return 0
    except Exception as exc:
        logger.exception("Scraper %s: nieoczekiwany błąd dla profilu %r", source, profile.name)
        db.record_scraper_failure(source, str(exc), db_path)
        return 0

    db.record_scraper_success(source, db_path)
    for offer in offers:
        db.upsert_offer(offer, db_path)

    await asyncio.sleep(scraper.request_delay_s)
    return len(offers)


async def run_profile(profile: SearchCriteria, db_path: str | None = None) -> None:
    """Odpytuje wszystkie sprawne scrapery dla jednego profilu, zapisuje wyniki
    i uruchamia detekcję okazji. Różne serwisy odpytywane są równolegle,
    ale w obrębie jednego serwisu zachowywana jest pauza między żądaniami
    (etykieta scrapingu z PLAN.md sekcja 1)."""
    healthy = _healthy_scrapers(db_path)
    tasks = [
        _run_scraper_for_profile(source, scraper, profile, db_path)
        for source, scraper in healthy.items()
    ]
    if tasks:
        await asyncio.gather(*tasks)

    deals.detect_deals(profile, db_path)


async def run_all_searches(db_path: str | None = None) -> None:
    """Główne zadanie harmonogramu: dla każdego aktywnego profilu sprawdza
    wszystkie sprawne scrapery, zapisuje oferty, wykrywa okazje i wysyła
    powiadomienia."""
    profiles = [_profile_from_row(row) for row in db.list_profiles(active_only=True, db_path=db_path)]
    logger.info("Start cyklu sprawdzania: %d aktywnych profili", len(profiles))

    for profile in profiles:
        try:
            await run_profile(profile, db_path)
        except Exception:
            logger.exception("Błąd podczas przetwarzania profilu %r", profile.name)

    await notify.send_pending(db_path)
    logger.info("Koniec cyklu sprawdzania")


async def run_now(profile_id: int, db_path: str | None = None) -> None:
    """Wywoływane z UI przyciskiem 'Sprawdź teraz' dla jednego profilu."""
    row = db.get_profile(profile_id, db_path)
    if row is None:
        raise ValueError(f"Nie znaleziono profilu {profile_id}")
    profile = _profile_from_row(row)
    await run_profile(profile, db_path)
    await notify.send_pending(db_path)


def cleanup_stale_offers(db_path: str | None = None) -> None:
    deleted = db.delete_stale_offers(STALE_OFFER_DAYS, db_path)
    if deleted:
        logger.info("Usunięto %d nieaktualnych ofert (bez odświeżenia od > %d dni)", deleted, STALE_OFFER_DAYS)


def create_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    for time_str in settings.check_times_list:
        hour, minute = time_str.split(":")
        scheduler.add_job(
            run_all_searches,
            trigger=CronTrigger(hour=int(hour), minute=int(minute)),
            id=f"run_all_searches_{time_str}",
            replace_existing=True,
        )
        logger.info("Zaplanowano cykl sprawdzania ofert codziennie o %s", time_str)

    scheduler.add_job(
        cleanup_stale_offers,
        trigger=CronTrigger(hour=4, minute=0),
        id="cleanup_stale_offers",
        replace_existing=True,
    )
    logger.info("Zaplanowano codzienne czyszczenie nieaktualnych ofert o 04:00")
    return scheduler
