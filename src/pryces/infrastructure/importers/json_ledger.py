from __future__ import annotations

import json
from datetime import date
from decimal import Decimal, InvalidOperation

from ...application.exceptions import UnrecognizedImportFormat
from ...application.interfaces import TransactionImporter
from ...domain.portfolio.transactions import (
    ImportResult,
    ImportWarning,
    Transaction,
    TransactionType,
    TransactionValidationError,
    WarningLevel,
    normalize_transactions,
)
from ...domain.stocks import Currency

_BROKER_ID = "json"


class JsonLedgerImporter(TransactionImporter):
    """Imports the JSON ledger shape used by `JsonPortfolioRepository`.

    Recognizes a top-level object with a `transactions` array (the same shape
    portfolio files are persisted in), giving prototype users a one-command
    migration path. Each malformed row is skipped with a warning rather than
    aborting the whole import.
    """

    @property
    def broker_id(self) -> str:
        return _BROKER_ID

    def can_parse(self, content: str) -> bool:
        try:
            data = json.loads(content)
        except (json.JSONDecodeError, ValueError):
            return False
        return isinstance(data, dict) and isinstance(data.get("transactions"), list)

    def parse(self, content: str) -> ImportResult:
        try:
            data = json.loads(content)
        except (json.JSONDecodeError, ValueError) as error:
            raise UnrecognizedImportFormat(_BROKER_ID) from error
        if not isinstance(data, dict) or not isinstance(data.get("transactions"), list):
            raise UnrecognizedImportFormat(_BROKER_ID)

        transactions: list[Transaction] = []
        warnings: list[ImportWarning] = []
        for index, row in enumerate(data["transactions"]):
            transaction = self._build_transaction(index, row, warnings)
            if transaction is not None:
                transactions.append(transaction)
        return ImportResult(transactions=tuple(transactions), warnings=tuple(warnings))

    def _build_transaction(
        self,
        index: int,
        row: object,
        warnings: list[ImportWarning],
    ) -> Transaction | None:
        try:
            transaction = self._row_to_transaction(row)
            normalize_transactions([transaction])
        except (
            KeyError,
            TypeError,
            ValueError,
            InvalidOperation,
            TransactionValidationError,
        ) as error:
            warnings.append(
                ImportWarning(
                    code="invalid_row",
                    level=WarningLevel.WARNING,
                    message=f"Skipped transaction at index {index}: {error}",
                    affected_rows=(index,),
                )
            )
            return None
        return transaction

    @staticmethod
    def _row_to_transaction(row: object) -> Transaction:
        if not isinstance(row, dict):
            raise TypeError("transaction row must be an object")
        return Transaction(
            date=date.fromisoformat(row["date"]),
            type=TransactionType(row["type"]),
            symbol=row["symbol"],
            currency=Currency(row["currency"]),
            quantity=_to_decimal(row.get("quantity")),
            price=_to_decimal(row.get("price")),
            amount=_to_decimal(row.get("amount")),
            fee=_to_decimal(row.get("fee")) or Decimal("0"),
            broker=row.get("broker"),
            raw_id=row.get("raw_id"),
        )


def _to_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))
