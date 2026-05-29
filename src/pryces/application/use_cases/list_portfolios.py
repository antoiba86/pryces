from ...domain.portfolio.portfolio import PortfolioSummary
from ..interfaces import PortfolioRepository


class ListPortfolios:
    def __init__(self, repository: PortfolioRepository) -> None:
        self._repository = repository

    def handle(self, user_id: int = 1) -> list[PortfolioSummary]:
        return self._repository.list_portfolios(user_id=user_id)
