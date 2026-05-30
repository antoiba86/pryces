from ....application.exceptions import PortfolioNotFound
from ....application.interfaces import MessageSender
from ....application.use_cases.get_portfolio import GetPortfolio, GetPortfolioRequest
from ....application.use_cases.list_portfolios import ListPortfolios
from ....domain.portfolio.formatters import PortfolioFormatter
from ....domain.portfolio.portfolio import PortfolioSummary
from .base import Command, CommandMetadata, CommandResult, InputPrompt
from ..utils import create_portfolio_selection_validator, format_portfolio_list


def _validate_confirm(value: str) -> str | None:
    if value.strip().lower() in ("yes", "no"):
        return None
    return "Enter 'yes' to send or 'no' to skip."


class ShowPortfolioCommand(Command):
    def __init__(
        self,
        list_portfolios: ListPortfolios,
        get_portfolio: GetPortfolio,
        formatter: PortfolioFormatter,
        message_sender: MessageSender,
    ) -> None:
        self._list_portfolios = list_portfolios
        self._get_portfolio = get_portfolio
        self._formatter = formatter
        self._message_sender = message_sender
        self._summaries: list[PortfolioSummary] = []

    def get_metadata(self) -> CommandMetadata:
        return CommandMetadata(
            id="show_portfolio",
            name="Show Portfolio",
            description="Show a portfolio with live prices",
        )

    def get_input_prompts(self) -> list[InputPrompt]:
        self._summaries = self._list_portfolios.handle()
        if not self._summaries:
            return []

        count = len(self._summaries)
        return [
            InputPrompt(
                key="portfolio_selection",
                prompt=f"Select portfolio to show (1-{count}): ",
                validator=create_portfolio_selection_validator(count),
                preamble=format_portfolio_list(self._summaries),
            ),
            InputPrompt(
                key="send",
                prompt="Send to Telegram? (yes/no) [no]: ",
                validator=_validate_confirm,
                default="no",
            ),
        ]

    def execute(self, **kwargs) -> CommandResult:
        if not self._summaries:
            return CommandResult("No portfolios found.", success=False)

        selection = kwargs.get("portfolio_selection")
        summary = self._summaries[int(selection) - 1]

        try:
            portfolio = self._get_portfolio.handle(GetPortfolioRequest(name=summary.name))
        except PortfolioNotFound as error:
            return CommandResult(str(error), success=False)

        messages = self._formatter.format(portfolio)
        output = "\n\n".join(messages)

        if kwargs.get("send", "no").strip().lower() == "yes":
            for message in messages:
                self._message_sender.send_message(message)
            output += "\n\n(Sent to Telegram.)"

        return CommandResult(output)
