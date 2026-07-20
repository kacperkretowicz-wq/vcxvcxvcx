# Tracker Okazji Wakacyjnych

Aplikacja webowa, która pozwala zdefiniować profil wyszukiwania wakacji
(kierunek, terminy, budżet, wyżywienie...), cyklicznie sprawdza oferty
w serwisach turystycznych (wakacje.pl, itaka, tui, coral travel,
lastminuter) i wykrywa okazje: cenę poniżej budżetu, nagły spadek ceny
oraz historyczne minimum. Powiadomienia trafiają na Telegram (i/lub
e-mail), a wszystkie wyniki są też widoczne w prostym panelu webowym.

Pełny opis architektury i decyzji projektowych: zobacz [`PLAN.md`](PLAN.md).

## ⚠️ Ważne: status scraperów

Ten projekt powstał w środowisku **bez dostępu do ogólnego internetu**
(tylko pypi/npm/github były dostępne), więc nie dało się podejrzeć
prawdziwej struktury stron wakacje.pl / itaka.pl / tui.pl / coraltravel.pl
/ lastminuter.pl w przeglądarce (procedura z `PLAN.md`, sekcja 7.2).

Efekt: **cała aplikacja jest w pełni zaimplementowana i przetestowana**
(93 testy jednostkowe, pełny przepływ UI zweryfikowany ręcznie), ale
**selektory CSS i adresy URL wyszukiwania w `app/scrapers/*.py` są
przybliżeniem** i prawie na pewno będą wymagały poprawek, zanim zaczną
zwracać prawdziwe oferty. Każdy plik scrapera ma na górze komentarz
z dokładną instrukcją, jak go dokończyć (krótko: otwórz stronę w
przeglądarce z DevTools → Network, wykonaj wyszukiwanie, zobacz jaki
URL/JSON faktycznie zwraca serwis, zaktualizuj `SELECTORS` /
`build_search_url` w danym pliku).

Reszta systemu (baza danych, wykrywanie okazji, harmonogram,
powiadomienia, panel webowy) nie wymaga żadnych zmian i działa od razu.

## Wymagania

- Python 3.11+
- Konto Telegram (opcjonalnie, do powiadomień)

## Instalacja

```bash
git clone <url-repozytorium>
cd vcxvcxvcx

python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -r requirements.txt
playwright install chromium
```

## Konfiguracja

```bash
cp .env.example .env
```

Edytuj `.env` wedle potrzeb:

| Zmienna | Znaczenie | Domyślnie |
|---|---|---|
| `CHECK_TIMES` | godziny cyklicznego sprawdzania (lokalne, HH:MM) | `07:30,13:30,20:30` |
| `PRICE_DROP_THRESHOLD_PCT` | próg wykrycia spadku ceny (%) | `10` |
| `PRICE_DROP_RENOTIFY_PCT` | próg ponownego powiadomienia przy dalszym spadku (%) | `5` |
| `DATABASE_PATH` | ścieżka do pliku SQLite | `data/app.db` |
| `LOG_PATH` | ścieżka do pliku logu | `data/app.log` |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | powiadomienia Telegram (opcjonalnie) | puste = wyłączone |
| `SMTP_*` | powiadomienia e-mail (opcjonalnie) | puste = wyłączone |

### Powiadomienia Telegram (opcjonalnie)

1. W Telegramie napisz do `@BotFather`, wyślij `/newbot` i postępuj wg
   instrukcji — dostaniesz token bota (`TELEGRAM_BOT_TOKEN`).
2. Napisz cokolwiek do swojego nowego bota (żeby "odblokować" czat).
3. Otwórz w przeglądarce
   `https://api.telegram.org/bot<TWÓJ_TOKEN>/getUpdates` i znajdź w
   odpowiedzi JSON pole `chat.id` — to jest `TELEGRAM_CHAT_ID`.
4. Wpisz oba w `.env`.

Bez tej konfiguracji aplikacja działa normalnie — okazje są widoczne
tylko w panelu webowym (`/deals`).

## Uruchomienie

```bash
uvicorn app.main:app --reload
```

Otwórz [http://localhost:8000](http://localhost:8000) w przeglądarce.

Przy pierwszym starcie tworzy się plik bazy danych (`data/app.db`) oraz
harmonogram cyklicznego sprawdzania ofert (godziny z `CHECK_TIMES`).
Logi trafiają jednocześnie na konsolę i do `data/app.log`.

## Użycie

1. Kliknij **„+ Nowy profil"**, wypełnij kierunek, terminy, budżet itd.
2. Na liście profili kliknij **„Sprawdź teraz"**, żeby od razu odpytać
   wszystkie serwisy (poza tym dzieje się to automatycznie wg `CHECK_TIMES`).
3. **„Wyniki"** pokazuje wszystkie pasujące oferty z trendem ceny i
   linkiem do historii.
4. **„Okazje"** (`/deals`) pokazuje wykryte okazje ze wszystkich profili.
5. **„Status"** (`/status`) pokazuje, które scrapery działają, a które
   mają błędy (patrz sekcja wyżej — bez weryfikacji selektorów na
   żywej stronie tu prawdopodobnie zobaczysz błędy).

## Testy

```bash
python -m pytest
```

93 testy: baza danych, silnik okazji, scrapery (na syntetycznych
zrzutach HTML), harmonogram, powiadomienia, trasy panelu webowego.
Żaden test nie łączy się z internetem.

## Ręczny test pojedynczego scrapera

```bash
python -m app.scrapers.wakacje_pl --country Grecja --date-from 2026-09-01 --date-to 2026-09-30
```

Wypisuje sparsowane oferty w konsoli (albo błąd, jeśli selektory nie
pasują do aktualnej struktury strony — patrz sekcja o statusie
scraperów wyżej).

## Struktura projektu

```
app/
  main.py            FastAPI: trasy panelu webowego + start harmonogramu
  config.py          Konfiguracja z .env (pydantic-settings)
  models.py          Modele danych: SearchCriteria, Offer, Deal
  db.py              Warstwa danych SQLite
  schema.sql          Schemat bazy
  deals.py           Wykrywanie okazji (below_budget / price_drop / historical_low)
  scheduler.py       Cykliczne sprawdzanie ofert (APScheduler)
  notify.py          Powiadomienia Telegram / e-mail
  logging_config.py  Logowanie do konsoli + pliku
  scrapers/          Po jednym module na serwis + wspólna baza w base.py
  templates/         Szablony Jinja2 panelu webowego
  static/            style.css
snapshots/           Przykładowe (syntetyczne) zrzuty HTML używane w testach
tests/               Testy pytest
```

## Etykieta scrapingu

Domyślny harmonogram odpytuje każdy serwis 3× dziennie, z pauzą
kilku sekund między żądaniami do tego samego serwisu i realistycznym
nagłówkiem User-Agent. Nie zwiększaj częstotliwości bez potrzeby i nie
próbuj obchodzić zabezpieczeń (CAPTCHA) — jeśli serwis blokuje dostęp,
zostaw go jako niesprawny (widoczne na `/status`) i korzystaj z innych
źródeł.
