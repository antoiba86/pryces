from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date, datetime
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

_BROKER_ID = "degiro"
_BROKER_LABEL = "DEGIRO"

# Header tokens that uniquely identify a DEGIRO Transactions.csv export.
_HEADER_SIGNATURE = ("Fecha", "ISIN", "Producto")

# Fixed leading columns (stable across export versions). The order id is read
# as the last non-empty cell because newer exports append a trailing empty
# column, shifting "ID Orden" off its header position.
_COL_DATE = 0
_COL_NAME = 2
_COL_ISIN = 3
_COL_EXCHANGE = 4
_COL_VENUE = 5
_COL_QUANTITY = 6
_COL_PRICE = 7
_COL_PRICE_CURRENCY = 8
_COL_FX_RATE = 12
_COL_AUTOFX_FEE = 13
_COL_TRANSACTION_FEE = 14
_MIN_COLUMNS = 16


@dataclass(frozen=True, slots=True)
class _Fill:
    date: date
    type: TransactionType
    isin: str
    name: str
    exchange: str
    currency: Currency
    quantity: Decimal
    price: Decimal
    fee: Decimal
    order_id: str | None


class DegiroCsvImporter(TransactionImporter):
    """Imports a DEGIRO `Transactions.csv` export (trades only).

    Handles the Spanish-locale number format, `DD-MM-YYYY` dates, signed
    quantities (negative = sell), GBX→GBP pence conversion, and commissions
    reported in EUR (converted to the trade currency via the row's exchange
    rate). Multiple fills sharing an `ID Orden` are merged into one
    transaction (quantity summed, price quantity-weighted, fees added) so the
    repository's broker+raw_id dedup never drops a partial fill.

    Instruments are emitted with `symbol = ISIN`; a downstream SymbolResolver
    maps them to Yahoo tickers. Dividends live in DEGIRO's Account.csv and are
    out of scope here.
    """

    @property
    def broker_id(self) -> str:
        return _BROKER_ID

    def can_parse(self, content: str) -> bool:
        header = content.lstrip().splitlines()[0] if content.strip() else ""
        return all(token in header for token in _HEADER_SIGNATURE)

    def parse(self, content: str) -> ImportResult:
        rows = list(csv.reader(io.StringIO(content)))
        if not rows or not all(token in ",".join(rows[0]) for token in _HEADER_SIGNATURE):
            raise UnrecognizedImportFormat(_BROKER_ID)

        warnings: list[ImportWarning] = []
        fills: list[_Fill] = []
        for index, row in enumerate(rows[1:], start=1):
            if not any(cell.strip() for cell in row):
                continue
            fill = self._parse_row(index, row, warnings)
            if fill is not None:
                fills.append(fill)

        transactions, instruments = self._build(fills, warnings)
        return ImportResult(
            transactions=tuple(transactions),
            warnings=tuple(warnings),
            instruments=tuple(instruments),
        )

    def _parse_row(
        self,
        index: int,
        row: list[str],
        warnings: list[ImportWarning],
    ) -> _Fill | None:
        if len(row) < _MIN_COLUMNS:
            return self._warn(warnings, index, "row has too few columns")
        if not row[_COL_VENUE].strip():
            # Empty execution venue marks non-trade events (e.g. stock splits).
            return self._warn(warnings, index, "missing execution venue")

        try:
            quantity_signed = _parse_decimal_es(row[_COL_QUANTITY])
            if quantity_signed == 0:
                raise ValueError("zero quantity")
            currency, pence = _map_currency(row[_COL_PRICE_CURRENCY])
            price = _parse_decimal_es(row[_COL_PRICE])
            if pence:
                price = price / Decimal("100")
            fee = self._compute_fee(row, currency)
            return _Fill(
                date=datetime.strptime(row[_COL_DATE].strip(), "%d-%m-%Y").date(),
                type=TransactionType.BUY if quantity_signed > 0 else TransactionType.SELL,
                isin=row[_COL_ISIN].strip(),
                name=row[_COL_NAME].strip(),
                exchange=row[_COL_EXCHANGE].strip(),
                currency=currency,
                quantity=abs(quantity_signed),
                price=price,
                fee=fee,
                order_id=_last_non_empty(row),
            )
        except (ValueError, InvalidOperation) as error:
            return self._warn(warnings, index, str(error))

    def _compute_fee(self, row: list[str], currency: Currency) -> Decimal:
        fee_eur = _abs_decimal_es(row[_COL_AUTOFX_FEE]) + _abs_decimal_es(row[_COL_TRANSACTION_FEE])
        if currency == Currency.EUR or fee_eur == 0:
            return fee_eur
        rate = _parse_decimal_es(row[_COL_FX_RATE]) if row[_COL_FX_RATE].strip() else None
        # Commissions are billed in EUR; convert to the trade currency so the
        # fee stays consistent with the (trade-currency) price.
        return fee_eur * rate if rate else fee_eur

    def _build(
        self,
        fills: list[_Fill],
        warnings: list[ImportWarning],
    ) -> tuple[list[Transaction], list[Instrument]]:
        transactions: list[Transaction] = []
        instruments: dict[str, Instrument] = {}
        for group in self._group_partial_fills(fills):
            merged = self._merge(group)
            transaction = Transaction(
                date=merged.date,
                type=merged.type,
                symbol=merged.isin,
                currency=merged.currency,
                quantity=merged.quantity,
                price=merged.price,
                fee=merged.fee,
                broker=_BROKER_LABEL,
                raw_id=merged.order_id,
            )
            try:
                normalize_transactions([transaction])
            except TransactionValidationError as error:
                warnings.append(ImportWarning("invalid_row", WarningLevel.WARNING, str(error)))
                continue
            transactions.append(transaction)
            instruments.setdefault(
                merged.isin,
                Instrument(
                    symbol=merged.isin,
                    name=merged.name or None,
                    exchange=merged.exchange or None,
                    isin=merged.isin,
                ),
            )
        return transactions, list(instruments.values())

    @staticmethod
    def _group_partial_fills(fills: list[_Fill]) -> list[list[_Fill]]:
        groups: dict[tuple[str, str], list[_Fill]] = {}
        singles: list[list[_Fill]] = []
        for fill in fills:
            # Only fills that share a non-empty order id AND the same side are
            # combined; everything else stays a standalone transaction.
            if fill.order_id is None:
                singles.append([fill])
                continue
            groups.setdefault((fill.order_id, fill.type.value), []).append(fill)
        return list(groups.values()) + singles

    @staticmethod
    def _merge(group: list[_Fill]) -> _Fill:
        if len(group) == 1:
            return group[0]
        total_quantity = sum((fill.quantity for fill in group), Decimal("0"))
        weighted_price = (
            sum((fill.price * fill.quantity for fill in group), Decimal("0")) / total_quantity
        )
        head = group[0]
        return _Fill(
            date=min(fill.date for fill in group),
            type=head.type,
            isin=head.isin,
            name=head.name,
            exchange=head.exchange,
            currency=head.currency,
            quantity=total_quantity,
            price=weighted_price,
            fee=sum((fill.fee for fill in group), Decimal("0")),
            order_id=head.order_id,
        )

    @staticmethod
    def _warn(warnings: list[ImportWarning], index: int, reason: str) -> None:
        warnings.append(
            ImportWarning(
                code="invalid_row",
                level=WarningLevel.WARNING,
                message=f"Skipped row {index}: {reason}",
                affected_rows=(index,),
            )
        )
        return None


def _map_currency(raw: str) -> tuple[Currency, bool]:
    token = raw.strip().upper()
    if token in ("GBX", "GBP"):
        # GBX/pence are quoted in hundredths of a pound.
        return Currency.GBP, token == "GBX"
    return Currency(token), False


def _last_non_empty(row: list[str]) -> str | None:
    for cell in reversed(row):
        if cell.strip():
            return cell.strip()
    return None


def _parse_decimal_es(raw: str) -> Decimal:
    text = raw.strip()
    if not text:
        raise ValueError("empty number")
    # Spanish locale: '.' thousands separator, ',' decimal separator.
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    return Decimal(text)


def _abs_decimal_es(raw: str) -> Decimal:
    if not raw.strip():
        return Decimal("0")
    return abs(_parse_decimal_es(raw))
