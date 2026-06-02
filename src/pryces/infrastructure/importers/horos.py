from __future__ import annotations

import csv
import hashlib
import io
from datetime import datetime
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

_BROKER_ID = "horos"
_BROKER_LABEL = "Horos"

# Header of the Horos web "movimientos" table (pasted out as a semicolon CSV —
# Horos offers no download). Columns: type, product, NAV, amount, date.
_DELIMITER = ";"
_HEADER_SIGNATURE = ("TIPO DE OPERACIÓN", "PRODUCTO", "VL", "IMPORTE")

_BUY_PREFIX = "SUSCRIP"
_SELL_PREFIX = "REEMBOLS"


class HorosFundsImporter(TransactionImporter):
    """Imports the Horos Asset Management fund "movimientos" table.

    Horos has no export, so the user pastes the web movements table into a
    semicolon CSV with columns `TIPO DE OPERACIÓN; PRODUCTO; VL; IMPORTE; FECHA`.
    The row gives the NAV (VL) and the amount invested (IMPORTE) but not the
    units, so `quantity = IMPORTE / VL`; SUSCRIPCIÓN → BUY, REEMBOLSO → SELL.
    The table has no ISIN, so the product name is emitted as the instrument name
    (resolution relies on a user-edited symbol_map.json entry). No order id, so a
    stable `raw_id` is synthesized from the row for dedup.
    """

    @property
    def broker_id(self) -> str:
        return _BROKER_ID

    def can_parse(self, content: bytes) -> bool:
        header = self._rows(content)[0] if self._rows(content) else []
        joined = ";".join(header)
        return all(token in joined for token in _HEADER_SIGNATURE)

    def parse(self, content: bytes) -> ImportResult:
        rows = self._rows(content)
        columns = self._header_columns(rows)
        if columns is None:
            raise UnrecognizedImportFormat(_BROKER_ID)

        transactions: list[Transaction] = []
        instruments: dict[str, Instrument] = {}
        warnings: list[ImportWarning] = []

        for index, row in enumerate(rows[1:], start=1):
            if not any(cell.strip() for cell in row):
                continue
            self._parse_row(index, row, columns, transactions, instruments, warnings)

        return ImportResult(
            transactions=tuple(transactions),
            warnings=tuple(warnings),
            instruments=tuple(instruments.values()),
        )

    def _parse_row(self, index, row, columns, transactions, instruments, warnings):
        def warn(message: str) -> None:
            warnings.append(
                ImportWarning(
                    code="invalid_row",
                    level=WarningLevel.WARNING,
                    message=f"Skipped row {index}: {message}",
                    affected_rows=(index,),
                )
            )

        operation = self._value(row, columns, "TIPO DE OPERACIÓN").upper()
        side = self._side(operation)
        if side is None:
            return  # not a buy/sell — silently skip

        product = self._value(row, columns, "PRODUCTO")
        if not product:
            warn("missing product")
            return

        try:
            nav = _money(self._value(row, columns, "VL"))
            amount = _money(self._value(row, columns, "IMPORTE"))
            transaction = Transaction(
                date=datetime.strptime(self._value(row, columns, "FECHA"), "%d/%m/%Y").date(),
                type=side,
                symbol=product,
                currency=Currency.EUR,
                quantity=amount / nav,
                price=nav,
                fee=Decimal("0"),
                broker=_BROKER_LABEL,
                raw_id=self._synthesize_id(operation, product, row, columns),
            )
            normalize_transactions([transaction])
        except (
            KeyError,
            ValueError,
            ZeroDivisionError,
            InvalidOperation,
            TransactionValidationError,
        ) as error:
            warn(str(error))
            return

        transactions.append(transaction)
        instruments.setdefault(
            product, Instrument(symbol=product, name=product, currency=Currency.EUR)
        )

    @staticmethod
    def _side(operation: str) -> TransactionType | None:
        if operation.startswith(_BUY_PREFIX):
            return TransactionType.BUY
        if operation.startswith(_SELL_PREFIX):
            return TransactionType.SELL
        return None

    @staticmethod
    def _rows(content: bytes) -> list[list[str]]:
        text = content.decode("utf-8", errors="ignore")
        return list(csv.reader(io.StringIO(text), delimiter=_DELIMITER))

    @classmethod
    def _header_columns(cls, rows: list[list[str]]) -> dict[str, int] | None:
        if not rows:
            return None
        labels = [cell.strip() for cell in rows[0]]
        if not all(token in labels for token in _HEADER_SIGNATURE):
            return None
        return {label: index for index, label in enumerate(labels) if label}

    @staticmethod
    def _value(row: list[str], columns: dict[str, int], label: str) -> str:
        index = columns[label]
        return row[index].strip() if index < len(row) else ""

    @classmethod
    def _synthesize_id(cls, operation, product, row, columns) -> str:
        parts = [
            product,
            operation,
            cls._value(row, columns, "FECHA"),
            cls._value(row, columns, "VL"),
            cls._value(row, columns, "IMPORTE"),
        ]
        return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:16]


def _money(raw: str) -> Decimal:
    # Spanish-locale money: "1.234,56 €" -> Decimal("1234.56"); strip currency and
    # (non-breaking) spaces, drop thousands dots, comma is the decimal separator.
    cleaned = raw.replace("€", "").replace("\xa0", "").strip()
    cleaned = cleaned.replace(".", "").replace(",", ".")
    if cleaned == "":
        raise ValueError("empty number")
    return Decimal(cleaned)
