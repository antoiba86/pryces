from unittest.mock import Mock

from pryces.application.exceptions import PortfolioAlreadyExists
from pryces.application.use_cases.create_portfolio import CreatePortfolio
from pryces.domain.portfolio.portfolio import PortfolioSummary
from pryces.presentation.console.commands.create_portfolio import CreatePortfolioCommand


def _command(use_case=None):
    return CreatePortfolioCommand(use_case or Mock(spec=CreatePortfolio))


class TestCreatePortfolioCommand:

    def test_metadata_id(self):
        assert _command().get_metadata().id == "create_portfolio"

    def test_prompts_for_name_and_currency(self):
        prompts = _command().get_input_prompts()

        assert [p.key for p in prompts] == ["name", "base_currency"]
        assert prompts[1].default == "EUR"

    def test_creates_with_blank_name_as_auto(self):
        use_case = Mock(spec=CreatePortfolio)
        use_case.handle.return_value = PortfolioSummary("auto", "EUR", 0)

        result = _command(use_case).execute(name="  ", base_currency="eur")

        request = use_case.handle.call_args.args[0]
        assert request.name is None
        assert request.base_currency == "EUR"
        assert result.success is True

    def test_reports_already_exists(self):
        use_case = Mock(spec=CreatePortfolio)
        use_case.handle.side_effect = PortfolioAlreadyExists("main")

        result = _command(use_case).execute(name="main", base_currency="EUR")

        assert result.success is False
