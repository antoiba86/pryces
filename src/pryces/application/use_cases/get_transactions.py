from dataclasses import dataclass

from ...domain.portfolio.transactions import Transaction
from ..interfaces import PortfolioRepository


@dataclass(frozen=True)
class TransactionRecord:
    """A transaction tagged with the portfolio it belongs to (so a cross-portfolio
    history can show where each trade happened)."""

    portfolio: str
    transaction: Transaction


class GetTransactions:
    """Reads the transaction ledger for the per-stock history view — either for one
    portfolio or across all of the user's portfolios, optionally filtered by symbol."""

    def __init__(self, repository: PortfolioRepository) -> None:
        self._repository = repository

    def for_portfolio(
        self, portfolio_name: str, symbol: str | None = None, user_id: int = 1
    ) -> list[TransactionRecord]:
        # Raises PortfolioNotFound when the portfolio is missing.
        transactions = self._repository.get_transactions(portfolio_name, user_id=user_id)
        return [
            TransactionRecord(portfolio_name, t)
            for t in self._filtered_sorted(transactions, symbol)
        ]

    def across_portfolios(
        self, symbol: str | None = None, user_id: int = 1
    ) -> list[TransactionRecord]:
        records: list[TransactionRecord] = []
        for summary in self._repository.list_portfolios(user_id=user_id):
            transactions = self._repository.get_transactions(summary.name, user_id=user_id)
            records.extend(
                TransactionRecord(summary.name, t) for t in self._matching(transactions, symbol)
            )
        records.sort(key=lambda record: record.transaction.date)
        return records

    @staticmethod
    def _matching(transactions: list[Transaction], symbol: str | None) -> list[Transaction]:
        if symbol is None:
            return transactions
        target = symbol.upper()
        return [t for t in transactions if t.symbol.upper() == target]

    @classmethod
    def _filtered_sorted(
        cls, transactions: list[Transaction], symbol: str | None
    ) -> list[Transaction]:
        return sorted(cls._matching(transactions, symbol), key=lambda t: t.date)
