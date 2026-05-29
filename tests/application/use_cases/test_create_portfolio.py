from unittest.mock import Mock

import pytest

from pryces.application.exceptions import PortfolioAlreadyExists
from pryces.application.interfaces import PortfolioRepository
from pryces.application.use_cases.create_portfolio import (
    CreatePortfolio,
    CreatePortfolioRequest,
)
from pryces.domain.portfolio.portfolio import PortfolioSummary


class TestCreatePortfolio:

    def setup_method(self):
        self.mock_repository = Mock(spec=PortfolioRepository)

    def test_handle_creates_portfolio_with_explicit_name(self):
        summary = PortfolioSummary(name="main", base_currency="EUR", transaction_count=0)
        self.mock_repository.create.return_value = summary
        use_case = CreatePortfolio(repository=self.mock_repository)
        request = CreatePortfolioRequest(base_currency="EUR", name="main")

        result = use_case.handle(request)

        assert result is summary
        self.mock_repository.create.assert_called_once_with(
            base_currency="EUR", name="main", user_id=1
        )

    def test_handle_passes_none_name_for_auto_generated(self):
        summary = PortfolioSummary(
            name="portfolio_2026-05-29_10-00-00", base_currency="USD", transaction_count=0
        )
        self.mock_repository.create.return_value = summary
        use_case = CreatePortfolio(repository=self.mock_repository)
        request = CreatePortfolioRequest(base_currency="USD")

        result = use_case.handle(request)

        assert result is summary
        self.mock_repository.create.assert_called_once_with(
            base_currency="USD", name=None, user_id=1
        )

    def test_handle_passes_through_user_id(self):
        summary = PortfolioSummary(name="main", base_currency="EUR", transaction_count=0)
        self.mock_repository.create.return_value = summary
        use_case = CreatePortfolio(repository=self.mock_repository)
        request = CreatePortfolioRequest(base_currency="EUR", name="main", user_id=42)

        use_case.handle(request)

        self.mock_repository.create.assert_called_once_with(
            base_currency="EUR", name="main", user_id=42
        )

    def test_handle_propagates_already_exists_error(self):
        self.mock_repository.create.side_effect = PortfolioAlreadyExists("main")
        use_case = CreatePortfolio(repository=self.mock_repository)
        request = CreatePortfolioRequest(base_currency="EUR", name="main")

        with pytest.raises(PortfolioAlreadyExists):
            use_case.handle(request)
