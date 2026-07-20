from app.scrapers.base import BaseScraper
from app.scrapers.coraltravel import CoralTravelScraper
from app.scrapers.itaka import ItakaScraper
from app.scrapers.lastminuter import LastminuterScraper
from app.scrapers.tui import TuiScraper
from app.scrapers.wakacje_pl import WakacjePlScraper

# Rejestr wszystkich scraperów. Scheduler i UI iterują po tym słowniku —
# dodanie kolejnego serwisu nie wymaga zmian nigdzie indziej.
SCRAPERS: dict[str, BaseScraper] = {
    "wakacje_pl": WakacjePlScraper(),
    "itaka": ItakaScraper(),
    "tui": TuiScraper(),
    "coraltravel": CoralTravelScraper(),
    "lastminuter": LastminuterScraper(),
}

__all__ = ["BaseScraper", "SCRAPERS"]
