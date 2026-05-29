from dataclasses import dataclass

from ...domain.portfolio.portfolio import PortfolioSummary
from ..interfaces import PortfolioRepository


@dataclass(frozen=True)
class CreatePortfolioRequest:
    base_currency: str
    name: str | None = None
    user_id: int = 1


class CreatePortfolio:
    def __init__(self, repository: PortfolioRepository) -> None:
        self._repository = repository

    def handle(self, request: CreatePortfolioRequest) -> PortfolioSummary:
        return self._repository.create(
            base_currency=request.base_currency,
            name=request.name,
            user_id=request.user_id,
        )
