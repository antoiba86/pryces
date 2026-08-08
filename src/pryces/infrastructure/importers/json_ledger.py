from __future__ import annotations

import json
from datetime import date
from decimal import Decimal, InvalidOperation

from ...application.exceptions import UnrecognizedImportFormat
from ...application.interfaces import TransactionImporter
from ...application.serialization import EXPORT_FORMAT, EXPORT_VERSION
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
    """Imports pryces' own JSON, in either shape it exists in.

    1. The **raw ledger** — a top-level object with a `transactions` array, the
       shape `JsonPortfolioRepository` persists portfolio files in.
    2. The **export document** the dashboard's Export button writes:
       `{format: "pryces-export", version, portfolios: [...]}`.

    The second makes export and import symmetric per portfolio: every portfolio
    accepts either its broker's own file or a JSON of the same rows. Without it
    you could download a portfolio as JSON and have no way to load it back into
    one, since the backup/restore screen restores whole portfolios *by name* —
    a different operation from "add these rows to this portfolio".

    A multi-portfolio export is refused rather than flattened: merging several
    portfolios into one silently destroys the split, and restore already does
    that job properly. Malformed rows are skipped with a warning rather than
    aborting the import.
    """

    @property
    def broker_id(self) -> str:
        return _BROKER_ID

    def can_parse(self, content: bytes) -> bool:
        data = _load(content)
        # Export documents match here even when `parse` will reject them (wrong
        # version, several portfolios) so the user gets that specific reason
        # instead of a generic "no importer recognised this file".
        return _ledger_rows(data) is not None or _is_export_document(data)

    def parse(self, content: bytes) -> ImportResult:
        data = _load(content)
        warnings: list[ImportWarning] = []

        rows = _ledger_rows(data)
        if rows is None:
            if not _is_export_document(data):
                raise UnrecognizedImportFormat(_BROKER_ID)
            rows = _export_rows(data, warnings)

        transactions: list[Transaction] = []
        for index, row in enumerate(rows):
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


def _load(content: bytes) -> object | None:
    # can_parse must never raise, so a non-JSON upload simply yields None.
    try:
        return json.loads(content)
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
        return None


def _ledger_rows(data: object) -> list | None:
    if isinstance(data, dict) and isinstance(data.get("transactions"), list):
        return data["transactions"]
    return None


def _is_export_document(data: object) -> bool:
    return (
        isinstance(data, dict)
        and data.get("format") == EXPORT_FORMAT
        and isinstance(data.get("portfolios"), list)
    )


def _export_rows(data: dict, warnings: list[ImportWarning]) -> list:
    """The single portfolio entry's rows, or a refusal explaining why not."""
    if data.get("version") != EXPORT_VERSION:
        raise UnrecognizedImportFormat(
            _BROKER_ID,
            f"Unsupported export version {data.get('version')!r}; this build reads "
            f"version {EXPORT_VERSION}.",
        )

    entries = [entry for entry in data["portfolios"] if isinstance(entry, dict)]
    if len(entries) > 1:
        names = ", ".join(str(entry.get("name")) for entry in entries)
        raise UnrecognizedImportFormat(
            _BROKER_ID,
            f"This backup holds {len(entries)} portfolios ({names}). Importing into a "
            "single portfolio would merge them, so it is refused — restore it from "
            "Portfolios → Import backup, or export one portfolio and import that.",
        )
    if not entries:
        return []

    entry = entries[0]
    if entry.get("manual_assets"):
        # Transactions are all this path can carry; saying so beats leaving the
        # user to notice the assets are missing.
        warnings.append(
            ImportWarning(
                code="manual_assets_ignored",
                level=WarningLevel.WARNING,
                message=(
                    f"{len(entry['manual_assets'])} manual asset(s) in the file were "
                    "ignored: a transaction import cannot carry them. Use "
                    "Portfolios \u2192 Import backup to restore those."
                ),
            )
        )
    rows = entry.get("transactions")
    return rows if isinstance(rows, list) else []


def _to_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))
