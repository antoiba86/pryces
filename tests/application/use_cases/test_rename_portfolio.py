from unittest.mock import Mock

import pytest

from pryces.application.exceptions import PortfolioAlreadyExists, PortfolioNotFound
from pryces.application.interfaces import PortfolioRepository
from pryces.application.use_cases.rename_portfolio import (
    RenamePortfolio,
    RenamePortfolioRequest,
)


class TestRenamePortfolio:

    def setup_method(self):
        self.mock_repository = Mock(spec=PortfolioRepository)

    def test_handle_renames_portfolio(self):
        use_case = RenamePortfolio(repository=self.mock_repository)
        request = RenamePortfolioRequest(old_name="main", new_name="primary")

        use_case.handle(request)

        self.mock_repository.rename.assert_called_once_with(
            old_name="main", new_name="primary", user_id=1
        )

    def test_handle_passes_through_user_id(self):
        use_case = RenamePortfolio(repository=self.mock_repository)
        request = RenamePortfolioRequest(old_name="a", new_name="b", user_id=42)

        use_case.handle(request)

        self.mock_repository.rename.assert_called_once_with(
            old_name="a", new_name="b", user_id=42
        )

    def test_handle_propagates_not_found_error(self):
        self.mock_repository.rename.side_effect = PortfolioNotFound("ghost")
        use_case = RenamePortfolio(repository=self.mock_repository)
        request = RenamePortfolioRequest(old_name="ghost", new_name="primary")

        with pytest.raises(PortfolioNotFound):
            use_case.handle(request)

    def test_handle_propagates_already_exists_error(self):
        self.mock_repository.rename.side_effect = PortfolioAlreadyExists("primary")
        use_case = RenamePortfolio(repository=self.mock_repository)
        request = RenamePortfolioRequest(old_name="main", new_name="primary")

        with pytest.raises(PortfolioAlreadyExists):
            use_case.handle(request)
