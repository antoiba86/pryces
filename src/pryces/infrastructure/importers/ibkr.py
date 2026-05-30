from __future__ import annotations

import csv
import hashlib
import io
from datetime import date
from decimal import Decimal, InvalidOperation

from ...application.exceptions import UnrecognizedImportFormat
from ...application.interfaces import TransactionImporter
from ...domain.portfolio.transactions import (
    ImportResult,
    ImportWarning,
    Instrument,
    Transaction,
    TransactionType,
    TransactionValidationError,
    WarningLevel,
    normalize_transactions,
)
from ...domain.stocks import Currency

_BROKER_ID = "ibkr"
_BROKER_LABEL = "IBKR"

_SECTION = "Transaction History"
# Distinctive header tokens of the Transaction History section (the section
# names are localized, but these column headers are not).
_HEADER_SIGNATURE = ("Transaction Type", "Symbol", "Price Currency")

_TYPE_MAP = {"Buy": TransactionType.BUY, "Sell": TransactionType.SELL}


class IbkrActivityImporter(TransactionImporter):
    """Imports an Interactive Brokers Activity Statement (Transaction History CSV).

    The export is a multi-section CSV; only the `Transaction History` section's
    `Buy`/`Sell` rows are mapped (deposits, forex legs, and adjustments are
    cash/FX noise and skipped). `Price` is in the trade currency while
    `Gross/Commission/Net` are in the account base currency, so the commission
    is converted to the trade currency via the row's implied rate
    (`quantity * price / |gross|`). The export carries no order id, so a stable
    `raw_id` is synthesized from the row to keep re-imports deduplicated.

    Instruments are emitted with the IBKR ticker as the symbol plus the
    description as the name, so the downstream SymbolResolver can map non-US
    tickers (e.g. `TTT` → `TTT.AX`) to their Yahoo symbols.
    """

    @property
    def broker_id(self) -> str:
        return _BROKER_ID

    def can_parse(self, content: str) -> bool:
        for row in self._rows(content):
            if row[:2] == [_SECTION, "Header"]:
                return all(token in row for token in _HEADER_SIGNATURE)
        return False

    def parse(self, content: str) -> ImportResult:
        columns = self._header_columns(content)
        if columns is None:
            raise UnrecognizedImportFormat(_BROKER_ID)

        transactions: list[Transaction] = []
        instruments: dict[str, Instrument] = {}
        warnings: list[ImportWarning] = []
        for index, row in enumerate(self._rows(content)):
            if row[:2] != [_SECTION, "Data"]:
                continue
            fields = self._fields(row, columns)
            if fields.get("Transaction Type") not in _TYPE_MAP:
                continue  # deposits, forex legs, adjustments — not equity trades
            self._add_trade(index, fields, transactions, instruments, warnings)

        return ImportResult(
            transactions=tuple(transactions),
            warnings=tuple(warnings),
            instruments=tuple(instruments.values()),
        )

    def _add_trade(
        self,
        index: int,
        fields: dict[str, str],
        transactions: list[Transaction],
        instruments: dict[str, Instrument],
        warnings: list[ImportWarning],
    ) -> None:
        try:
            quantity = _decimal(fields["Quantity"])
            symbol = fields["Symbol"].strip()
            transaction = Transaction(
                date=date.fromisoformat(fields["Date"].strip()),
                type=_TYPE_MAP[fields["Transaction Type"]],
                symbol=symbol,
                currency=Currency(fields["Price Currency"].strip()),
                quantity=abs(quantity),
                price=_decimal(fields["Price"]),
                fee=self._fee(fields, quantity),
                broker=_BROKER_LABEL,
                raw_id=_synthesize_id(fields),
            )
            normalize_transactions([transaction])
        except (KeyError, ValueError, InvalidOperation, TransactionValidationError) as error:
            warnings.append(
                ImportWarning(
                    code="invalid_row",
                    level=WarningLevel.WARNING,
                    message=f"Skipped row {index}: {error}",
                    affected_rows=(index,),
                )
            )
            return

        transactions.append(transaction)
        instruments.setdefault(
            symbol,
            Instrument(symbol=symbol, name=fields.get("Description", "").strip() or None),
        )

    @staticmethod
    def _fee(fields: dict[str, str], quantity: Decimal) -> Decimal:
        commission = _abs_decimal(fields.get("Commission", ""))
        if commission == 0:
            return Decimal("0")
        gross = _abs_decimal(fields.get("Gross Amount", ""))
        notional = abs(quantity) * _decimal(fields["Price"])
        if gross == 0 or notional == 0:
            return commission
        # Commission is billed in the base currency; convert to the trade
        # currency using the rate implied by this row (trade-ccy per base-ccy).
        return commission * (notional / gross)

    def _header_columns(self, content: str) -> dict[str, int] | None:
        for row in self._rows(content):
            if row[:2] == [_SECTION, "Header"] and all(t in row for t in _HEADER_SIGNATURE):
                # Header names start after the two section-marker columns.
                return {name.strip(): position for position, name in enumerate(row[2:])}
        return None

    @staticmethod
    def _fields(row: list[str], columns: dict[str, int]) -> dict[str, str]:
        values = row[2:]
        return {
            name: values[position] for name, position in columns.items() if position < len(values)
        }

    @staticmethod
    def _rows(content: str) -> list[list[str]]:
        return list(csv.reader(io.StringIO(content)))


def _synthesize_id(fields: dict[str, str]) -> str:
    parts = "|".join(
        fields.get(key, "") for key in ("Date", "Symbol", "Quantity", "Price", "Net Amount")
    )
    return hashlib.sha1(parts.encode("utf-8")).hexdigest()[:16]


def _decimal(raw: str) -> Decimal:
    text = raw.strip()
    if not text or text == "-":
        raise ValueError("missing number")
    return Decimal(text)


def _abs_decimal(raw: str) -> Decimal:
    text = raw.strip()
    if not text or text == "-":
        return Decimal("0")
    return abs(Decimal(text))
