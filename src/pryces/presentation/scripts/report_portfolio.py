import argparse
import sys

from dotenv import load_dotenv

from ...application.exceptions import PortfolioNotFound
from ...application.interfaces import LoggerFactory, MessageSender
from ...application.use_cases.get_portfolio import GetPortfolio, GetPortfolioRequest
from ...domain.portfolio.formatters import PortfolioFormatter
from ...infrastructure.factories import SettingsFactory
from ...infrastructure.fx import YahooFinanceFxProvider, YahooFinanceHistoricalFxProvider
from ...infrastructure.logging import PythonLoggerFactory, setup_logging
from ...infrastructure.portfolio_formatters import TelegramPortfolioFormatter
from ...infrastructure.providers import YahooFinanceProvider
from ...infrastructure.repositories import JsonPortfolioRepository
from ...infrastructure.senders import TelegramMessageSender


class ReportPortfolioScript:
    def __init__(
        self,
        get_portfolio: GetPortfolio,
        formatter: PortfolioFormatter,
        message_sender: MessageSender,
        portfolio_name: str,
        logger_factory: LoggerFactory,
    ) -> None:
        self._get_portfolio = get_portfolio
        self._formatter = formatter
        self._message_sender = message_sender
        self._portfolio_name = portfolio_name
        self._logger = logger_factory.get_logger(__name__)

    def run(self) -> None:
        try:
            portfolio = self._get_portfolio.handle(GetPortfolioRequest(name=self._portfolio_name))
        except PortfolioNotFound:
            self._logger.error(f"Portfolio not found: {self._portfolio_name}")
            return

        messages = self._formatter.format(portfolio)
        self._logger.info(
            f"Sending {len(messages)} message(s) for portfolio {self._portfolio_name!r}"
        )
        for message in messages:
            self._message_sender.send_message(message)


def _create_script(portfolio_name: str, logger_factory: LoggerFactory) -> ReportPortfolioScript:
    yahoo_settings = SettingsFactory.create_yahoo_finance_settings()
    provider = YahooFinanceProvider(settings=yahoo_settings, logger_factory=logger_factory)
    fx_provider = YahooFinanceFxProvider(provider, logger_factory)
    historical_fx_provider = YahooFinanceHistoricalFxProvider(logger_factory)
    repository = JsonPortfolioRepository()

    get_portfolio = GetPortfolio(repository, provider, fx_provider, historical_fx_provider)

    telegram_settings = SettingsFactory.create_telegram_settings()
    message_sender = TelegramMessageSender(
        settings=telegram_settings, logger_factory=logger_factory
    )

    return ReportPortfolioScript(
        get_portfolio=get_portfolio,
        formatter=TelegramPortfolioFormatter(),
        message_sender=message_sender,
        portfolio_name=portfolio_name,
        logger_factory=logger_factory,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Report a portfolio (holdings, totals, XIRR) via Telegram",
    )
    parser.add_argument("--portfolio", required=True, help="Name of the portfolio to report")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging to stderr")
    args = parser.parse_args()

    load_dotenv()
    setup_logging(
        SettingsFactory.create_report_logging_settings(verbose=args.verbose, debug=args.debug)
    )
    logger_factory = PythonLoggerFactory()

    try:
        script = _create_script(args.portfolio, logger_factory)
        script.run()
    except KeyboardInterrupt:
        logger_factory.get_logger(__name__).info("Report stopped by user.")
    except Exception as e:
        message = f"Report error: {e}"
        print(message)
        logger_factory.get_logger(__name__).error(message)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
