from __future__ import annotations

import csv
import hashlib
import io
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from ...application.exceptions import UnrecognizedImportFormat
from ...application.interfaces import TransactionImporter
from ...application.text import decode_csv
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
# Horos offers no download). Columns: type, product, NAV, amount, date. Labels
# are upper-cased before matching: the site has emitted both "TIPO DE OPERACIÓN"
# and "Tipo de operación", and the casing carries no meaning.
_DELIMITER = ";"
_HEADER_SIGNATURE = ("TIPO DE OPERACIÓN", "PRODUCTO", "VL", "IMPORTE")

# Both year widths appear in the wild ("01/06/2026" and "04/08/26").
_DATE_FORMATS = ("%d/%m/%Y", "%d/%m/%y")

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
        rows = self._rows(content)
        joined = ";".join(_label(cell) for cell in rows[0]) if rows else ""
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
            when = _parse_date(self._value(row, columns, "FECHA"))
            transaction = Transaction(
                date=when,
                type=side,
                symbol=product,
                currency=Currency.EUR,
                quantity=amount / nav,
                price=nav,
                fee=Decimal("0"),
                broker=_BROKER_LABEL,
                raw_id=self._synthesize_id(operation, product, when, nav, amount),
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
        # can_parse must never raise: a binary file (e.g. an .xls being
        # auto-detected) decodes to garbage that csv.reader chokes on.
        try:
            return list(csv.reader(io.StringIO(decode_csv(content)), delimiter=_DELIMITER))
        except csv.Error:
            return []

    @classmethod
    def _header_columns(cls, rows: list[list[str]]) -> dict[str, int] | None:
        if not rows:
            return None
        labels = [_label(cell) for cell in rows[0]]
        if not all(token in labels for token in _HEADER_SIGNATURE):
            return None
        return {label: index for index, label in enumerate(labels) if label}

    @staticmethod
    def _value(row: list[str], columns: dict[str, int], label: str) -> str:
        index = columns[label]
        return row[index].strip() if index < len(row) else ""

    @staticmethod
    def _synthesize_id(
        operation: str, product: str, when: date, nav: Decimal, amount: Decimal
    ) -> str:
        # Hash the *parsed* values, not the raw cells: Horos has changed its date
        # and money formatting between exports, and a formatting-sensitive id
        # would make the same operation look new and re-insert as a duplicate.
        parts = [product, operation, when.isoformat(), _canonical(nav), _canonical(amount)]
        return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:16]


def _label(cell: str) -> str:
    # Column names are matched case-insensitively by normalizing to the upper
    # case form the signature and the per-row lookups use.
    return cell.strip().upper()


def _canonical(value: Decimal) -> str:
    # "200,00 €" and "200" must hash identically; normalize() drops trailing
    # zeros and "f" keeps it out of exponent notation.
    return format(value.normalize(), "f")


def _parse_date(raw: str) -> date:
    for date_format in _DATE_FORMATS:
        try:
            return datetime.strptime(raw, date_format).date()
        except ValueError:
            continue
    raise ValueError(f"unrecognized date: {raw!r}")


def _money(raw: str) -> Decimal:
    # Spanish-locale money: "1.234,56 €" -> Decimal("1234.56"); strip currency and
    # (non-breaking) spaces, drop thousands dots, comma is the decimal separator.
    cleaned = raw.replace("€", "").replace("\xa0", "").strip()
    cleaned = cleaned.replace(".", "").replace(",", ".")
    if cleaned == "":
        raise ValueError("empty number")
    return Decimal(cleaned)
