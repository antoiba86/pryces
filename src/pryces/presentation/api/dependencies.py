from __future__ import annotations

from decimal import Decimal

from fastapi import Depends

from ...application.importers import ImporterRegistry
from ...application.interfaces import (
    FxRateProvider,
    HistoricalFxRateProvider,
    HistoricalPriceProvider,
    LoggerFactory,
    PortfolioRepository,
    StockProvider,
    SymbolResolver,
)
from ...application.use_cases.create_portfolio import CreatePortfolio
from ...application.use_cases.delete_portfolio import DeletePortfolio
from ...application.use_cases.get_overview import GetOverview
from ...application.use_cases.get_portfolio import GetPortfolio
from ...application.use_cases.get_transactions import GetTransactions
from ...application.use_cases.import_transactions import ImportTransactions
from ...application.use_cases.list_portfolios import ListPortfolios
from ...application.use_cases.manage_transactions import (
    AddTransaction,
    DeleteTransaction,
    UpdateTransaction,
)
from ...domain.stocks import Currency, Stock
from ...infrastructure.caching import CachedFxRateProvider, CachedStockProvider, TtlCache
from ...infrastructure.factories import SettingsFactory
from ...infrastructure.fx import YahooFinanceFxProvider, YahooFinanceHistoricalFxProvider
from ...infrastructure.importers.degiro import DegiroCsvImporter
from ...infrastructure.importers.ibkr import IbkrActivityImporter
from ...infrastructure.importers.json_ledger import JsonLedgerImporter
from ...infrastructure.importers.horos import HorosFundsImporter
from ...infrastructure.importers.renta4 import Renta4FundsImporter
from ...infrastructure.logging import PythonLoggerFactory
from ...infrastructure.providers import YahooFinanceHistoricalPriceProvider, YahooFinanceProvider
from ...infrastructure.repositories import JsonPortfolioRepository
from ...infrastructure.resolvers import CachedSymbolResolver, JsonSymbolMap, YahooSymbolResolver

# --- Infrastructure providers (overridden in tests via app.dependency_overrides) ---


def get_logger_factory() -> LoggerFactory:
    return PythonLoggerFactory()


def get_portfolio_repository() -> PortfolioRepository:
    return JsonPortfolioRepository()


# Process-wide caches. `Depends` rebuilds the provider every request, so the cache
# stores must live outside them to survive across requests; built lazily so the TTL
# env vars are read on first use, not at import time. Quotes use a short TTL; FX rates
# a much longer one (they barely move within an hour).
_stock_cache: TtlCache[str, Stock] | None = None
_fx_cache: TtlCache[tuple[Currency, Currency], Decimal] | None = None


def _get_stock_cache() -> TtlCache[str, Stock]:
    global _stock_cache
    if _stock_cache is None:
        _stock_cache = TtlCache(SettingsFactory.create_cache_settings().ttl_seconds)
    return _stock_cache


def _get_fx_cache() -> TtlCache[tuple[Currency, Currency], Decimal]:
    global _fx_cache
    if _fx_cache is None:
        _fx_cache = TtlCache(SettingsFactory.create_fx_cache_settings().ttl_seconds)
    return _fx_cache


def _build_yahoo_stock_provider(logger_factory: LoggerFactory) -> YahooFinanceProvider:
    return YahooFinanceProvider(
        settings=SettingsFactory.create_yahoo_finance_settings(),
        logger_factory=logger_factory,
    )


def get_stock_provider(
    logger_factory: LoggerFactory = Depends(get_logger_factory),
) -> StockProvider:
    return CachedStockProvider(
        _build_yahoo_stock_provider(logger_factory),
        _get_stock_cache(),
        logger_factory,
        closed_ttl_seconds=SettingsFactory.create_closed_market_cache_settings().ttl_seconds,
    )


def get_fx_provider(
    logger_factory: LoggerFactory = Depends(get_logger_factory),
) -> FxRateProvider:
    # The FX provider fetches `EURUSD=X`-style pairs through a StockProvider; give it
    # the *uncached* one so FX rates live only in the FX cache (at the FX TTL), not
    # also in the shorter-lived quote cache.
    inner = YahooFinanceFxProvider(_build_yahoo_stock_provider(logger_factory), logger_factory)
    return CachedFxRateProvider(inner, _get_fx_cache(), logger_factory)


def get_historical_fx_provider(
    logger_factory: LoggerFactory = Depends(get_logger_factory),
) -> HistoricalFxRateProvider:
    return YahooFinanceHistoricalFxProvider(logger_factory)


def get_historical_price_provider(
    logger_factory: LoggerFactory = Depends(get_logger_factory),
) -> HistoricalPriceProvider:
    return YahooFinanceHistoricalPriceProvider(logger_factory)


def get_symbol_resolver(
    logger_factory: LoggerFactory = Depends(get_logger_factory),
) -> SymbolResolver:
    return CachedSymbolResolver(
        YahooSymbolResolver(logger_factory), JsonSymbolMap(), logger_factory
    )


def get_importer_registry(
    logger_factory: LoggerFactory = Depends(get_logger_factory),
) -> ImporterRegistry:
    return ImporterRegistry(
        [
            DegiroCsvImporter(),
            JsonLedgerImporter(),
            IbkrActivityImporter(),
            Renta4FundsImporter(),
            HorosFundsImporter(),
        ],
        logger_factory,
    )


def current_user_id() -> int:
    # Auth seam: v1 is single-user. Later this reads a session/JWT and returns the
    # authenticated user's id — every route already threads user_id through.
    return 1


# --- Application use cases ---


def get_list_portfolios(
    repository: PortfolioRepository = Depends(get_portfolio_repository),
) -> ListPortfolios:
    return ListPortfolios(repository)


def get_create_portfolio(
    repository: PortfolioRepository = Depends(get_portfolio_repository),
) -> CreatePortfolio:
    return CreatePortfolio(repository)


def get_delete_portfolio(
    repository: PortfolioRepository = Depends(get_portfolio_repository),
) -> DeletePortfolio:
    return DeletePortfolio(repository)


def get_get_portfolio(
    repository: PortfolioRepository = Depends(get_portfolio_repository),
    stock_provider: StockProvider = Depends(get_stock_provider),
    fx_provider: FxRateProvider = Depends(get_fx_provider),
    historical_fx_provider: HistoricalFxRateProvider = Depends(get_historical_fx_provider),
    historical_price_provider: HistoricalPriceProvider = Depends(get_historical_price_provider),
) -> GetPortfolio:
    return GetPortfolio(
        repository,
        stock_provider,
        fx_provider,
        historical_fx_provider,
        historical_price_provider,
    )


def get_overview(
    repository: PortfolioRepository = Depends(get_portfolio_repository),
    portfolio_builder: GetPortfolio = Depends(get_get_portfolio),
) -> GetOverview:
    return GetOverview(repository, portfolio_builder)


def get_get_transactions(
    repository: PortfolioRepository = Depends(get_portfolio_repository),
) -> GetTransactions:
    return GetTransactions(repository)


def get_import_transactions(
    registry: ImporterRegistry = Depends(get_importer_registry),
    resolver: SymbolResolver = Depends(get_symbol_resolver),
    repository: PortfolioRepository = Depends(get_portfolio_repository),
) -> ImportTransactions:
    return ImportTransactions(registry, resolver, repository)


def get_add_transaction(
    repository: PortfolioRepository = Depends(get_portfolio_repository),
    resolver: SymbolResolver = Depends(get_symbol_resolver),
) -> AddTransaction:
    return AddTransaction(repository, resolver)


def get_update_transaction(
    repository: PortfolioRepository = Depends(get_portfolio_repository),
) -> UpdateTransaction:
    return UpdateTransaction(repository)


def get_delete_transaction(
    repository: PortfolioRepository = Depends(get_portfolio_repository),
) -> DeleteTransaction:
    return DeleteTransaction(repository)
