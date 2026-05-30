from unittest.mock import Mock

from pryces.application.importers import ImporterRegistry
from pryces.application.interfaces import (
    FxRateProvider,
    HistoricalFxRateProvider,
    HistoricalPriceProvider,
    MessageSender,
    PortfolioRepository,
    StockProvider,
    SymbolResolver,
)
from pryces.domain.portfolio.formatters import PortfolioFormatter
from pryces.infrastructure.configs import ConfigStore
from pryces.presentation.console.factories import CommandFactory
from pryces.presentation.console.commands.get_stocks_prices import GetStocksPricesCommand
from pryces.presentation.console.commands.import_transactions import ImportTransactionsCommand
from pryces.presentation.console.commands.monitor_stocks import MonitorStocksCommand
from pryces.presentation.console.commands.registry import CommandRegistry
from pryces.presentation.console.commands.check_readiness import CheckReadinessCommand


def _factory(provider=None):
    return CommandFactory(
        stock_provider=provider or Mock(spec=StockProvider),
        message_sender=Mock(spec=MessageSender),
        logger_factory=Mock(),
        config_store=Mock(spec=ConfigStore),
        portfolio_repository=Mock(spec=PortfolioRepository),
        fx_provider=Mock(spec=FxRateProvider),
        historical_fx_provider=Mock(spec=HistoricalFxRateProvider),
        historical_price_provider=Mock(spec=HistoricalPriceProvider),
        importer_registry=ImporterRegistry([], Mock()),
        symbol_resolver=Mock(spec=SymbolResolver),
        portfolio_formatter=Mock(spec=PortfolioFormatter),
    )


class TestCommandFactory:

    def test_init_accepts_custom_provider_and_message_sender(self):
        custom_provider = Mock(spec=StockProvider)
        factory = _factory(provider=custom_provider)

        assert factory._stock_provider is custom_provider

    def test_create_command_registry_returns_registry_instance(self):
        assert isinstance(_factory().create_command_registry(), CommandRegistry)

    def test__create_get_stocks_prices_command_returns_command_instance(self):
        assert isinstance(_factory()._create_get_stocks_prices_command(), GetStocksPricesCommand)

    def test_registry_contains_get_stocks_prices_command(self):
        registry = _factory().create_command_registry()

        assert isinstance(registry.get_command("get_stocks_prices"), GetStocksPricesCommand)

    def test_registry_contains_check_readiness_command(self):
        registry = _factory().create_command_registry()

        assert isinstance(registry.get_command("check_readiness"), CheckReadinessCommand)

    def test_registry_contains_monitor_stocks_command(self):
        registry = _factory().create_command_registry()

        assert isinstance(registry.get_command("monitor_stocks"), MonitorStocksCommand)

    def test_registry_contains_portfolio_commands(self):
        registry = _factory().create_command_registry()

        for command_id in (
            "list_portfolios",
            "create_portfolio",
            "show_portfolio",
            "import_transactions",
            "delete_portfolio",
        ):
            assert registry.get_command(command_id) is not None

    def test_create_import_transactions_command_exposes_broker_ids(self):
        command = _factory()._create_import_transactions_command()

        assert isinstance(command, ImportTransactionsCommand)

    def test_list_configs_is_first_command_in_registry(self):
        registry = _factory().create_command_registry()
        all_commands = registry.get_all_commands()

        assert all_commands[0].get_metadata().id == "list_configs"
