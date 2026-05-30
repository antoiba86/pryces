from ....application.exceptions import PortfolioAlreadyExists
from ....application.use_cases.create_portfolio import CreatePortfolio, CreatePortfolioRequest
from .base import Command, CommandMetadata, CommandResult, InputPrompt
from ..utils import validate_currency


class CreatePortfolioCommand(Command):
    def __init__(self, create_portfolio: CreatePortfolio) -> None:
        self._create_portfolio = create_portfolio

    def get_metadata(self) -> CommandMetadata:
        return CommandMetadata(
            id="create_portfolio",
            name="Create Portfolio",
            description="Create a new portfolio",
            show_progress=False,
        )

    def get_input_prompts(self) -> list[InputPrompt]:
        return [
            InputPrompt(
                key="name",
                prompt="Portfolio name (blank for an auto-generated name): ",
            ),
            InputPrompt(
                key="base_currency",
                prompt="Base currency [EUR]: ",
                validator=validate_currency,
                default="EUR",
            ),
        ]

    def execute(self, name: str = "", base_currency: str = "EUR", **kwargs) -> CommandResult:
        resolved_name = name.strip() or None
        try:
            summary = self._create_portfolio.handle(
                CreatePortfolioRequest(
                    base_currency=base_currency.strip().upper(),
                    name=resolved_name,
                )
            )
        except PortfolioAlreadyExists as error:
            return CommandResult(str(error), success=False)
        return CommandResult(f"Portfolio created: {summary.name} ({summary.base_currency})")
