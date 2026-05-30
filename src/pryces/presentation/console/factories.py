from ...application.importers import ImporterRegistry
from ...application.interfaces import (
    FxRateProvider,
    HistoricalFxRateProvider,
    HistoricalPriceProvider,
    LoggerFactory,
    MessageSender,
    PortfolioRepository,
    StockProvider,
    SymbolResolver,
)
from ...application.use_cases.create_portfolio import CreatePortfolio
from ...application.use_cases.delete_portfolio import DeletePortfolio
from ...application.use_cases.get_portfolio import GetPortfolio
from ...application.use_cases.get_stocks_prices import GetStocksPrices
from ...application.use_cases.import_transactions import ImportTransactions
from ...application.use_cases.list_portfolios import ListPortfolios
from ...application.use_cases.send_messages import SendMessages
from ...domain.portfolio.formatters import PortfolioFormatter
from ...infrastructure.configs import ConfigStore
from .commands.check_readiness import CheckReadinessCommand, EnvVarsChecker, TelegramChecker
from .commands.create_config import CreateConfigCommand
from .commands.create_portfolio import CreatePortfolioCommand
from .commands.delete_config import DeleteConfigCommand
from .commands.delete_portfolio import DeletePortfolioCommand
from .commands.edit_config import EditConfigCommand
from .commands.get_stocks_prices import GetStocksPricesCommand
from .commands.import_transactions import ImportTransactionsCommand
from .commands.list_configs import ListConfigsCommand
from .commands.list_monitors import ListMonitorsCommand
from .commands.list_portfolios import ListPortfoliosCommand
from .commands.monitor_stocks import MonitorStocksCommand
from .commands.registry import CommandRegistry
from .commands.show_portfolio import ShowPortfolioCommand
from .commands.stop_monitor import StopMonitorCommand


class CommandFactory:
    def __init__(
        self,
        stock_provider: StockProvider,
        message_sender: MessageSender,
        logger_factory: LoggerFactory,
        config_store: ConfigStore,
        portfolio_repository: PortfolioRepository,
        fx_provider: FxRateProvider,
        historical_fx_provider: HistoricalFxRateProvider,
        historical_price_provider: HistoricalPriceProvider,
        importer_registry: ImporterRegistry,
        symbol_resolver: SymbolResolver,
        portfolio_formatter: PortfolioFormatter,
    ) -> None:
        self._stock_provider = stock_provider
        self._message_sender = message_sender
        self._logger_factory = logger_factory
        self._config_store = config_store
        self._portfolio_repository = portfolio_repository
        self._fx_provider = fx_provider
        self._historical_fx_provider = historical_fx_provider
        self._historical_price_provider = historical_price_provider
        self._importer_registry = importer_registry
        self._symbol_resolver = symbol_resolver
        self._portfolio_formatter = portfolio_formatter

    def _create_list_portfolios_command(self) -> ListPortfoliosCommand:
        return ListPortfoliosCommand(ListPortfolios(self._portfolio_repository))

    def _create_create_portfolio_command(self) -> CreatePortfolioCommand:
        return CreatePortfolioCommand(CreatePortfolio(self._portfolio_repository))

    def _create_delete_portfolio_command(self) -> DeletePortfolioCommand:
        return DeletePortfolioCommand(
            ListPortfolios(self._portfolio_repository),
            DeletePortfolio(self._portfolio_repository),
        )

    def _create_show_portfolio_command(self) -> ShowPortfolioCommand:
        return ShowPortfolioCommand(
            ListPortfolios(self._portfolio_repository),
            GetPortfolio(
                self._portfolio_repository,
                self._stock_provider,
                self._fx_provider,
                self._historical_fx_provider,
                self._historical_price_provider,
            ),
            self._portfolio_formatter,
            self._message_sender,
        )

    def _create_import_transactions_command(self) -> ImportTransactionsCommand:
        return ImportTransactionsCommand(
            ListPortfolios(self._portfolio_repository),
            ImportTransactions(
                self._importer_registry, self._symbol_resolver, self._portfolio_repository
            ),
            [importer.broker_id for importer in self._importer_registry.importers],
        )

    def _create_monitor_stocks_command(self) -> MonitorStocksCommand:
        return MonitorStocksCommand(self._config_store)

    def _create_get_stocks_prices_command(self) -> GetStocksPricesCommand:
        use_case = GetStocksPrices(provider=self._stock_provider)
        return GetStocksPricesCommand(
            get_stocks_prices_use_case=use_case, logger_factory=self._logger_factory
        )

    def _create_check_readiness_command(self) -> CheckReadinessCommand:
        send_messages = SendMessages(sender=self._message_sender)
        checkers = [
            EnvVarsChecker(),
            TelegramChecker(
                send_messages=send_messages,
                logger=self._logger_factory.get_logger(
                    "pryces.presentation.console.commands.check_readiness"
                ),
            ),
        ]
        return CheckReadinessCommand(checkers=checkers, logger_factory=self._logger_factory)

    def _create_list_monitors_command(self) -> ListMonitorsCommand:
        return ListMonitorsCommand()

    def _create_stop_monitor_command(self) -> StopMonitorCommand:
        return StopMonitorCommand()

    def _create_list_configs_command(self) -> ListConfigsCommand:
        return ListConfigsCommand(self._config_store)

    def _create_create_config_command(self) -> CreateConfigCommand:
        return CreateConfigCommand(self._config_store)

    def _create_edit_config_command(self) -> EditConfigCommand:
        return EditConfigCommand(self._config_store)

    def _create_delete_config_command(self) -> DeleteConfigCommand:
        return DeleteConfigCommand(self._config_store)

    def create_command_registry(self) -> CommandRegistry:
        registry = CommandRegistry()
        registry.register(self._create_list_configs_command())
        registry.register(self._create_create_config_command())
        registry.register(self._create_edit_config_command())
        registry.register(self._create_delete_config_command())
        registry.register(self._create_monitor_stocks_command())
        registry.register(self._create_list_monitors_command())
        registry.register(self._create_stop_monitor_command())
        registry.register(self._create_get_stocks_prices_command())
        registry.register(self._create_list_portfolios_command())
        registry.register(self._create_create_portfolio_command())
        registry.register(self._create_show_portfolio_command())
        registry.register(self._create_import_transactions_command())
        registry.register(self._create_delete_portfolio_command())
        registry.register(self._create_check_readiness_command())
        return registry
