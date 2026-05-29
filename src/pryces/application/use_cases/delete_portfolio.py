from dataclasses import dataclass

from ..interfaces import PortfolioRepository


@dataclass(frozen=True)
class DeletePortfolioRequest:
    name: str
    user_id: int = 1


class DeletePortfolio:
    def __init__(self, repository: PortfolioRepository) -> None:
        self._repository = repository

    def handle(self, request: DeletePortfolioRequest) -> None:
        self._repository.delete(name=request.name, user_id=request.user_id)
