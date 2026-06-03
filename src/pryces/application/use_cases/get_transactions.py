from dataclasses import dataclass

from ...domain.portfolio.transactions import Transaction
from ..interfaces import PortfolioRepository


@dataclass(frozen=True)
class TransactionRecord:
    """A transaction tagged with its stable id and the portfolio it belongs to (so a
    cross-portfolio history can show where each trade happened, and the management
    view can address each row for edit/delete)."""

    portfolio: str
    id: str
    transaction: Transaction


class GetTransactions:
    """Reads the transaction ledger for the per-stock history view — either for one
    portfolio or across all of the user's portfolios, optionally filtered by symbol.
    Each row carries its stable id so the UI can edit or delete it."""

    def __init__(self, repository: PortfolioRepository) -> None:
        self._repository = repository

    def for_portfolio(
        self, portfolio_name: str, symbol: str | None = None, user_id: int = 1
    ) -> list[TransactionRecord]:
        # Raises PortfolioNotFound when the portfolio is missing.
        rows = self._repository.get_transactions_with_ids(portfolio_name, user_id=user_id)
        return [
            TransactionRecord(portfolio_name, row_id, transaction)
            for row_id, transaction in self._filtered_sorted(rows, symbol)
        ]

    def across_portfolios(
        self, symbol: str | None = None, user_id: int = 1
    ) -> list[TransactionRecord]:
        records: list[TransactionRecord] = []
        for summary in self._repository.list_portfolios(user_id=user_id):
            rows = self._repository.get_transactions_with_ids(summary.name, user_id=user_id)
            records.extend(
                TransactionRecord(summary.name, row_id, transaction)
                for row_id, transaction in self._matching(rows, symbol)
            )
        records.sort(key=lambda record: record.transaction.date)
        return records

    @staticmethod
    def _matching(
        rows: list[tuple[str, Transaction]], symbol: str | None
    ) -> list[tuple[str, Transaction]]:
        if symbol is None:
            return rows
        target = symbol.upper()
        return [row for row in rows if row[1].symbol.upper() == target]

    @classmethod
    def _filtered_sorted(
        cls, rows: list[tuple[str, Transaction]], symbol: str | None
    ) -> list[tuple[str, Transaction]]:
        return sorted(cls._matching(rows, symbol), key=lambda row: row[1].date)
