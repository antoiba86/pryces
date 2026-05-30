import argparse
import sys

from dotenv import load_dotenv

from ...application.importers import ImporterRegistry
from ...application.interfaces import LoggerFactory
from ...infrastructure.configs import CONFIGS_DIR, ConfigStore
from ...infrastructure.factories import SettingsFactory
from ...infrastructure.fx import YahooFinanceFxProvider, YahooFinanceHistoricalFxProvider
from ...infrastructure.importers.degiro import DegiroCsvImporter
from ...infrastructure.importers.ibkr import IbkrFlexImporter
from ...infrastructure.importers.json_ledger import JsonLedgerImporter
from ...infrastructure.logging import PythonLoggerFactory, setup_logging
from ...infrastructure.portfolio_formatters import TelegramPortfolioFormatter
from ...infrastructure.providers import YahooFinanceHistoricalPriceProvider, YahooFinanceProvider
from ...infrastructure.repositories import JsonPortfolioRepository
from ...infrastructure.resolvers import CachedSymbolResolver, JsonSymbolMap, YahooSymbolResolver
from ...infrastructure.senders import RetryMessageSender, RetrySettings, TelegramMessageSender
from .factories import CommandFactory
from .menu import InteractiveMenu


def _create_menu(logger_factory: LoggerFactory) -> InteractiveMenu:
    yahoo_finance_settings = SettingsFactory.create_yahoo_finance_settings()
    provider = YahooFinanceProvider(settings=yahoo_finance_settings, logger_factory=logger_factory)

    telegram_settings = SettingsFactory.create_telegram_settings()
    message_sender = RetryMessageSender(
        inner=TelegramMessageSender(settings=telegram_settings, logger_factory=logger_factory),
        settings=RetrySettings(max_retries=3, base_delay=1.0, backoff_factor=2.0),
        logger_factory=logger_factory,
    )

    portfolio_repository = JsonPortfolioRepository()
    fx_provider = YahooFinanceFxProvider(provider, logger_factory)
    historical_fx_provider = YahooFinanceHistoricalFxProvider(logger_factory)
    historical_price_provider = YahooFinanceHistoricalPriceProvider(logger_factory)
    symbol_resolver = CachedSymbolResolver(
        YahooSymbolResolver(logger_factory), JsonSymbolMap(), logger_factory
    )
    importer_registry = ImporterRegistry(
        [DegiroCsvImporter(), JsonLedgerImporter(), IbkrFlexImporter()], logger_factory
    )

    factory = CommandFactory(
        stock_provider=provider,
        message_sender=message_sender,
        logger_factory=logger_factory,
        config_store=ConfigStore(CONFIGS_DIR),
        portfolio_repository=portfolio_repository,
        fx_provider=fx_provider,
        historical_fx_provider=historical_fx_provider,
        historical_price_provider=historical_price_provider,
        importer_registry=importer_registry,
        symbol_resolver=symbol_resolver,
        portfolio_formatter=TelegramPortfolioFormatter(),
    )

    registry = factory.create_command_registry()
    return InteractiveMenu(registry)


def main() -> int:
    parser = argparse.ArgumentParser(description="Pryces - Stock Price Information System")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    load_dotenv()

    setup_logging(SettingsFactory.create_cli_logging_settings(debug=args.debug))
    logger_factory = PythonLoggerFactory()
    logger = logger_factory.get_logger(__name__)

    try:
        menu = _create_menu(logger_factory)
        menu.run()
        return 0

    except KeyboardInterrupt:
        logger.info("CLI stopped by user.")
        return 0

    except Exception as e:
        message = f"CLI error: {e}"
        print(message)
        logger.error(message)
        return 1


if __name__ == "__main__":
    sys.exit(main())
