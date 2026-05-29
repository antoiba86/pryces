from dataclasses import dataclass

from ..interfaces import PortfolioRepository


@dataclass(frozen=True)
class RenamePortfolioRequest:
    old_name: str
    new_name: str
    user_id: int = 1


class RenamePortfolio:
    def __init__(self, repository: PortfolioRepository) -> None:
        self._repository = repository

    def handle(self, request: RenamePortfolioRequest) -> None:
        self._repository.rename(
            old_name=request.old_name,
            new_name=request.new_name,
            user_id=request.user_id,
        )
