from datetime import date, datetime

import pytest

from app import db, notify
from app.config import settings
from app.models import Deal, Offer, SearchCriteria


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test.db")
    db.init_db(path)
    return path


@pytest.fixture(autouse=True)
def disabled_channels(monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", "")
    monkeypatch.setattr(settings, "telegram_chat_id", "")
    monkeypatch.setattr(settings, "smtp_host", "")
    monkeypatch.setattr(settings, "smtp_to", "")


def _seed_deal(db_path, profile_name="Grecja wrzesień", reason="below_budget", price=3890):
    offer = Offer(
        source="wakacje_pl",
        external_id="abc",
        hotel_name="Hotel Blue Bay",
        country="Grecja",
        region="Kreta",
        stars=4.0,
        rating=8.6,
        board="AI",
        departure_airport="Warszawa",
        date_start=date(2026, 9, 12),
        date_end=date(2026, 9, 19),
        price_total=price * 2,
        price_per_person=price,
        url="https://www.wakacje.pl/oferta/123",
        scraped_at=datetime.now(),
    )
    db.upsert_offer(offer, db_path)
    profile_id = db.save_profile(
        SearchCriteria(
            name=profile_name,
            country="Grecja",
            date_from=date(2026, 9, 1),
            date_to=date(2026, 9, 30),
        ),
        db_path,
    )
    deal = Deal(
        offer_key=offer.offer_key,
        profile_id=profile_id,
        reason=reason,
        detail=f"{price} PLN/os, budżet 4000 PLN",
        detected_at=datetime.now(),
    )
    db.insert_deal(deal, db_path)
    return offer, profile_id


@pytest.mark.asyncio
async def test_send_pending_marks_notified_when_no_channel_configured(db_path):
    _seed_deal(db_path)
    assert len(db.get_unnotified_deals(db_path)) == 1

    await notify.send_pending(db_path)

    assert db.get_unnotified_deals(db_path) == []


@pytest.mark.asyncio
async def test_send_pending_noop_when_no_deals(db_path):
    await notify.send_pending(db_path)  # nie powinno rzucić wyjątku
    assert db.get_unnotified_deals(db_path) == []


@pytest.mark.asyncio
async def test_send_pending_calls_telegram_and_marks_notified(db_path, monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", "test-token")
    monkeypatch.setattr(settings, "telegram_chat_id", "12345")

    sent_messages = []

    async def fake_send(text: str) -> bool:
        sent_messages.append(text)
        return True

    monkeypatch.setattr(notify, "send_telegram_message", fake_send)

    _seed_deal(db_path)
    await notify.send_pending(db_path)

    assert len(sent_messages) == 1
    assert "Hotel Blue Bay" in sent_messages[0]
    assert "Grecja wrzesień" in sent_messages[0]
    assert db.get_unnotified_deals(db_path) == []


@pytest.mark.asyncio
async def test_send_pending_does_not_mark_notified_on_delivery_failure(db_path, monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", "test-token")
    monkeypatch.setattr(settings, "telegram_chat_id", "12345")

    async def failing_send(text: str) -> bool:
        return False

    monkeypatch.setattr(notify, "send_telegram_message", failing_send)

    _seed_deal(db_path)
    await notify.send_pending(db_path)

    assert len(db.get_unnotified_deals(db_path)) == 1


@pytest.mark.asyncio
async def test_send_pending_groups_by_profile(db_path, monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", "test-token")
    monkeypatch.setattr(settings, "telegram_chat_id", "12345")

    sent_messages = []

    async def fake_send(text: str) -> bool:
        sent_messages.append(text)
        return True

    monkeypatch.setattr(notify, "send_telegram_message", fake_send)

    _seed_deal(db_path, profile_name="Grecja wrzesień")
    _seed_deal(db_path, profile_name="Turcja sierpień")

    await notify.send_pending(db_path)

    assert len(sent_messages) == 2  # jedna wiadomość na profil
    assert db.get_unnotified_deals(db_path) == []


def test_fmt_date_range_same_month():
    assert notify._fmt_date_range("2026-09-12", "2026-09-19") == "12–19.09"


def test_fmt_date_range_different_months():
    assert notify._fmt_date_range("2026-09-28", "2026-10-05") == "28.09–05.10"


@pytest.mark.parametrize(
    "n,expected",
    [
        (1, "nowa okazja"),
        (2, "nowe okazje"),
        (4, "nowe okazje"),
        (5, "nowych okazji"),
        (12, "nowych okazji"),
        (22, "nowe okazje"),
    ],
)
def test_pluralize_deals(n, expected):
    assert notify._pluralize_deals(n) == expected
