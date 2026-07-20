CREATE TABLE IF NOT EXISTS profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    country TEXT NOT NULL,
    region TEXT,
    date_from TEXT NOT NULL,          -- ISO: YYYY-MM-DD
    date_to TEXT NOT NULL,
    duration_min INTEGER NOT NULL DEFAULT 6,
    duration_max INTEGER NOT NULL DEFAULT 8,
    adults INTEGER NOT NULL DEFAULT 2,
    children INTEGER NOT NULL DEFAULT 0,
    board TEXT,
    max_price_per_person INTEGER,
    min_hotel_rating REAL,
    min_stars INTEGER,
    departure_airport TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS offers (
    offer_key TEXT PRIMARY KEY,       -- "{source}:{external_id}"
    source TEXT NOT NULL,
    external_id TEXT NOT NULL,
    hotel_name TEXT NOT NULL,
    country TEXT NOT NULL,
    region TEXT,
    stars REAL,
    rating REAL,
    board TEXT,
    departure_airport TEXT,
    date_start TEXT NOT NULL,
    date_end TEXT NOT NULL,
    url TEXT NOT NULL,
    current_price_per_person INTEGER NOT NULL,
    lowest_price_per_person INTEGER NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS price_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    offer_key TEXT NOT NULL REFERENCES offers(offer_key),
    checked_at TEXT NOT NULL,
    price_per_person INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS deals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    offer_key TEXT NOT NULL REFERENCES offers(offer_key),
    profile_id INTEGER NOT NULL REFERENCES profiles(id),
    reason TEXT NOT NULL,
    detail TEXT NOT NULL,
    detected_at TEXT NOT NULL,
    notified_at TEXT,                 -- NULL = jeszcze nie wysłano powiadomienia
    UNIQUE(offer_key, profile_id, reason)
);

CREATE TABLE IF NOT EXISTS scraper_health (
    source TEXT PRIMARY KEY,
    last_success TEXT,
    last_error TEXT,
    last_error_message TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_price_history_offer ON price_history(offer_key, checked_at);
CREATE INDEX IF NOT EXISTS idx_offers_country ON offers(country, date_start);
