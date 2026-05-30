from abc import ABC, abstractmethod

from pryces.domain.portfolio.portfolio import ManualAsset, PortfolioSummary
from pryces.domain.portfolio.transactions import ImportResult, Instrument, Transaction
from pryces.domain.stock_statistics import StockStatistics
from decimal import Decimal

from pryces.domain.stocks import Currency, Stock


class StockProvider(ABC):
    @abstractmethod
    def get_stocks(self, symbols: list[str]) -> list[Stock]:
        pass


class StockStatisticsProvider(ABC):
    @abstractmethod
    def get_stock_statistics(self, symbols: list[str]) -> list[StockStatistics]:
        pass


class FxRateProvider(ABC):
    @abstractmethod
    def get_rates(self, base: Currency, quotes: list[Currency]) -> dict[Currency, Decimal]:
        # Returns rate-per-quote-unit in the base currency (so 1 USD = rate[USD] EUR
        # when base is EUR). Quotes equal to base map to Decimal("1"). Quotes for
        # which no rate is available are omitted.
        pass


class TransactionImporter(ABC):
    @property
    @abstractmethod
    def broker_id(self) -> str:
        pass

    @abstractmethod
    def can_parse(self, content: str) -> bool:
        # Fast shape/header sniff used for auto-detection. No I/O, no exceptions.
        pass

    @abstractmethod
    def parse(self, content: str) -> ImportResult:
        # Returns parsed transactions plus non-fatal warnings. Raises
        # UnrecognizedImportFormat only when the content is structurally
        # unrecognized (e.g. parse() called on content can_parse() rejected).
        pass


class SymbolResolver(ABC):
    @abstractmethod
    def resolve(self, instrument: Instrument) -> str | None:
        # Maps a broker-provided Instrument to a Yahoo ticker. Returns None when
        # no ticker can be determined (the caller keeps the original symbol).
        pass


class StockRepository(ABC):
    @abstractmethod
    def save_batch(self, stocks: list[Stock]) -> None:
        pass

    @abstractmethod
    def get(self, symbol: str) -> Stock | None:
        pass


class MessageSender(ABC):
    @abstractmethod
    def send_message(self, message: str) -> bool:
        # Returns True when accepted for delivery — not necessarily delivered yet.
        pass


class Logger(ABC):
    @abstractmethod
    def debug(self, message: str) -> None:
        pass

    @abstractmethod
    def info(self, message: str) -> None:
        pass

    @abstractmethod
    def warning(self, message: str) -> None:
        pass

    @abstractmethod
    def error(self, message: str) -> None:
        pass


class LoggerFactory(ABC):
    @abstractmethod
    def get_logger(self, name: str) -> Logger:
        pass


class PortfolioRepository(ABC):
    @abstractmethod
    def list_portfolios(self, user_id: int = 1) -> list[PortfolioSummary]:
        pass

    @abstractmethod
    def find_summary_by_name(self, name: str, user_id: int = 1) -> PortfolioSummary | None:
        pass

    @abstractmethod
    def create(
        self,
        base_currency: str,
        name: str | None = None,
        user_id: int = 1,
    ) -> PortfolioSummary:
        # `name` is optional; when omitted the repository assigns a default like
        # `portfolio_<YYYY-MM-DD_HH-MM-SS>` (and auto-bumps `_2`, `_3`, ... on
        # collision). Raises PortfolioAlreadyExists if the resolved name is
        # already taken or a same-named file already exists on disk.
        pass

    @abstractmethod
    def rename(self, old_name: str, new_name: str, user_id: int = 1) -> None:
        # Updates the name → filename index entry only; the portfolio file
        # itself is untouched, so external references survive renames.
        pass

    @abstractmethod
    def delete(self, name: str, user_id: int = 1) -> None:
        pass

    @abstractmethod
    def add_transactions(
        self,
        portfolio_name: str,
        transactions: list[Transaction],
        user_id: int = 1,
    ) -> int:
        # Returns the count of NEWLY-appended rows. Duplicates (matched on
        # broker + raw_id within the portfolio) are silently skipped.
        pass

    @abstractmethod
    def get_transactions(self, portfolio_name: str, user_id: int = 1) -> list[Transaction]:
        pass

    @abstractmethod
    def set_manual_assets(
        self,
        portfolio_name: str,
        manual_assets: list[ManualAsset],
        user_id: int = 1,
    ) -> None:
        pass

    @abstractmethod
    def get_manual_assets(self, portfolio_name: str, user_id: int = 1) -> list[ManualAsset]:
        pass
