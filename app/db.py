import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from app.config import settings
from app.models import Deal, Offer, SearchCriteria

SCHEMA_PATH = Path(__file__).parent / "schema.sql"

# Nie zapisuj kolejnego wpisu w historii cen, jeśli cena się nie zmieniła
# i ostatni wpis jest świeższy niż ten interwał (żeby historia nie puchła
# przy kilku odczytach dziennie z tą samą ceną).
PRICE_HISTORY_MIN_GAP = timedelta(hours=20)


def get_connection(db_path: str | None = None) -> sqlite3.Connection:
    path = db_path or settings.database_path
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: str | None = None) -> None:
    conn = get_connection(db_path)
    try:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()


def upsert_offer(offer: Offer, db_path: str | None = None) -> bool:
    """Zapisuje/aktualizuje ofertę. Zwraca True, jeśli oferta jest nowa."""
    conn = get_connection(db_path)
    try:
        now = offer.scraped_at.isoformat()
        existing = conn.execute(
            "SELECT lowest_price_per_person FROM offers WHERE offer_key = :offer_key",
            {"offer_key": offer.offer_key},
        ).fetchone()
        is_new = existing is None

        if is_new:
            lowest_price = offer.price_per_person
            conn.execute(
                """
                INSERT INTO offers (
                    offer_key, source, external_id, hotel_name, country, region,
                    stars, rating, board, departure_airport, date_start, date_end,
                    url, current_price_per_person, lowest_price_per_person,
                    first_seen, last_seen
                ) VALUES (
                    :offer_key, :source, :external_id, :hotel_name, :country, :region,
                    :stars, :rating, :board, :departure_airport, :date_start, :date_end,
                    :url, :price, :lowest_price, :now, :now
                )
                """,
                {
                    "offer_key": offer.offer_key,
                    "source": offer.source,
                    "external_id": offer.external_id,
                    "hotel_name": offer.hotel_name,
                    "country": offer.country,
                    "region": offer.region,
                    "stars": offer.stars,
                    "rating": offer.rating,
                    "board": offer.board,
                    "departure_airport": offer.departure_airport,
                    "date_start": offer.date_start.isoformat(),
                    "date_end": offer.date_end.isoformat(),
                    "url": offer.url,
                    "price": offer.price_per_person,
                    "lowest_price": lowest_price,
                    "now": now,
                },
            )
        else:
            lowest_price = min(existing["lowest_price_per_person"], offer.price_per_person)
            conn.execute(
                """
                UPDATE offers SET
                    hotel_name = :hotel_name,
                    stars = :stars,
                    rating = :rating,
                    board = :board,
                    departure_airport = :departure_airport,
                    url = :url,
                    current_price_per_person = :price,
                    lowest_price_per_person = :lowest_price,
                    last_seen = :now
                WHERE offer_key = :offer_key
                """,
                {
                    "hotel_name": offer.hotel_name,
                    "stars": offer.stars,
                    "rating": offer.rating,
                    "board": offer.board,
                    "departure_airport": offer.departure_airport,
                    "url": offer.url,
                    "price": offer.price_per_person,
                    "lowest_price": lowest_price,
                    "now": now,
                    "offer_key": offer.offer_key,
                },
            )

        last_history = conn.execute(
            """
            SELECT checked_at, price_per_person FROM price_history
            WHERE offer_key = :offer_key ORDER BY checked_at DESC LIMIT 1
            """,
            {"offer_key": offer.offer_key},
        ).fetchone()

        should_record = True
        if last_history is not None:
            same_price = last_history["price_per_person"] == offer.price_per_person
            last_checked = datetime.fromisoformat(last_history["checked_at"])
            recent_enough = (offer.scraped_at - last_checked) < PRICE_HISTORY_MIN_GAP
            if same_price and recent_enough:
                should_record = False

        if should_record:
            conn.execute(
                """
                INSERT INTO price_history (offer_key, checked_at, price_per_person)
                VALUES (:offer_key, :now, :price)
                """,
                {"offer_key": offer.offer_key, "now": now, "price": offer.price_per_person},
            )

        conn.commit()
        return is_new
    finally:
        conn.close()


def get_offers_for_profile(criteria: SearchCriteria, db_path: str | None = None) -> list[dict]:
    """Oferty pasujące do lokalizacji/dat/parametrów profilu (BEZ filtra budżetu —
    budżet i inne reguły okazji ocenia app/deals.py)."""
    conn = get_connection(db_path)
    try:
        clauses = [
            "lower(country) = lower(:country)",
            "date_start >= :date_from",
            "date_start <= :date_to",
            "CAST(julianday(date_end) - julianday(date_start) AS INTEGER) BETWEEN :duration_min AND :duration_max",
        ]
        params: dict = {
            "country": criteria.country,
            "date_from": criteria.date_from.isoformat(),
            "date_to": criteria.date_to.isoformat(),
            "duration_min": criteria.duration_min,
            "duration_max": criteria.duration_max,
        }

        if criteria.region:
            clauses.append("lower(region) = lower(:region)")
            params["region"] = criteria.region

        if criteria.board:
            clauses.append("board = :board")
            params["board"] = criteria.board

        if criteria.min_stars is not None:
            clauses.append("stars IS NOT NULL AND stars >= :min_stars")
            params["min_stars"] = criteria.min_stars

        if criteria.min_hotel_rating is not None:
            clauses.append("rating IS NOT NULL AND rating >= :min_hotel_rating")
            params["min_hotel_rating"] = criteria.min_hotel_rating

        if criteria.departure_airport:
            clauses.append("lower(departure_airport) = lower(:departure_airport)")
            params["departure_airport"] = criteria.departure_airport

        query = "SELECT * FROM offers WHERE " + " AND ".join(clauses) + " ORDER BY current_price_per_person ASC"
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def save_profile(criteria: SearchCriteria, db_path: str | None = None) -> int:
    conn = get_connection(db_path)
    try:
        payload = {
            "name": criteria.name,
            "country": criteria.country,
            "region": criteria.region,
            "date_from": criteria.date_from.isoformat(),
            "date_to": criteria.date_to.isoformat(),
            "duration_min": criteria.duration_min,
            "duration_max": criteria.duration_max,
            "adults": criteria.adults,
            "children": criteria.children,
            "board": criteria.board,
            "max_price_per_person": criteria.max_price_per_person,
            "min_hotel_rating": criteria.min_hotel_rating,
            "min_stars": criteria.min_stars,
            "departure_airport": criteria.departure_airport,
        }
        if criteria.profile_id is None:
            columns = ", ".join(payload.keys())
            placeholders = ", ".join(f":{key}" for key in payload)
            cursor = conn.execute(
                f"INSERT INTO profiles ({columns}) VALUES ({placeholders})", payload
            )
            conn.commit()
            return int(cursor.lastrowid)
        else:
            payload["id"] = criteria.profile_id
            set_clause = ", ".join(f"{key} = :{key}" for key in payload if key != "id")
            conn.execute(
                f"UPDATE profiles SET {set_clause} WHERE id = :id", payload
            )
            conn.commit()
            return criteria.profile_id
    finally:
        conn.close()


def list_profiles(active_only: bool = False, db_path: str | None = None) -> list[dict]:
    conn = get_connection(db_path)
    try:
        query = "SELECT * FROM profiles"
        if active_only:
            query += " WHERE active = 1"
        query += " ORDER BY created_at DESC"
        rows = conn.execute(query).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_profile(profile_id: int, db_path: str | None = None) -> dict | None:
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM profiles WHERE id = :id", {"id": profile_id}
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def delete_profile(profile_id: int, db_path: str | None = None) -> None:
    conn = get_connection(db_path)
    try:
        conn.execute("DELETE FROM deals WHERE profile_id = :id", {"id": profile_id})
        conn.execute("DELETE FROM profiles WHERE id = :id", {"id": profile_id})
        conn.commit()
    finally:
        conn.close()


def set_profile_active(profile_id: int, active: bool, db_path: str | None = None) -> None:
    conn = get_connection(db_path)
    try:
        conn.execute(
            "UPDATE profiles SET active = :active WHERE id = :id",
            {"active": int(active), "id": profile_id},
        )
        conn.commit()
    finally:
        conn.close()


def insert_deal(deal: Deal, db_path: str | None = None) -> bool:
    """Zwraca True, jeśli wstawiono nową okazję (a nie duplikat)."""
    conn = get_connection(db_path)
    try:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO deals (offer_key, profile_id, reason, detail, detected_at)
            VALUES (:offer_key, :profile_id, :reason, :detail, :detected_at)
            """,
            {
                "offer_key": deal.offer_key,
                "profile_id": deal.profile_id,
                "reason": deal.reason,
                "detail": deal.detail,
                "detected_at": deal.detected_at.isoformat(),
            },
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def get_deal(
    offer_key: str, profile_id: int, reason: str, db_path: str | None = None
) -> dict | None:
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            """
            SELECT * FROM deals
            WHERE offer_key = :offer_key AND profile_id = :profile_id AND reason = :reason
            """,
            {"offer_key": offer_key, "profile_id": profile_id, "reason": reason},
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def update_deal_for_renotify(
    offer_key: str, profile_id: int, reason: str, detail: str, db_path: str | None = None
) -> None:
    """Aktualizuje istniejącą okazję i zeruje notified_at, aby wysłać powiadomienie ponownie."""
    conn = get_connection(db_path)
    try:
        conn.execute(
            """
            UPDATE deals SET detail = :detail, notified_at = NULL
            WHERE offer_key = :offer_key AND profile_id = :profile_id AND reason = :reason
            """,
            {
                "detail": detail,
                "offer_key": offer_key,
                "profile_id": profile_id,
                "reason": reason,
            },
        )
        conn.commit()
    finally:
        conn.close()


def get_unnotified_deals(db_path: str | None = None) -> list[dict]:
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            """
            SELECT deals.*, offers.hotel_name, offers.url, offers.stars, offers.rating,
                   offers.board, offers.departure_airport, offers.date_start, offers.date_end,
                   offers.current_price_per_person, profiles.name AS profile_name
            FROM deals
            JOIN offers ON offers.offer_key = deals.offer_key
            JOIN profiles ON profiles.id = deals.profile_id
            WHERE deals.notified_at IS NULL
            ORDER BY deals.profile_id, deals.detected_at
            """
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def mark_deal_notified(deal_id: int, db_path: str | None = None) -> None:
    conn = get_connection(db_path)
    try:
        conn.execute(
            "UPDATE deals SET notified_at = :now WHERE id = :id",
            {"now": datetime.now().isoformat(), "id": deal_id},
        )
        conn.commit()
    finally:
        conn.close()


def list_deals(db_path: str | None = None, limit: int = 200) -> list[dict]:
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            """
            SELECT deals.*, offers.hotel_name, offers.url, offers.stars, offers.rating,
                   offers.board, offers.departure_airport, offers.date_start, offers.date_end,
                   offers.current_price_per_person, profiles.name AS profile_name
            FROM deals
            JOIN offers ON offers.offer_key = deals.offer_key
            JOIN profiles ON profiles.id = deals.profile_id
            ORDER BY deals.detected_at DESC
            LIMIT :limit
            """,
            {"limit": limit},
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def record_scraper_success(source: str, db_path: str | None = None) -> None:
    conn = get_connection(db_path)
    try:
        now = datetime.now().isoformat()
        conn.execute(
            """
            INSERT INTO scraper_health (source, last_success, consecutive_failures)
            VALUES (:source, :now, 0)
            ON CONFLICT(source) DO UPDATE SET last_success = :now, consecutive_failures = 0
            """,
            {"source": source, "now": now},
        )
        conn.commit()
    finally:
        conn.close()


def record_scraper_failure(source: str, message: str, db_path: str | None = None) -> None:
    conn = get_connection(db_path)
    try:
        now = datetime.now().isoformat()
        conn.execute(
            """
            INSERT INTO scraper_health (source, last_error, last_error_message, consecutive_failures)
            VALUES (:source, :now, :message, 1)
            ON CONFLICT(source) DO UPDATE SET
                last_error = :now,
                last_error_message = :message,
                consecutive_failures = consecutive_failures + 1
            """,
            {"source": source, "now": now, "message": message},
        )
        conn.commit()
    finally:
        conn.close()


def get_scraper_health(db_path: str | None = None) -> list[dict]:
    conn = get_connection(db_path)
    try:
        rows = conn.execute("SELECT * FROM scraper_health ORDER BY source").fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_price_history(offer_key: str, db_path: str | None = None) -> list[tuple[str, int]]:
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            """
            SELECT checked_at, price_per_person FROM price_history
            WHERE offer_key = :offer_key ORDER BY checked_at ASC
            """,
            {"offer_key": offer_key},
        ).fetchall()
        return [(row["checked_at"], row["price_per_person"]) for row in rows]
    finally:
        conn.close()


def delete_stale_offers(older_than_days: int, db_path: str | None = None) -> int:
    """Usuwa oferty nieodświeżone od > older_than_days dni. Zwraca liczbę usuniętych."""
    conn = get_connection(db_path)
    try:
        cutoff = (datetime.now() - timedelta(days=older_than_days)).isoformat()
        stale_keys = [
            row["offer_key"]
            for row in conn.execute(
                "SELECT offer_key FROM offers WHERE last_seen < :cutoff", {"cutoff": cutoff}
            ).fetchall()
        ]
        for key in stale_keys:
            conn.execute("DELETE FROM deals WHERE offer_key = :key", {"key": key})
            conn.execute("DELETE FROM price_history WHERE offer_key = :key", {"key": key})
            conn.execute("DELETE FROM offers WHERE offer_key = :key", {"key": key})
        conn.commit()
        return len(stale_keys)
    finally:
        conn.close()
