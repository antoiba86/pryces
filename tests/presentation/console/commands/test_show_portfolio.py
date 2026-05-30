from unittest.mock import Mock

from pryces.application.exceptions import PortfolioNotFound
from pryces.application.interfaces import MessageSender
from pryces.application.use_cases.get_portfolio import GetPortfolio
from pryces.application.use_cases.list_portfolios import ListPortfolios
from pryces.domain.portfolio.formatters import PortfolioFormatter
from pryces.domain.portfolio.portfolio import Portfolio, PortfolioSummary
from pryces.presentation.console.commands.show_portfolio import ShowPortfolioCommand

_SUMMARIES = [PortfolioSummary(name="main", base_currency="EUR", transaction_count=2)]


def _command(summaries=_SUMMARIES, messages=("line1", "line2")):
    list_use_case = Mock(spec=ListPortfolios)
    list_use_case.handle.return_value = summaries
    get_use_case = Mock(spec=GetPortfolio)
    get_use_case.handle.return_value = Portfolio(base_currency="EUR")
    formatter = Mock(spec=PortfolioFormatter)
    formatter.format.return_value = list(messages)
    sender = Mock(spec=MessageSender)
    return (
        ShowPortfolioCommand(list_use_case, get_use_case, formatter, sender),
        get_use_case,
        sender,
    )


class TestShowPortfolioCommand:

    def test_metadata_id(self):
        command, _, _ = _command()
        assert command.get_metadata().id == "show_portfolio"

    def test_no_prompts_when_empty(self):
        command, _, _ = _command(summaries=[])
        assert command.get_input_prompts() == []

    def test_renders_to_console_without_sending(self):
        command, _, sender = _command()
        command.get_input_prompts()

        result = command.execute(portfolio_selection="1", send="no")

        assert "line1" in result.message
        assert "line2" in result.message
        sender.send_message.assert_not_called()

    def test_sends_each_message_when_confirmed(self):
        command, _, sender = _command(messages=("a", "b"))
        command.get_input_prompts()

        result = command.execute(portfolio_selection="1", send="yes")

        assert sender.send_message.call_count == 2
        assert "Telegram" in result.message

    def test_reports_not_found(self):
        command, get_use_case, _ = _command()
        get_use_case.handle.side_effect = PortfolioNotFound("main")
        command.get_input_prompts()

        result = command.execute(portfolio_selection="1", send="no")

        assert result.success is False
