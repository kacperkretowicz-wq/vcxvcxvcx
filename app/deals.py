"""Silnik wykrywania okazji (sekcja 6 planu)."""

import logging
from datetime import datetime, timedelta

from app import db
from app.config import settings
from app.models import Deal, SearchCriteria

logger = logging.getLogger(__name__)

PRICE_DROP_LOOKBACK = timedelta(hours=72)
HISTORICAL_LOW_MIN_ENTRIES = 3


def detect_deals(profile: SearchCriteria, db_path: str | None = None) -> list[Deal]:
    """Uruchamiana po każdym cyklu scrapowania, dla każdego aktywnego profilu.
    Zwraca listę NOWO wykrytych okazji (duplikaty są cicho pomijane/aktualizowane —
    patrz _maybe_renotify)."""
    if profile.profile_id is None:
        raise ValueError("detect_deals wymaga zapisanego profilu (profile_id)")

    offers = db.get_offers_for_profile(profile, db_path)
    now = datetime.now()
    new_deals: list[Deal] = []

    for offer in offers:
        for reason, detail in _evaluate_offer(offer, profile, now, db_path):
            deal = Deal(
                offer_key=offer["offer_key"],
                profile_id=profile.profile_id,
                reason=reason,
                detail=detail,
                detected_at=now,
            )
            if db.insert_deal(deal, db_path):
                new_deals.append(deal)
            else:
                _maybe_renotify(offer, profile, reason, detail, db_path)

    return new_deals


def _evaluate_offer(
    offer: dict, profile: SearchCriteria, now: datetime, db_path: str | None
) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    current_price = offer["current_price_per_person"]

    if profile.max_price_per_person is not None and current_price <= profile.max_price_per_person:
        candidates.append(
            (
                "below_budget",
                f"{current_price} PLN/os, budżet {profile.max_price_per_person} PLN",
            )
        )

    history = db.get_price_history(offer["offer_key"], db_path)

    reference = _find_price_drop_reference(history, now)
    if reference is not None and reference > 0:
        drop_pct = (reference - current_price) / reference * 100
        if drop_pct >= settings.price_drop_threshold_pct:
            candidates.append(
                (
                    "price_drop",
                    f"spadek o {drop_pct:.0f}% ({reference} → {current_price} PLN/os)",
                )
            )

    if (
        len(history) >= HISTORICAL_LOW_MIN_ENTRIES
        and current_price <= offer["lowest_price_per_person"]
    ):
        candidates.append(("historical_low", f"historyczne minimum: {current_price} PLN/os"))

    return candidates


def _find_price_drop_reference(history: list[tuple[str, int]], now: datetime) -> int | None:
    """Najstarszy wpis w historii cen z ostatnich 72h (None, jeśli brak takiego wpisu)."""
    cutoff = now - PRICE_DROP_LOOKBACK
    within_window = [
        (datetime.fromisoformat(checked_at), price)
        for checked_at, price in history
        if datetime.fromisoformat(checked_at) >= cutoff
    ]
    if not within_window:
        return None
    within_window.sort(key=lambda pair: pair[0])
    return within_window[0][1]


def _price_at_or_before(history: list[tuple[str, int]], reference_iso: str) -> int | None:
    reference = datetime.fromisoformat(reference_iso)
    candidates = [
        (datetime.fromisoformat(checked_at), price)
        for checked_at, price in history
        if datetime.fromisoformat(checked_at) <= reference
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda pair: pair[0])
    return candidates[-1][1]


def _maybe_renotify(
    offer: dict, profile: SearchCriteria, reason: str, detail: str, db_path: str | None
) -> None:
    """Jeśli okazja o tym powodzie już istnieje, ale cena spadła o kolejne
    >= PRICE_DROP_RENOTIFY_PCT od poprzedniego wykrycia, zaktualizuj szczegóły
    i wyzeruj notified_at, aby użytkownik dostał powiadomienie ponownie."""
    assert profile.profile_id is not None
    existing = db.get_deal(offer["offer_key"], profile.profile_id, reason, db_path)
    if existing is None:
        return

    history = db.get_price_history(offer["offer_key"], db_path)
    reference_price = _price_at_or_before(history, existing["detected_at"])
    if reference_price is None or reference_price <= 0:
        return

    current_price = offer["current_price_per_person"]
    drop_pct = (reference_price - current_price) / reference_price * 100
    if drop_pct >= settings.price_drop_renotify_pct:
        db.update_deal_for_renotify(
            offer["offer_key"], profile.profile_id, reason, detail, db_path
        )
        logger.info(
            "Ponowne powiadomienie: %s / profil %s / %s (dalszy spadek o %.0f%%)",
            offer["offer_key"],
            profile.profile_id,
            reason,
            drop_pct,
        )
