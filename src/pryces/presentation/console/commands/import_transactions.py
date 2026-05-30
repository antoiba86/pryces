from pathlib import Path

from ....application.exceptions import UnrecognizedImportFormat
from ....application.use_cases.import_transactions import (
    ImportTransactions,
    ImportTransactionsRequest,
)
from ....application.use_cases.list_portfolios import ListPortfolios
from ....domain.portfolio.portfolio import PortfolioSummary
from .base import Command, CommandMetadata, CommandResult, InputPrompt
from ..utils import (
    create_portfolio_selection_validator,
    format_portfolio_list,
    validate_file_path,
)


def _validate_confirm(value: str) -> str | None:
    if value.strip().lower() in ("yes", "no"):
        return None
    return "Enter 'yes' to import or 'no' to cancel."


class ImportTransactionsCommand(Command):
    def __init__(
        self,
        list_portfolios: ListPortfolios,
        import_transactions: ImportTransactions,
        broker_ids: list[str],
    ) -> None:
        self._list_portfolios = list_portfolios
        self._import_transactions = import_transactions
        self._broker_ids = broker_ids
        self._summaries: list[PortfolioSummary] = []

    def get_metadata(self) -> CommandMetadata:
        return CommandMetadata(
            id="import_transactions",
            name="Import Transactions",
            description="Import transactions from a broker export into a portfolio",
            show_progress=False,
        )

    def get_input_prompts(self) -> list[InputPrompt]:
        self._summaries = self._list_portfolios.handle()
        if not self._summaries:
            return []

        count = len(self._summaries)
        brokers = ", ".join(self._broker_ids)
        return [
            InputPrompt(
                key="portfolio_selection",
                prompt=f"Select target portfolio (1-{count}): ",
                validator=create_portfolio_selection_validator(count),
                preamble=format_portfolio_list(self._summaries),
            ),
            InputPrompt(
                key="file_path",
                prompt="Path to the export file: ",
                validator=validate_file_path,
            ),
            InputPrompt(
                key="broker",
                prompt="Broker (blank = auto-detect): ",
                validator=self._validate_broker,
                preamble=f"Available brokers: {brokers}\n",
            ),
            InputPrompt(
                key="confirm",
                prompt="Type 'yes' to import: ",
                validator=_validate_confirm,
            ),
        ]

    def execute(self, **kwargs) -> CommandResult:
        if not self._summaries:
            return CommandResult("No portfolios found.", success=False)

        if kwargs.get("confirm", "").strip().lower() != "yes":
            return CommandResult("Import cancelled.")

        summary = self._summaries[int(kwargs.get("portfolio_selection")) - 1]
        content = Path(kwargs.get("file_path").strip()).read_text(encoding="utf-8")
        broker = kwargs.get("broker", "").strip() or None

        try:
            result = self._import_transactions.handle(
                ImportTransactionsRequest(
                    portfolio_name=summary.name,
                    content=content,
                    broker=broker,
                )
            )
        except UnrecognizedImportFormat as error:
            return CommandResult(str(error), success=False)

        return CommandResult(self._format_result(summary.name, result))

    def _validate_broker(self, value: str) -> str | None:
        if not value.strip() or value.strip() in self._broker_ids:
            return None
        return f"Unknown broker. Choose one of: {', '.join(self._broker_ids)} (or leave blank)."

    @staticmethod
    def _format_result(portfolio_name, result) -> str:
        lines = [
            f"Imported into {portfolio_name} via {result.broker}:",
            f"  parsed: {result.parsed}",
            f"  inserted: {result.inserted}",
            f"  duplicates skipped: {result.duplicates}",
        ]
        if result.unresolved_symbols:
            lines.append(f"  unresolved symbols: {', '.join(result.unresolved_symbols)}")
        for warning in result.warnings:
            lines.append(f"  ⚠ {warning}")
        return "\n".join(lines)
