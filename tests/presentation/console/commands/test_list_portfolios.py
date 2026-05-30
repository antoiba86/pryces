from unittest.mock import Mock

from pryces.application.use_cases.list_portfolios import ListPortfolios
from pryces.domain.portfolio.portfolio import PortfolioSummary
from pryces.presentation.console.commands.list_portfolios import ListPortfoliosCommand


def _command(summaries):
    use_case = Mock(spec=ListPortfolios)
    use_case.handle.return_value = summaries
    return ListPortfoliosCommand(use_case)


class TestListPortfoliosCommand:

    def test_metadata_id(self):
        assert _command([]).get_metadata().id == "list_portfolios"

    def test_no_input_prompts(self):
        assert _command([]).get_input_prompts() == []

    def test_empty_message_when_no_portfolios(self):
        result = _command([]).execute()

        assert "No portfolios" in result.message

    def test_lists_portfolios(self):
        summaries = [PortfolioSummary(name="main", base_currency="EUR", transaction_count=3)]

        result = _command(summaries).execute()

        assert "main" in result.message
        assert "EUR" in result.message
