import json
from datetime import date
from pathlib import Path

from ....application.use_cases.export_data import ExportData, ExportDataRequest
from ....application.use_cases.list_portfolios import ListPortfolios
from ....domain.portfolio.portfolio import PortfolioSummary
from ..utils import format_portfolio_list
from .base import Command, CommandMetadata, CommandResult, InputPrompt


class ExportDataCommand(Command):
    def __init__(self, list_portfolios: ListPortfolios, export_data: ExportData) -> None:
        self._list_portfolios = list_portfolios
        self._export_data = export_data
        self._summaries: list[PortfolioSummary] = []

    def get_metadata(self) -> CommandMetadata:
        return CommandMetadata(
            id="export_data",
            name="Export Data",
            description="Export all portfolio data (or one portfolio) to a JSON backup file",
            show_progress=False,
        )

    def get_input_prompts(self) -> list[InputPrompt]:
        self._summaries = self._list_portfolios.handle()
        if not self._summaries:
            return []

        count = len(self._summaries)
        return [
            InputPrompt(
                key="scope_selection",
                prompt=f"Select what to export (0-{count}): ",
                validator=self._validate_scope,
                preamble=f"  0. All portfolios\n{format_portfolio_list(self._summaries)}",
            ),
            InputPrompt(
                key="destination",
                prompt="Destination file: ",
                validator=_validate_destination,
                default=f"pryces_export_{date.today().strftime('%Y%m%d')}.json",
            ),
        ]

    def execute(self, **kwargs) -> CommandResult:
        if not self._summaries:
            return CommandResult("No portfolios found.", success=False)

        selection = int(kwargs.get("scope_selection"))
        portfolio_name = None if selection == 0 else self._summaries[selection - 1].name
        destination = Path(kwargs.get("destination").strip())

        document = self._export_data.handle(ExportDataRequest(portfolio_name=portfolio_name))
        try:
            destination.write_text(
                json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
        except OSError as error:
            return CommandResult(f"Could not write {destination}: {error}", success=False)

        portfolios = document["portfolios"]
        transactions = sum(len(entry["transactions"]) for entry in portfolios)
        return CommandResult(
            f"Exported {len(portfolios)} portfolio(s) with {transactions} transaction(s)"
            f" to {destination}"
        )

    def _validate_scope(self, value: str) -> str | None:
        count = len(self._summaries)
        try:
            selection = int(value.strip())
        except ValueError:
            return f"Enter a number between 0 and {count}."
        if 0 <= selection <= count:
            return None
        return f"Enter a number between 0 and {count}."


def _validate_destination(value: str) -> str | None:
    if not value or not value.strip():
        return "Enter a destination path."
    path = Path(value.strip())
    if path.exists():
        return "File already exists — choose another path."
    if not path.parent.exists():
        return f"Directory not found: {path.parent}"
    return None
