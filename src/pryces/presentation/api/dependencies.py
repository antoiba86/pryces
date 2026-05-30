from __future__ import annotations

from fastapi import Depends

from ...application.importers import ImporterRegistry
from ...application.interfaces import (
    FxRateProvider,
    HistoricalFxRateProvider,
    LoggerFactory,
    PortfolioRepository,
    StockProvider,
    SymbolResolver,
)
from ...application.use_cases.create_portfolio import CreatePortfolio
from ...application.use_cases.delete_portfolio import DeletePortfolio
from ...application.use_cases.get_portfolio import GetPortfolio
from ...application.use_cases.import_transactions import ImportTransactions
from ...application.use_cases.list_portfolios import ListPortfolios
from ...infrastructure.factories import SettingsFactory
from ...infrastructure.fx import YahooFinanceFxProvider, YahooFinanceHistoricalFxProvider
from ...infrastructure.importers.degiro import DegiroCsvImporter
from ...infrastructure.importers.ibkr import IbkrFlexImporter
from ...infrastructure.importers.json_ledger import JsonLedgerImporter
from ...infrastructure.logging import PythonLoggerFactory
from ...infrastructure.providers import YahooFinanceProvider
from ...infrastructure.repositories import JsonPortfolioRepository
from ...infrastructure.resolvers import CachedSymbolResolver, JsonSymbolMap, YahooSymbolResolver

# --- Infrastructure providers (overridden in tests via app.dependency_overrides) ---


def get_logger_factory() -> LoggerFactory:
    return PythonLoggerFactory()


def get_portfolio_repository() -> PortfolioRepository:
    return JsonPortfolioRepository()


def get_stock_provider(
    logger_factory: LoggerFactory = Depends(get_logger_factory),
) -> StockProvider:
    return YahooFinanceProvider(
        settings=SettingsFactory.create_yahoo_finance_settings(),
        logger_factory=logger_factory,
    )


def get_fx_provider(
    stock_provider: StockProvider = Depends(get_stock_provider),
    logger_factory: LoggerFactory = Depends(get_logger_factory),
) -> FxRateProvider:
    return YahooFinanceFxProvider(stock_provider, logger_factory)


def get_historical_fx_provider(
    logger_factory: LoggerFactory = Depends(get_logger_factory),
) -> HistoricalFxRateProvider:
    return YahooFinanceHistoricalFxProvider(logger_factory)


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
        [DegiroCsvImporter(), JsonLedgerImporter(), IbkrFlexImporter()], logger_factory
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
) -> GetPortfolio:
    return GetPortfolio(repository, stock_provider, fx_provider, historical_fx_provider)


def get_import_transactions(
    registry: ImporterRegistry = Depends(get_importer_registry),
    resolver: SymbolResolver = Depends(get_symbol_resolver),
    repository: PortfolioRepository = Depends(get_portfolio_repository),
) -> ImportTransactions:
    return ImportTransactions(registry, resolver, repository)
