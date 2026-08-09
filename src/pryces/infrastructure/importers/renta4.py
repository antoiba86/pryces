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

_HEADER_TOKENS = ("Fecha", "Tipo operación", "Participaciones")


class _Renta4Importer(TransactionImporter):
    """Shared parsing for Renta 4's binary .xls operation exports.

    Funds and pension plans use the *same* sheet layout — preamble rows, a header
    row, then per-product sections where a row carrying just the product name is a
    group header for the operations beneath it. Only the title line and the Spanish
    operation verbs differ, so subclasses supply those and inherit everything else;
    keeping one parser is what stops the two drifting apart.

    Each operation gives units (participaciones) and a gross amount, so the NAV is
    `importe_bruto / participaciones`. Neither export carries an ISIN, so the
    product name is emitted as the instrument and resolution goes through the
    user-editable symbol map. No order id is present, so a stable `raw_id` is
    synthesized from the row to keep re-imports deduped.
    """

    # The title fragment that identifies this export. Both layouts are otherwise
    # identical, so without it one importer would swallow the other's files.
    _MARKER: str = ""
    _BROKER_ID: str = ""
    # The label stored on every transaction, and what the single-broker rule
    # compares — so this, not `_BROKER_ID`, decides whether two exports can share
    # a portfolio.
    _BROKER_LABEL: str = ""
    _BUY_PREFIXES: tuple[str, ...] = ()
    _SELL_PREFIXES: tuple[str, ...] = ()
    # Funds legitimately carry rows that are neither side (traspaso, comisión) and
    # skip them quietly. Pension vocabulary is less well known here, so unknown
    # verbs are reported rather than dropped silently.
    _WARN_ON_UNKNOWN_OPERATION: bool = False

    @property
    def broker_id(self) -> str:
        return self._BROKER_ID

    def can_parse(self, content: bytes) -> bool:
        sheet = self._open(content)
        if sheet is None:
            return False
        return any(self._MARKER in self._cell(sheet, r, c).lower() for r, c in self._cells(sheet))

    def parse(self, content: bytes) -> ImportResult:
        sheet = self._open(content)
        if sheet is None or not self.can_parse(content):
            raise UnrecognizedImportFormat(self._BROKER_ID)

        columns = self._header_columns(sheet)
        if columns is None:
            raise UnrecognizedImportFormat(self._BROKER_ID)

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
            if self._WARN_ON_UNKNOWN_OPERATION and operation:
                warn(f"unrecognized operation {operation!r}")
            return  # not a buy/sell (e.g. traspaso/comision)

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
                broker=self._BROKER_LABEL,
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

    @classmethod
    def _side(cls, operation: str) -> TransactionType | None:
        if operation.startswith(cls._BUY_PREFIXES):
            return TransactionType.BUY
        if operation.startswith(cls._SELL_PREFIXES):
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


class Renta4FundsImporter(_Renta4Importer):
    """ "Operaciones en Fondos de Inversión" — SUSCRIPCIÓN[ NUEVA] buys units,
    REEMBOLSO[ TOTAL/PARCIAL] sells them."""

    _MARKER = "fondos de inversión"
    _BROKER_ID = "renta4"
    _BROKER_LABEL = "Renta 4"
    _BUY_PREFIXES = ("SUSCRIP",)
    _SELL_PREFIXES = ("REEMBOLS",)


class Renta4PensionsImporter(_Renta4Importer):
    """ "Operaciones en Planes de Pensiones" — APORTACIÓN[ NUEVA] buys units.

    Deliberately carries its **own** broker label, which the single-broker rule
    turns into a separate portfolio from the funds export. A pension is locked
    until retirement and taxed differently, so blending it with a liquid fund
    would produce portfolio-level XIRR/TWR figures describing a pot that cannot
    be acted on as a unit. Nothing is lost at the top: the overview rolls every
    portfolio into one net-worth view regardless.

    The plan is also a separate *instrument* from the manager's fund of the same
    name — different vehicle, different NAV (15.47 against 28.97 for Numantia) —
    and keys off its own product name, so the symbol map maps the two
    independently.

    Payout verbs are a best guess: no export with one has been seen, so anything
    unrecognized is reported rather than dropped.
    """

    _MARKER = "planes de pensiones"
    _BROKER_ID = "renta4_pensions"
    _BROKER_LABEL = "Renta 4 Pensiones"
    _BUY_PREFIXES = ("APORTACI",)
    _SELL_PREFIXES = ("PRESTACI", "RESCATE", "DISPOSICI")
    _WARN_ON_UNKNOWN_OPERATION = True
