from __future__ import annotations

import hashlib
from datetime import datetime
from decimal import Decimal, InvalidOperation

import xlrd

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

_BROKER_ID = "renta4"
_BROKER_LABEL = "Renta 4"

# Marks the funds export (the pension export shares the same column layout, so the
# title is what distinguishes them).
_FUNDS_MARKER = "fondos de inversión"
_HEADER_TOKENS = ("Fecha", "Tipo operación", "Participaciones")

# Spanish operation labels → transaction side. SUSCRIPCIÓN[ NUEVA] = buy units,
# REEMBOLSO[ TOTAL/PARCIAL] = sell units.
_BUY_PREFIX = "SUSCRIP"
_SELL_PREFIX = "REEMBOLS"


class Renta4FundsImporter(TransactionImporter):
    """Imports a Renta 4 "Operaciones en Fondos de Inversión" export (a binary .xls).

    The sheet has preamble rows, then a header row, then per-fund sections: a row
    carrying just the fund name acts as a group header for the operation rows
    beneath it. Each operation gives units (participaciones) and a gross amount, so
    the NAV is `importe_bruto / participaciones`; SUSCRIPCIÓN → BUY, REEMBOLSO →
    SELL. The export has no ISIN, so the fund name is emitted as the instrument
    name (resolution is via the user-editable symbol map). No order id is present,
    so a stable `raw_id` is synthesized from the row to keep re-imports deduped.
    """

    @property
    def broker_id(self) -> str:
        return _BROKER_ID

    def can_parse(self, content: bytes) -> bool:
        sheet = self._open(content)
        if sheet is None:
            return False
        return any(_FUNDS_MARKER in self._cell(sheet, r, c).lower() for r, c in self._cells(sheet))

    def parse(self, content: bytes) -> ImportResult:
        sheet = self._open(content)
        if sheet is None or not self.can_parse(content):
            raise UnrecognizedImportFormat(_BROKER_ID)

        columns = self._header_columns(sheet)
        if columns is None:
            raise UnrecognizedImportFormat(_BROKER_ID)

        transactions: list[Transaction] = []
        instruments: dict[str, Instrument] = {}
        warnings: list[ImportWarning] = []
        current_fund: str | None = None

        header_row = columns.pop("_row")
        for row in range(header_row + 1, sheet.nrows):
            first = self._cell(sheet, row, 0).strip()
            if not first:
                continue
            try:
                operation_date = datetime.strptime(first, "%d/%m/%Y").date()
            except ValueError:
                # A non-date in the first column is a fund-name section header.
                current_fund = first
                continue
            self._parse_operation(
                sheet,
                row,
                operation_date,
                columns,
                current_fund,
                transactions,
                instruments,
                warnings,
            )

        return ImportResult(
            transactions=tuple(transactions),
            warnings=tuple(warnings),
            instruments=tuple(instruments.values()),
        )

    def _parse_operation(
        self, sheet, row, operation_date, columns, fund, transactions, instruments, warnings
    ):
        def warn(message: str) -> None:
            warnings.append(
                ImportWarning(
                    code="invalid_row",
                    level=WarningLevel.WARNING,
                    message=f"Skipped row {row}: {message}",
                    affected_rows=(row,),
                )
            )

        if fund is None:
            warn("operation with no preceding fund name")
            return

        operation = self._cell(sheet, row, columns["Tipo operación"]).strip().upper()
        side = self._side(operation)
        if side is None:
            return  # not a buy/sell (e.g. traspaso/comision) — silently skip

        try:
            quantity = self._decimal(sheet, row, columns["Participaciones"])
            gross = self._decimal(sheet, row, columns["Importe bruto"])
            fee = self._decimal(sheet, row, columns.get("Comisión."), default=Decimal("0"))
            transaction = Transaction(
                date=operation_date,
                type=side,
                symbol=fund,
                currency=Currency.EUR,
                quantity=quantity,
                price=gross / quantity,
                fee=fee,
                broker=_BROKER_LABEL,
                raw_id=self._synthesize_id(fund, operation, sheet, row, columns),
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
        instruments.setdefault(fund, Instrument(symbol=fund, name=fund, currency=Currency.EUR))

    @staticmethod
    def _side(operation: str) -> TransactionType | None:
        if operation.startswith(_BUY_PREFIX):
            return TransactionType.BUY
        if operation.startswith(_SELL_PREFIX):
            return TransactionType.SELL
        return None

    @staticmethod
    def _open(content: bytes):
        try:
            return xlrd.open_workbook(file_contents=content).sheet_by_index(0)
        except Exception:
            # Not a readable .xls (e.g. a CSV/JSON passed during auto-detection).
            return None

    @staticmethod
    def _cells(sheet):
        for r in range(sheet.nrows):
            for c in range(sheet.ncols):
                yield r, c

    @staticmethod
    def _cell(sheet, row: int, col: int) -> str:
        value = sheet.cell_value(row, col)
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value)

    @classmethod
    def _header_columns(cls, sheet) -> dict | None:
        for row in range(sheet.nrows):
            labels = [cls._cell(sheet, row, c).strip() for c in range(sheet.ncols)]
            if all(token in labels for token in _HEADER_TOKENS):
                columns = {label: index for index, label in enumerate(labels) if label}
                columns["_row"] = row
                return columns
        return None

    @classmethod
    def _decimal(cls, sheet, row: int, col: int | None, default: Decimal | None = None) -> Decimal:
        if col is None:
            if default is not None:
                return default
            raise ValueError("missing column")
        raw = cls._cell(sheet, row, col).strip()
        if raw == "":
            if default is not None:
                return default
            raise ValueError("empty number")
        return Decimal(raw)

    @classmethod
    def _synthesize_id(cls, fund: str, operation: str, sheet, row: int, columns: dict) -> str:
        parts = [
            fund,
            operation,
            cls._cell(sheet, row, columns["Fecha"]),
            cls._cell(sheet, row, columns["Participaciones"]),
            cls._cell(sheet, row, columns["Importe bruto"]),
        ]
        return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:16]
