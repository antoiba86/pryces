from ....application.use_cases.delete_portfolio import DeletePortfolio, DeletePortfolioRequest
from ....application.use_cases.list_portfolios import ListPortfolios
from ....domain.portfolio.portfolio import PortfolioSummary
from .base import Command, CommandMetadata, CommandResult, InputPrompt
from ..utils import create_portfolio_selection_validator, format_portfolio_list


def _validate_confirm(value: str) -> str | None:
    if value.strip().lower() in ("yes", "no"):
        return None
    return "Enter 'yes' to confirm or 'no' to cancel."


class DeletePortfolioCommand(Command):
    def __init__(
        self,
        list_portfolios: ListPortfolios,
        delete_portfolio: DeletePortfolio,
    ) -> None:
        self._list_portfolios = list_portfolios
        self._delete_portfolio = delete_portfolio
        self._summaries: list[PortfolioSummary] = []

    def get_metadata(self) -> CommandMetadata:
        return CommandMetadata(
            id="delete_portfolio",
            name="Delete Portfolio",
            description="Delete an existing portfolio",
            show_progress=False,
        )

    def get_input_prompts(self) -> list[InputPrompt]:
        self._summaries = self._list_portfolios.handle()
        if not self._summaries:
            return []

        count = len(self._summaries)
        return [
            InputPrompt(
                key="portfolio_selection",
                prompt=f"Select portfolio to delete (1-{count}): ",
                validator=create_portfolio_selection_validator(count),
                preamble=format_portfolio_list(self._summaries),
            ),
            InputPrompt(
                key="confirm",
                prompt="Type 'yes' to confirm deletion: ",
                validator=_validate_confirm,
            ),
        ]

    def execute(self, **kwargs) -> CommandResult:
        if not self._summaries:
            return CommandResult("No portfolios found.", success=False)

        selection = kwargs.get("portfolio_selection")
        confirm = kwargs.get("confirm", "").strip().lower()
        summary = self._summaries[int(selection) - 1]

        if confirm != "yes":
            return CommandResult("Deletion cancelled.")

        self._delete_portfolio.handle(DeletePortfolioRequest(name=summary.name))
        return CommandResult(f"Portfolio deleted: {summary.name}")
