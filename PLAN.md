# Plan: Tracker Okazji Wakacyjnych (Wakacje Deals Tracker)

> **Dla kogo jest ten dokument:** dla modelu AI (lub programisty), który będzie implementował
> to narzędzie. Wykonuj etapy **po kolei**, jeden po drugim. Nie przechodź do następnego
> etapu, dopóki kryteria akceptacji poprzedniego nie są spełnione. Wszystkie nazwy plików,
> funkcji i schematy w tym dokumencie są **wiążące** — używaj ich dokładnie tak, jak podano.

---

## 1. Cel narzędzia

Aplikacja, która:

1. Pozwala użytkownikowi w **kilka kliknięć** zdefiniować profil wyszukiwania:
   kierunek (kraj/region), zakres dat wylotu, długość pobytu, liczba osób, wyżywienie,
   maksymalna cena za osobę, minimalna ocena hotelu.
2. **Cyklicznie** (np. 3× dziennie) odpytuje serwisy turystyczne:
   `wakacje.pl`, `itaka.pl`, `tui.pl`, `coraltravel.pl`, `lastminuter.pl`.
3. Zapisuje oferty i **historię cen** w lokalnej bazie danych.
4. Wykrywa **okazje** (spadek ceny, cena poniżej budżetu, historyczne minimum).
5. Wysyła **powiadomienia** (Telegram i/lub e-mail) i pokazuje wyniki w prostym
   **panelu webowym**.

### Ważne fakty, które musisz znać przed startem

- **Żaden z tych serwisów nie ma oficjalnego, publicznego API.** Dane pozyskujemy przez
  scraping: najpierw próbujemy znaleźć **wewnętrzne endpointy JSON/XHR** strony (stabilniejsze),
  a dopiero w ostateczności parsujemy HTML przez Playwright.
- **`wakacje.pl` jest agregatorem** — pokazuje oferty niemal wszystkich polskich
  touroperatorów (Itaka, TUI, Coral Travel, Rainbow, Join UP! itd.). Dlatego **MVP oparte
  tylko o wakacje.pl już pokrywa większość rynku**. Scrapery pozostałych serwisów to
  rozszerzenie, nie fundament.
- Scrapery **będą się psuć**, gdy serwisy zmienią strukturę stron. Architektura musi
  izolować scrapery od reszty systemu (awaria jednego nie może wywalić całości).
- **Etykieta scrapingu (obowiązkowa):** narzędzie do użytku prywatnego; odpytuj rzadko
  (2–4 razy dziennie, NIE co minutę), rób pauzy 5–10 s między żądaniami do tego samego
  serwisu, ustaw realistyczny nagłówek User-Agent, respektuj `robots.txt` tam, gdzie to
  możliwe, cache'uj wyniki. Nie obchodź CAPTCHA — jeśli serwis blokuje, oznacz scraper
  jako niesprawny i idź dalej.

---

## 2. Stos technologiczny (wiążący)

| Warstwa | Technologia | Uwagi |
|---|---|---|
| Język | Python 3.11+ | |
| Scraping (XHR) | `httpx` | preferowana ścieżka |
| Scraping (przeglądarka) | `playwright` (Chromium, headless) | fallback, gdy nie ma endpointu JSON |
| Baza danych | SQLite (moduł `sqlite3` ze standardowej biblioteki) | plik `data/app.db` |
| Web UI + API | `FastAPI` + szablony `Jinja2` | proste formularze HTML, bez Reacta |
| Harmonogram | `APScheduler` | uruchamiany w procesie FastAPI |
| Powiadomienia | Telegram Bot API (przez `httpx`), opcjonalnie SMTP | Telegram jako domyślne |
| Walidacja danych | `pydantic` v2 | modele `Offer`, `SearchCriteria` |
| Testy | `pytest` | scrapery testowane na zapisanych snapshotach |
| Konfiguracja | plik `.env` + `pydantic-settings` | |

Plik `requirements.txt`:

```
fastapi
uvicorn[standard]
jinja2
httpx
playwright
apscheduler
pydantic
pydantic-settings
python-multipart
pytest
```

---

## 3. Struktura katalogów (wiążąca)

```
vcxvcxvcx/
├── PLAN.md                  # ten dokument
├── requirements.txt
├── .env.example             # wzór konfiguracji (bez sekretów)
├── README.md                # instrukcja uruchomienia (napisz na końcu, etap 8)
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI app + start APScheduler
│   ├── config.py            # pydantic-settings: wczytanie .env
│   ├── models.py            # pydantic: SearchCriteria, Offer, Deal
│   ├── db.py                # inicjalizacja SQLite + wszystkie funkcje zapisu/odczytu
│   ├── schema.sql           # schemat bazy (sekcja 5)
│   ├── deals.py             # silnik wykrywania okazji (sekcja 6)
│   ├── scheduler.py         # definicja zadań cyklicznych
│   ├── notify.py            # wysyłka Telegram / e-mail
│   ├── scrapers/
│   │   ├── __init__.py      # rejestr scraperów: SCRAPERS = {"wakacje_pl": ..., ...}
│   │   ├── base.py          # klasa bazowa BaseScraper
│   │   ├── wakacje_pl.py    # ETAP 2 (najważniejszy)
│   │   ├── itaka.py         # ETAP 7
│   │   ├── tui.py           # ETAP 7
│   │   ├── coraltravel.py   # ETAP 7
│   │   └── lastminuter.py   # ETAP 7
│   ├── templates/           # Jinja2: base.html, profiles.html, offers.html, deals.html
│   └── static/              # style.css (minimalny, bez frameworków)
├── data/                    # app.db (w .gitignore)
├── snapshots/               # zapisane odpowiedzi HTML/JSON do testów (commitowane)
└── tests/
    ├── test_db.py
    ├── test_deals.py
    └── test_scrapers.py
```

Do `.gitignore` dodaj: `data/`, `.env`, `__pycache__/`, `.pytest_cache/`.

---

## 4. Modele danych (`app/models.py`)

Zaimplementuj dokładnie te modele pydantic:

```python
from datetime import date, datetime
from pydantic import BaseModel

class SearchCriteria(BaseModel):
    """Kryteria jednego profilu wyszukiwania — to wypełnia użytkownik w UI."""
    profile_id: int | None = None
    name: str                      # np. "Grecja wrzesień"
    country: str                   # np. "Grecja" (jedna wartość; wiele krajów = wiele profili)
    region: str | None = None      # np. "Kreta", opcjonalne
    date_from: date                # najwcześniejszy akceptowany wylot
    date_to: date                  # najpóźniejszy akceptowany wylot
    duration_min: int = 6          # noclegi, min
    duration_max: int = 8          # noclegi, max
    adults: int = 2
    children: int = 0
    board: str | None = None       # None = dowolne; wartości: "AI", "HB", "BB", "SC"
    max_price_per_person: int | None = None   # PLN; None = bez limitu
    min_hotel_rating: float | None = None     # skala 1–10 (jak na wakacje.pl)
    min_stars: int | None = None              # 1–5
    departure_airport: str | None = None      # np. "Warszawa"; None = dowolne

class Offer(BaseModel):
    """Jedna oferta zwrócona przez scraper. Wszystkie scrapery zwracają TEN format."""
    source: str                    # "wakacje_pl" | "itaka" | "tui" | "coraltravel" | "lastminuter"
    external_id: str               # stabilny identyfikator oferty w źródle (patrz uwaga niżej)
    hotel_name: str
    country: str
    region: str | None = None
    stars: float | None = None     # 1.0–5.0
    rating: float | None = None    # ocena klientów 1–10, jeśli dostępna
    board: str | None = None       # znormalizowane: "AI", "HB", "BB", "SC", "OB" (sekcja 4.1)
    departure_airport: str | None = None
    date_start: date
    date_end: date
    price_total: int               # PLN, cena całkowita za wszystkich podróżnych
    price_per_person: int          # PLN
    url: str                       # bezpośredni link do oferty
    scraped_at: datetime

class Deal(BaseModel):
    """Wykryta okazja powiązana z ofertą i profilem."""
    offer_key: str
    profile_id: int
    reason: str                    # "below_budget" | "price_drop" | "historical_low"
    detail: str                    # np. "spadek o 18% (4200 → 3444 PLN/os)"
    detected_at: datetime
```

**Uwaga o `external_id`:** jeśli serwis nie daje stabilnego ID, wygeneruj je jako
`sha1(hotel_name + date_start + date_end + board + departure_airport)[:16]`.
Klucz deduplikacji oferty w bazie to para `(source, external_id)` — nazywamy ją `offer_key`
w formacie `"{source}:{external_id}"`.

### 4.1 Normalizacja wyżywienia (board)

Każdy serwis nazywa wyżywienie inaczej. W `app/scrapers/base.py` zaimplementuj funkcję
`normalize_board(raw: str) -> str | None` mapującą (bez rozróżniania wielkości liter,
dopasowanie po fragmencie):

- zawiera "all inclusive" lub "all incl" → `"AI"`
- zawiera "2 posiłki", "śniadania i obiadokolacje", "half board", "HB" → `"HB"`
- zawiera "śniadani" (samo), "bed & breakfast", "BB" → `"BB"`
- zawiera "bez wyżywienia", "self", "SC" → `"SC"`
- zawiera "tylko nocleg", "overnight", "OB" → `"OB"`
- nic nie pasuje → zwróć `None` i zaloguj ostrzeżenie z surową wartością

---

## 5. Schemat bazy (`app/schema.sql`)

```sql
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
```

W `app/db.py` zaimplementuj funkcje (wszystkie przyjmują/zwracają modele z `models.py`):

- `init_db()` — wykonuje `schema.sql`
- `upsert_offer(offer: Offer) -> bool` — INSERT lub UPDATE po `offer_key`; aktualizuje
  `current_price_per_person`, `last_seen`, obniża `lowest_price_per_person` jeśli trzeba;
  **zawsze** dopisuje wiersz do `price_history`, ale tylko gdy cena różni się od
  ostatniego wpisu w historii LUB ostatni wpis jest starszy niż 20 godzin
  (żeby historia nie puchła). Zwraca `True`, jeśli oferta jest nowa.
- `get_offers_for_profile(criteria: SearchCriteria) -> list[dict]` — filtruje ofertę po
  kraju, datach, budżecie, gwiazdkach, ocenie, wyżywieniu
- `save_profile`, `list_profiles`, `get_profile`, `delete_profile`, `set_profile_active`
- `insert_deal(deal: Deal) -> bool` — `INSERT OR IGNORE`; zwraca `True` jeśli wstawiono nowy
- `get_unnotified_deals() -> list[dict]`, `mark_deal_notified(deal_id)`
- `record_scraper_success(source)`, `record_scraper_failure(source, message)`
- `get_price_history(offer_key) -> list[tuple[str, int]]`

---

## 6. Silnik okazji (`app/deals.py`)

Funkcja główna:

```python
def detect_deals(profile: SearchCriteria) -> list[Deal]:
    """Uruchamiana po każdym cyklu scrapowania, dla każdego aktywnego profilu."""
```

Dla każdej oferty pasującej do profilu (z `get_offers_for_profile`) sprawdź reguły —
oferta może wygenerować kilka okazji o różnych `reason`:

1. **`below_budget`** — `current_price_per_person <= profile.max_price_per_person`
   (tylko jeśli budżet ustawiony). `detail`: `"3890 PLN/os, budżet 4000 PLN"`.
2. **`price_drop`** — cena spadła o **≥ 10%** względem ceny sprzed 24–72 h
   (weź najstarszy wpis z `price_history` z ostatnich 72 h i porównaj z aktualną).
   `detail`: `"spadek o 18% (4200 → 3444 PLN/os)"`.
3. **`historical_low`** — `current_price_per_person <= lowest_price_per_person`
   ORAZ oferta ma ≥ 3 wpisy w historii cen (żeby nie oznaczać każdej nowej oferty).
   `detail`: `"historyczne minimum: 3444 PLN/os"`.

Deduplikacja: `UNIQUE(offer_key, profile_id, reason)` w bazie załatwia sprawę —
`insert_deal` zwróci `False` dla powtórki i wtedy nie wysyłamy ponownego powiadomienia.
Wyjątek: jeśli dla istniejącego deala cena spadła o kolejne ≥ 5%, zaktualizuj `detail`,
wyzeruj `notified_at` (powiadomimy ponownie).

---

## 7. Scrapery

### 7.1 Klasa bazowa (`app/scrapers/base.py`)

```python
from abc import ABC, abstractmethod
from app.models import SearchCriteria, Offer

class BaseScraper(ABC):
    source_name: str          # np. "wakacje_pl"
    request_delay_s: float = 7.0   # pauza między żądaniami do serwisu

    @abstractmethod
    async def search(self, criteria: SearchCriteria) -> list[Offer]:
        """Zwraca listę ofert dla podanych kryteriów. Rzuca ScraperError przy awarii."""

class ScraperError(Exception):
    pass
```

Zasady wspólne dla wszystkich scraperów:

- User-Agent: aktualny desktopowy Chrome, np.
  `Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36`.
- `asyncio.sleep(self.request_delay_s)` między kolejnymi żądaniami/stronami wyników.
- Timeout żądania: 30 s. Maks. 3 strony wyników na jedno wyszukiwanie (wystarczy;
  sortuj po cenie rosnąco, jeśli serwis na to pozwala).
- Każdy scraper łapie własne wyjątki i rzuca `ScraperError` z czytelnym komunikatem.
- Po udanym przebiegu wywołaj `record_scraper_success`, po nieudanym `record_scraper_failure`.
  Jeśli `consecutive_failures >= 5`, scheduler pomija ten scraper i loguje ostrzeżenie
  (nadal widoczne w UI na stronie „Status”).

### 7.2 Jak znaleźć wewnętrzne API serwisu (procedura — wykonaj ją dla każdego serwisu)

To jest najtrudniejsza część projektu i **nie da się jej napisać „na ślepo”**. Struktury
stron zmieniają się, dlatego NIE podaję tu gotowych selektorów ani URL-i endpointów —
musisz je ustalić samodzielnie według tej procedury:

1. Uruchom Playwright w trybie **nie**-headless lokalnie (albo użyj zwykłej przeglądarki
   z DevTools) i wejdź na stronę wyszukiwania serwisu.
2. Otwórz kartę **Network**, filtr **Fetch/XHR**. Wykonaj ręcznie wyszukiwanie
   (np. Grecja, wrzesień, 2 osoby, All Inclusive).
3. Znajdź żądanie, którego odpowiedź JSON zawiera listę ofert (szukaj w odpowiedziach
   nazw hoteli i cen). Zanotuj: metodę (GET/POST), URL, parametry/payload, wymagane
   nagłówki i cookies.
4. **Ścieżka A (preferowana):** odtwórz to żądanie w `httpx`. Jeśli działa bez cookies
   sesyjnych — świetnie. Jeśli wymaga cookies/tokenów — pobierz je raz przez Playwright
   (`context.cookies()`), przekaż do `httpx` i odświeżaj przy błędzie 401/403.
5. **Ścieżka B (fallback):** jeśli endpoint jest nie do odtworzenia (podpisywane żądania,
   Cloudflare), użyj Playwright: wejdź na URL wyników wyszukiwania (większość serwisów
   koduje kryteria w URL — ustal format, zmieniając filtry i obserwując adres), poczekaj
   na załadowanie kart ofert, sparsuj DOM. Selektory trzymaj w **jednym słowniku na górze
   pliku** scrapera, żeby naprawa po zmianie strony była jednym miejscem edycji.
6. **Zawsze zapisz przykładową odpowiedź** (JSON lub HTML) do `snapshots/{source}/…`
   i napisz test parsera działający na tym pliku (sekcja 10). Parser (funkcja
   `parse_offers(raw) -> list[Offer]`) musi być **oddzielony** od pobierania, żeby dało
   się go testować offline.

### 7.3 Kolejność implementacji serwisów

| Priorytet | Serwis | Moduł | Dlaczego |
|---|---|---|---|
| 1 (ETAP 2) | wakacje.pl | `wakacje_pl.py` | agregator — pokrywa większość touroperatorów |
| 2 (ETAP 7) | itaka.pl | `itaka.py` | duży touroperator, bywa tańszy u źródła |
| 3 (ETAP 7) | tui.pl | `tui.py` | jw. |
| 4 (ETAP 7) | coraltravel.pl | `coraltravel.py` | jw. |
| 5 (ETAP 7) | lastminuter.pl | `lastminuter.py` | agregator last minute |

W `app/scrapers/__init__.py` utrzymuj rejestr:

```python
SCRAPERS: dict[str, BaseScraper] = {}  # wypełniany w miarę implementacji
```

Scheduler i UI iterują po tym rejestrze — dodanie serwisu nie wymaga zmian nigdzie indziej.

---

## 8. Harmonogram (`app/scheduler.py`)

- APScheduler `AsyncIOScheduler`, startowany w `app/main.py` przy starcie FastAPI
  (lifespan handler).
- Zadanie `run_all_searches()`: dla każdego **aktywnego** profilu × każdego sprawnego
  scrapera wywołaj `search()`, wyniki zapisz przez `upsert_offer`, potem uruchom
  `detect_deals(profile)`, potem `notify.send_pending()`.
- Harmonogram: **3× dziennie** o 07:30, 13:30, 20:30 czasu lokalnego (cron trigger).
  Godziny konfigurowalne w `.env` (`CHECK_TIMES=07:30,13:30,20:30`).
- Sekwencyjnie, nie równolegle między serwisami (etykieta scrapingu); równoległość
  między RÓŻNYMI serwisami jest OK (`asyncio.gather` po jednym tasku na serwis).
- Dodatkowo funkcja `run_now(profile_id)` wywoływana z UI przyciskiem „Sprawdź teraz”.

---

## 9. Panel webowy (`app/main.py` + szablony)

Minimalny, formularze HTML + Jinja2, bez JS-frameworków. Strony:

1. **`GET /`** — lista profili + przycisk „Nowy profil” + dla każdego profilu:
   liczba pasujących ofert, najniższa aktualna cena, przyciski
   „Wyniki” / „Sprawdź teraz” (POST `/profiles/{id}/run`) / „Edytuj” / „Usuń” /
   włącz-wyłącz (checkbox `active`).
2. **`GET /profiles/new`**, **`POST /profiles`** — formularz z polami z `SearchCriteria`
   (selecty dla kraju/wyżywienia/lotniska, inputy date dla dat). Edycja analogicznie.
3. **`GET /profiles/{id}/offers`** — tabela ofert pasujących do profilu, sortowana po
   cenie: hotel, ⭐, ocena, termin, wyżywienie, wylot z, cena/os (+ strzałka ↓ i procent,
   jeśli cena spadła vs poprzedni odczyt), źródło, link „Otwórz ofertę”.
   Obok ceny link „historia” → **`GET /offers/{offer_key}/history`** (prosta tabela
   data → cena; wykres NIE jest wymagany w MVP).
4. **`GET /deals`** — lista wykrytych okazji (najnowsze pierwsze) z powodem i szczegółem.
5. **`GET /status`** — tabela `scraper_health`: źródło, ostatni sukces, ostatni błąd,
   liczba awarii z rzędu.

„Parę kliknięć” = użytkownik raz tworzy profil, a potem wszystko dzieje się samo;
wyniki sprawdza na `/deals` albo dostaje na Telegramie.

---

## 10. Powiadomienia (`app/notify.py`)

- `send_pending()`: pobiera `get_unnotified_deals()`, grupuje po profilu, wysyła jedną
  wiadomość na profil na cykl (nie spamować pojedynczymi), po sukcesie `mark_deal_notified`.
- **Telegram (domyślne):** użytkownik zakłada bota przez `@BotFather`, wpisuje do `.env`
  `TELEGRAM_BOT_TOKEN` i `TELEGRAM_CHAT_ID`. Wysyłka: POST
  `https://api.telegram.org/bot{token}/sendMessage`, `parse_mode="HTML"`.
  Format wiadomości:

  ```
  🏖 <b>Grecja wrzesień</b> — 2 nowe okazje
  ▪️ Hotel Blue Bay ⭐4.0 (8.6/10), AI, 12–19.09, z Warszawy
     3 444 PLN/os 🔻18% — historyczne minimum
     [link]
  ```

- **E-mail (opcjonalnie):** SMTP z `.env` (`SMTP_HOST/PORT/USER/PASSWORD/TO`).
  Implementuj tylko, jeśli zmienne są ustawione; brak konfiguracji ≠ błąd.
- Brak jakiejkolwiek konfiguracji powiadomień jest OK — okazje i tak widać w UI.

---

## 11. Konfiguracja (`.env.example`)

```
# harmonogram
CHECK_TIMES=07:30,13:30,20:30
# progi okazji
PRICE_DROP_THRESHOLD_PCT=10
# telegram (opcjonalnie)
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
# e-mail (opcjonalnie)
SMTP_HOST=
SMTP_PORT=587
SMTP_USER=
SMTP_PASSWORD=
SMTP_TO=
```

`app/config.py` wczytuje to przez `pydantic-settings` do obiektu `Settings`.

---

## 12. Testy (`tests/`)

- `test_db.py`: baza tymczasowa (`tmp_path`), test `upsert_offer` (nowa oferta,
  aktualizacja ceny, aktualizacja `lowest_price`), test filtrowania
  `get_offers_for_profile`, test deduplikacji deali.
- `test_deals.py`: przypadki dla trzech reguł, w tym progi brzegowe (dokładnie 10% spadku,
  budżet równy cenie) i ponowne powiadomienie po kolejnych 5% spadku.
- `test_scrapers.py`: dla każdego scrapera test `parse_offers()` na pliku ze
  `snapshots/` — sprawdza liczbę sparsowanych ofert, poprawność cen, dat i normalizacji
  wyżywienia. **Testy scraperów nie łączą się z internetem.**
- Uruchamianie: `python -m pytest`. Wszystkie testy muszą przechodzić po każdym etapie.

---

## 13. Etapy realizacji (wykonuj po kolei)

### ETAP 0 — szkielet projektu
Utwórz strukturę katalogów, `requirements.txt`, `.env.example`, `.gitignore`,
`config.py`, pusty `main.py` z FastAPI zwracającym `{"status": "ok"}` na `/health`.
**Kryteria:** `uvicorn app.main:app` startuje; `pytest` przechodzi (0 testów = OK).

### ETAP 1 — modele + baza
`models.py`, `schema.sql`, `db.py`, `test_db.py`.
**Kryteria:** wszystkie funkcje z sekcji 5 zaimplementowane; testy przechodzą.

### ETAP 2 — scraper wakacje.pl
`base.py` (+ `normalize_board`), `wakacje_pl.py` wg procedury 7.2, snapshot + testy.
Dodaj też CLI do ręcznego testu: `python -m app.scrapers.wakacje_pl --country Grecja
--date-from 2026-09-01 --date-to 2026-09-30` drukujący oferty w konsoli.
**Kryteria:** żywe wyszukiwanie zwraca ≥ 10 sensownych ofert dla popularnego kierunku;
test parsera na snapshocie przechodzi; ceny per os. i daty poprawne (zweryfikuj ręcznie
3 oferty, porównując z przeglądarką).

### ETAP 3 — silnik okazji
`deals.py`, `test_deals.py`.
**Kryteria:** testy trzech reguł przechodzą; podwójne uruchomienie `detect_deals`
nie tworzy duplikatów.

### ETAP 4 — harmonogram
`scheduler.py`, integracja z `main.py`, obsługa `scraper_health` i pomijania
niesprawnych scraperów.
**Kryteria:** `run_all_searches()` wywołana ręcznie robi pełny cykl
(scraping → zapis → detekcja) bez wyjątków; zaplanowane zadania widać w logu przy starcie.

### ETAP 5 — panel webowy
Wszystkie strony z sekcji 9.
**Kryteria:** pełny przepływ klikalny w przeglądarce: utworzenie profilu → „Sprawdź teraz”
→ wyniki w tabeli → okazje na `/deals` → historia ceny oferty.

### ETAP 6 — powiadomienia
`notify.py` + wpięcie w cykl schedulera.
**Kryteria:** przy skonfigurowanym tokenie wiadomość dochodzi na Telegram; bez
konfiguracji cykl działa bez błędów; powtórny cykl nie wysyła duplikatów.

### ETAP 7 — pozostałe scrapery
Kolejno: `itaka.py`, `tui.py`, `coraltravel.py`, `lastminuter.py` — każdy wg procedury
7.2, każdy ze snapshotem i testem, każdy rejestrowany w `SCRAPERS`.
**Kryteria (per serwis):** jak w etapie 2. Jeśli serwis skutecznie blokuje scraping
(CAPTCHA/Cloudflare nie do przejścia grzecznymi metodami) — **nie walcz**: zostaw moduł
rzucający `ScraperError("blocked")`, odnotuj to w README i jedź dalej. Agregacja przez
wakacje.pl i tak pokrywa oferty tego operatora.

### ETAP 8 — dopracowanie
Retry z backoffem (2 s / 4 s / 8 s) na błędy sieciowe w scraperach, logowanie do
`data/app.log` (moduł `logging`, poziom INFO), czyszczenie ofert nieodświeżonych
od > 14 dni (job raz dziennie), README z instrukcją: instalacja
(`pip install -r requirements.txt`, `playwright install chromium`), konfiguracja `.env`,
uruchomienie, założenie bota Telegram.
**Kryteria:** świeży klon repo da się uruchomić wyłącznie wg README.

---

## 14. Zasady pracy dla modelu implementującego

1. **Jeden etap = jeden commit** (lub kilka małych). Komunikat: `Etap N: <co zrobiono>`.
2. Po każdym etapie uruchom `python -m pytest` i uruchom aplikację. Nie kontynuuj
   z czerwonymi testami.
3. **Nie wymyślaj selektorów ani URL-i endpointów** — zawsze ustalaj je procedurą 7.2
   na żywej stronie i od razu zapisuj snapshot. Jeśli nie masz dostępu do internetu,
   zatrzymaj się i poproś użytkownika o wykonanie kroków 1–3 procedury i wklejenie
   przykładowej odpowiedzi.
4. Trzymaj się dokładnie nazw plików, funkcji i schematu bazy z tego dokumentu.
5. Nie dodawaj zależności spoza `requirements.txt` bez wyraźnej potrzeby — a jeśli
   dodajesz, dopisz ją do `requirements.txt` i uzasadnij w commit message.
6. Nie obchodź zabezpieczeń serwisów (CAPTCHA, limity). Zablokowany serwis oznaczasz
   w `scraper_health` i opisujesz w README.
7. Wszystkie komunikaty w UI i powiadomieniach po polsku.

---

## 15. Znane ryzyka

| Ryzyko | Mitygacja |
|---|---|
| Zmiana struktury strony psuje scraper | separacja pobierania od parsowania; selektory w jednym miejscu; testy na snapshotach wykrywają regresje parsera; `/status` pokazuje awarie |
| Blokady anty-botowe | niska częstotliwość, pauzy, realistyczny UA, Playwright jako fallback; serwis nie do przejścia → pomijamy (wakacje.pl agreguje operatorów) |
| Niespójne dane między serwisami (nazwy hoteli, wyżywienie) | normalizacja board (4.1); deduplikacja tylko wewnątrz źródła, nie między źródłami (MVP) |
| Ceny „od”, dopłaty, różne definicje ceny | zawsze zapisujemy cenę per osoba tak, jak prezentuje ją serwis + link do źródła; użytkownik weryfikuje przed zakupem |
| Rozrost bazy | wpisy historii tylko przy zmianie ceny; czyszczenie ofert > 14 dni |
