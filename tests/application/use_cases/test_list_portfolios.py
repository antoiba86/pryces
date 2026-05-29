from unittest.mock import Mock

from pryces.application.interfaces import PortfolioRepository
from pryces.application.use_cases.list_portfolios import ListPortfolios
from pryces.domain.portfolio.portfolio import PortfolioSummary


class TestListPortfolios:

    def setup_method(self):
        self.mock_repository = Mock(spec=PortfolioRepository)

    def test_handle_returns_repository_summaries(self):
        summaries = [
            PortfolioSummary(name="main", base_currency="EUR", transaction_count=3),
            PortfolioSummary(name="side", base_currency="USD", transaction_count=0),
        ]
        self.mock_repository.list_portfolios.return_value = summaries
        use_case = ListPortfolios(repository=self.mock_repository)

        result = use_case.handle()

        assert result == summaries
        self.mock_repository.list_portfolios.assert_called_once_with(user_id=1)

    def test_handle_returns_empty_list_when_no_portfolios(self):
        self.mock_repository.list_portfolios.return_value = []
        use_case = ListPortfolios(repository=self.mock_repository)

        result = use_case.handle()

        assert result == []

    def test_handle_passes_through_user_id(self):
        self.mock_repository.list_portfolios.return_value = []
        use_case = ListPortfolios(repository=self.mock_repository)

        use_case.handle(user_id=42)

        self.mock_repository.list_portfolios.assert_called_once_with(user_id=42)
