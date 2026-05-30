from unittest.mock import Mock

import pytest

from pryces.application.exceptions import PortfolioNotFound
from pryces.application.interfaces import MessageSender
from pryces.application.use_cases.get_portfolio import GetPortfolio
from pryces.domain.portfolio.formatters import PortfolioFormatter
from pryces.domain.portfolio.portfolio import Portfolio
from pryces.presentation.scripts.report_portfolio import ReportPortfolioScript


@pytest.fixture()
def logger_factory():
    factory = Mock()
    factory.get_logger.return_value = Mock()
    return factory


def _script(logger_factory, get_portfolio, formatter, sender, name="main"):
    return ReportPortfolioScript(
        get_portfolio=get_portfolio,
        formatter=formatter,
        message_sender=sender,
        portfolio_name=name,
        logger_factory=logger_factory,
    )


class TestReportPortfolioScript:

    def test_sends_each_formatted_message(self, logger_factory):
        get_portfolio = Mock(spec=GetPortfolio)
        get_portfolio.handle.return_value = Portfolio(base_currency="EUR")
        formatter = Mock(spec=PortfolioFormatter)
        formatter.format.return_value = ["msg-1", "msg-2"]
        sender = Mock(spec=MessageSender)

        _script(logger_factory, get_portfolio, formatter, sender).run()

        assert get_portfolio.handle.call_args[0][0].name == "main"
        assert sender.send_message.call_count == 2
        sender.send_message.assert_any_call("msg-1")
        sender.send_message.assert_any_call("msg-2")

    def test_does_not_send_when_portfolio_missing(self, logger_factory):
        get_portfolio = Mock(spec=GetPortfolio)
        get_portfolio.handle.side_effect = PortfolioNotFound("ghost")
        formatter = Mock(spec=PortfolioFormatter)
        sender = Mock(spec=MessageSender)

        _script(logger_factory, get_portfolio, formatter, sender, name="ghost").run()

        formatter.format.assert_not_called()
        sender.send_message.assert_not_called()
