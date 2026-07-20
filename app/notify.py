"""Powiadomienia o wykrytych okazjach (sekcja 10 planu)."""

import asyncio
import html as html_module
import logging
import smtplib
from collections import defaultdict
from datetime import date
from email.mime.text import MIMEText

import httpx

from app import db
from app.config import settings

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT_S = 15.0
TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"

REASON_ICONS = {
    "below_budget": "💰",
    "price_drop": "🔻",
    "historical_low": "🏆",
}


async def send_pending(db_path: str | None = None) -> None:
    """Wysyła powiadomienia o niewysłanych jeszcze okazjach, grupując je po
    profilu (jedna wiadomość na profil na cykl)."""
    unnotified = db.get_unnotified_deals(db_path)
    if not unnotified:
        return

    by_profile: dict[int, list[dict]] = defaultdict(list)
    for deal in unnotified:
        by_profile[deal["profile_id"]].append(deal)

    for profile_deals in by_profile.values():
        await _send_for_profile(profile_deals, db_path)


async def _send_for_profile(profile_deals: list[dict], db_path: str | None) -> None:
    text = _build_message(profile_deals)
    any_channel_configured = settings.telegram_enabled or settings.smtp_enabled
    delivered = not any_channel_configured  # brak konfiguracji = i tak OK (sekcja 10)

    if settings.telegram_enabled:
        if await send_telegram_message(text):
            delivered = True

    if settings.smtp_enabled:
        subject = f"Nowe okazje: {profile_deals[0]['profile_name']}"
        if await send_email(subject, text.replace("\n", "<br>")):
            delivered = True

    if delivered:
        for deal in profile_deals:
            db.mark_deal_notified(deal["id"], db_path)


# --- Telegram ----------------------------------------------------------------


async def send_telegram_message(text: str) -> bool:
    url = TELEGRAM_API_URL.format(token=settings.telegram_bot_token)
    payload = {
        "chat_id": settings.telegram_chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_S) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
        return True
    except Exception:
        logger.exception("Błąd wysyłki powiadomienia Telegram")
        return False


# --- E-mail --------------------------------------------------------------


def _send_email_sync(subject: str, html_body: str) -> None:
    msg = MIMEText(html_body, "html", "utf-8")
    msg["Subject"] = subject
    msg["From"] = settings.smtp_user or settings.smtp_host
    msg["To"] = settings.smtp_to

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=REQUEST_TIMEOUT_S) as server:
        server.starttls()
        if settings.smtp_user:
            server.login(settings.smtp_user, settings.smtp_password)
        server.sendmail(msg["From"], [settings.smtp_to], msg.as_string())


async def send_email(subject: str, html_body: str) -> bool:
    try:
        await asyncio.to_thread(_send_email_sync, subject, html_body)
        return True
    except Exception:
        logger.exception("Błąd wysyłki e-mail")
        return False


# --- Budowanie treści wiadomości --------------------------------------------


def _build_message(profile_deals: list[dict]) -> str:
    profile_name = profile_deals[0]["profile_name"]
    header = f"🏖 <b>{html_module.escape(profile_name)}</b> — {_pluralize_deals(len(profile_deals))}"
    lines = [header]
    for deal in profile_deals:
        lines.append(_format_deal_line(deal))
    return "\n".join(lines)


def _format_deal_line(deal: dict) -> str:
    icon = REASON_ICONS.get(deal["reason"], "▪️")
    stars = f" ⭐{deal['stars']:.1f}" if deal.get("stars") is not None else ""
    rating = f" ({deal['rating']:.1f}/10)" if deal.get("rating") is not None else ""
    board = f", {deal['board']}" if deal.get("board") else ""
    airport = f", z {deal['departure_airport']}" if deal.get("departure_airport") else ""
    dates = _fmt_date_range(deal["date_start"], deal["date_end"])
    hotel = html_module.escape(deal["hotel_name"])
    return (
        f"{icon} {hotel}{stars}{rating}{board}, {dates}{airport}\n"
        f"   {html_module.escape(deal['detail'])}\n"
        f"   {deal['url']}"
    )


def _fmt_date_range(date_start: str, date_end: str) -> str:
    start = date.fromisoformat(date_start)
    end = date.fromisoformat(date_end)
    if start.month == end.month:
        return f"{start.day:02d}–{end.day:02d}.{end.month:02d}"
    return f"{start.day:02d}.{start.month:02d}–{end.day:02d}.{end.month:02d}"


def _pluralize_deals(n: int) -> str:
    if n == 1:
        return "nowa okazja"
    if 2 <= n % 10 <= 4 and not (12 <= n % 100 <= 14):
        return "nowe okazje"
    return "nowych okazji"
