from unittest.mock import Mock

import pytest

from pryces.application.exceptions import PortfolioNotFound
from pryces.application.interfaces import PortfolioRepository
from pryces.application.use_cases.delete_portfolio import (
    DeletePortfolio,
    DeletePortfolioRequest,
)


class TestDeletePortfolio:

    def setup_method(self):
        self.mock_repository = Mock(spec=PortfolioRepository)

    def test_handle_deletes_portfolio(self):
        use_case = DeletePortfolio(repository=self.mock_repository)
        request = DeletePortfolioRequest(name="main")

        use_case.handle(request)

        self.mock_repository.delete.assert_called_once_with(name="main", user_id=1)

    def test_handle_passes_through_user_id(self):
        use_case = DeletePortfolio(repository=self.mock_repository)
        request = DeletePortfolioRequest(name="main", user_id=42)

        use_case.handle(request)

        self.mock_repository.delete.assert_called_once_with(name="main", user_id=42)

    def test_handle_propagates_not_found_error(self):
        self.mock_repository.delete.side_effect = PortfolioNotFound("ghost")
        use_case = DeletePortfolio(repository=self.mock_repository)
        request = DeletePortfolioRequest(name="ghost")

        with pytest.raises(PortfolioNotFound):
            use_case.handle(request)
