from unittest.mock import Mock

from pryces.application.use_cases.delete_portfolio import DeletePortfolio
from pryces.application.use_cases.list_portfolios import ListPortfolios
from pryces.domain.portfolio.portfolio import PortfolioSummary
from pryces.presentation.console.commands.delete_portfolio import DeletePortfolioCommand


def _command(summaries):
    list_use_case = Mock(spec=ListPortfolios)
    list_use_case.handle.return_value = summaries
    delete_use_case = Mock(spec=DeletePortfolio)
    return DeletePortfolioCommand(list_use_case, delete_use_case), delete_use_case


_SUMMARIES = [PortfolioSummary(name="main", base_currency="EUR", transaction_count=3)]


class TestDeletePortfolioCommand:

    def test_metadata_id(self):
        command, _ = _command(_SUMMARIES)
        assert command.get_metadata().id == "delete_portfolio"

    def test_no_prompts_when_empty(self):
        command, _ = _command([])
        assert command.get_input_prompts() == []

    def test_two_prompts_when_portfolios_exist(self):
        command, _ = _command(_SUMMARIES)

        prompts = command.get_input_prompts()

        assert [p.key for p in prompts] == ["portfolio_selection", "confirm"]

    def test_execute_no_portfolios_returns_error(self):
        command, _ = _command([])
        command.get_input_prompts()

        result = command.execute()

        assert result.success is False

    def test_execute_cancels_when_not_confirmed(self):
        command, delete_use_case = _command(_SUMMARIES)
        command.get_input_prompts()

        result = command.execute(portfolio_selection="1", confirm="no")

        assert "cancel" in result.message.lower()
        delete_use_case.handle.assert_not_called()

    def test_execute_deletes_when_confirmed(self):
        command, delete_use_case = _command(_SUMMARIES)
        command.get_input_prompts()

        result = command.execute(portfolio_selection="1", confirm="yes")

        assert result.success is True
        assert delete_use_case.handle.call_args.args[0].name == "main"
