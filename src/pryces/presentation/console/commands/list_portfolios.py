from ....application.use_cases.list_portfolios import ListPortfolios
from .base import Command, CommandMetadata, CommandResult, InputPrompt
from ..utils import format_portfolio_list


class ListPortfoliosCommand(Command):
    def __init__(self, list_portfolios: ListPortfolios) -> None:
        self._list_portfolios = list_portfolios

    def get_metadata(self) -> CommandMetadata:
        return CommandMetadata(
            id="list_portfolios",
            name="List Portfolios",
            description="List all portfolios",
            show_progress=False,
        )

    def get_input_prompts(self) -> list[InputPrompt]:
        return []

    def execute(self, **kwargs) -> CommandResult:
        summaries = self._list_portfolios.handle()
        if not summaries:
            return CommandResult("No portfolios found.")
        return CommandResult(format_portfolio_list(summaries))
