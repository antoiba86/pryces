from __future__ import annotations

import csv
import io
from datetime import date
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

_BROKER_ID = "trade_republic"
_BROKER_LABEL = "Trade Republic"

# Only TRADING rows are portfolio movements; CASH rows (transfers, interest, card
# spending, ...) are out of scope and skipped.
_TRADING_CATEGORY = "TRADING"

# Header field names unique to a Trade Republic transaction export. None of the
# other CSV importers (DEGIRO, IBKR) use these, so the signature is unambiguous.
_HEADER_SIGNATURE = ("category", "asset_class", "transaction_id")

_TYPE_MAP = {"BUY": TransactionType.BUY, "SELL": TransactionType.SELL}


class TradeRepublicCsvImporter(TransactionImporter):
    """Imports a Trade Republic transaction export (`category == TRADING` only).

    Trade Republic settles buys/sells (often fractional savings-plan executions)
    in the account currency, reporting `shares`, a per-share `price`, and a
    signed `amount`, all with plain `.`-decimals and ISO dates. Each row carries
    its own `transaction_id`, so executions are distinct transactions — no
    partial-fill merging is needed. Any `fee` and `tax` on a row are summed into
    the transaction's cost.

    Instruments are emitted with `symbol = ISIN`; a downstream SymbolResolver
    maps them to Yahoo tickers. Non-TRADING rows (cash transfers, interest, card
    payments) are ignored.
    """

    @property
    def broker_id(self) -> str:
        return _BROKER_ID

    def can_parse(self, content: bytes) -> bool:
        text = decode_csv(content)
        header = text.lstrip().splitlines()[0] if text.strip() else ""
        return all(token in header for token in _HEADER_SIGNATURE)

    def parse(self, content: bytes) -> ImportResult:
        text = decode_csv(content)
        reader = csv.DictReader(io.StringIO(text))
        if reader.fieldnames is None or not set(_HEADER_SIGNATURE).issubset(reader.fieldnames):
            raise UnrecognizedImportFormat(_BROKER_ID)

        warnings: list[ImportWarning] = []
        transactions: list[Transaction] = []
        instruments: dict[str, Instrument] = {}
        for index, row in enumerate(reader, start=1):
            if (row.get("category") or "").strip().upper() != _TRADING_CATEGORY:
                continue
            parsed = self._parse_row(index, row, warnings)
            if parsed is None:
                continue
            transaction, instrument = parsed
            transactions.append(transaction)
            instruments.setdefault(instrument.symbol, instrument)

        return ImportResult(
            transactions=tuple(transactions),
            warnings=tuple(warnings),
            instruments=tuple(instruments.values()),
        )

    def _parse_row(
        self,
        index: int,
        row: dict[str, str],
        warnings: list[ImportWarning],
    ) -> tuple[Transaction, Instrument] | None:
        transaction_type = _TYPE_MAP.get((row.get("type") or "").strip().upper())
        if transaction_type is None:
            return self._warn(warnings, index, f"unsupported trade type {row.get('type')!r}")

        isin = (row.get("symbol") or "").strip()
        if not isin:
            return self._warn(warnings, index, "missing symbol/ISIN")

        try:
            currency = Currency((row.get("currency") or "").strip().upper())
            quantity = _parse_decimal(row.get("shares"))
            price = _parse_decimal(row.get("price"))
            # Both fee and tax reduce the trade's economics, so they're summed
            # into the single cost field the domain models.
            fee = _abs_decimal(row.get("fee")) + _abs_decimal(row.get("tax"))
            transaction = Transaction(
                date=date.fromisoformat((row.get("date") or "").strip()),
                type=transaction_type,
                symbol=isin,
                currency=currency,
                quantity=quantity,
                price=price,
                fee=fee,
                broker=_BROKER_LABEL,
                raw_id=(row.get("transaction_id") or "").strip() or None,
            )
            normalize_transactions([transaction])
        except (ValueError, InvalidOperation, TransactionValidationError) as error:
            return self._warn(warnings, index, str(error))

        instrument = Instrument(
            symbol=isin,
            name=(row.get("name") or "").strip() or None,
            isin=isin,
            currency=currency,
        )
        return transaction, instrument

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


def _parse_decimal(raw: str | None) -> Decimal:
    text = (raw or "").strip()
    if not text:
        raise ValueError("empty number")
    return Decimal(text)


def _abs_decimal(raw: str | None) -> Decimal:
    text = (raw or "").strip()
    if not text:
        return Decimal("0")
    return abs(Decimal(text))
