from app.scrapers.base import BaseScraper
from app.scrapers.wakacje_pl import WakacjePlScraper

# Rejestr wszystkich scraperów. Scheduler i UI iterują po tym słowniku —
# dodanie kolejnego serwisu (Etap 7) nie wymaga zmian nigdzie indziej.
SCRAPERS: dict[str, BaseScraper] = {
    "wakacje_pl": WakacjePlScraper(),
}

__all__ = ["BaseScraper", "SCRAPERS"]
