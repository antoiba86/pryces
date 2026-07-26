"""(De)serialization for the versioned pryces export document.

The export document is an interchange contract, versioned independently of
the storage format in the JSON repository — the two coincide today, but each
must be free to evolve on its own (a round-trip test pins compatibility).
Transaction rows deliberately omit the storage-internal `id`; the repository
assigns a fresh one on insert.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from ..domain.portfolio.portfolio import ManualAsset
from ..domain.portfolio.transactions import Transaction, TransactionType
from ..domain.stocks import Currency

EXPORT_FORMAT = "pryces-export"
EXPORT_VERSION = 1


def build_export_document(portfolios: list[dict], exported_at: str) -> dict:
    return {
        "format": EXPORT_FORMAT,
        "version": EXPORT_VERSION,
        "exported_at": exported_at,
        "portfolios": portfolios,
    }


def transaction_to_dict(transaction: Transaction) -> dict:
    row: dict = {
        "date": transaction.date.isoformat(),
        "type": transaction.type.value,
        "symbol": transaction.symbol,
        "currency": transaction.currency.value,
        "fee": str(transaction.fee),
    }
    if transaction.quantity is not None:
        row["quantity"] = str(transaction.quantity)
    if transaction.price is not None:
        row["price"] = str(transaction.price)
    if transaction.amount is not None:
        row["amount"] = str(transaction.amount)
    if transaction.broker is not None:
        row["broker"] = transaction.broker
    if transaction.raw_id is not None:
        row["raw_id"] = transaction.raw_id
    return row


def transaction_from_dict(row: dict) -> Transaction:
    if not isinstance(row, dict):
        raise ValueError("transaction row must be an object")
    try:
        symbol = row["symbol"]
        if not isinstance(symbol, str) or not symbol.strip():
            raise ValueError("symbol must be a non-empty string")
        return Transaction(
            date=date.fromisoformat(row["date"]),
            type=TransactionType(row["type"]),
            symbol=symbol,
            currency=Currency(row["currency"]),
            quantity=_optional_decimal(row.get("quantity")),
            price=_optional_decimal(row.get("price")),
            amount=_optional_decimal(row.get("amount")),
            fee=_decimal_or_zero(row.get("fee")),
            broker=_optional_str(row.get("broker")),
            raw_id=_optional_str(row.get("raw_id")),
        )
    except KeyError as error:
        raise ValueError(f"missing field {error.args[0]!r}") from error
    except (TypeError, InvalidOperation) as error:
        raise ValueError(str(error)) from error


def manual_asset_to_dict(asset: ManualAsset) -> dict:
    return {
        "name": asset.name,
        "asset_type": asset.asset_type,
        "value_base": str(asset.value_base),
    }


def manual_asset_from_dict(row: dict) -> ManualAsset:
    if not isinstance(row, dict):
        raise ValueError("manual asset row must be an object")
    try:
        name = row["name"]
        if not isinstance(name, str) or not name.strip():
            raise ValueError("name must be a non-empty string")
        return ManualAsset(
            name=name,
            asset_type=str(row["asset_type"]),
            value_base=Decimal(row["value_base"]),
        )
    except KeyError as error:
        raise ValueError(f"missing field {error.args[0]!r}") from error
    except (TypeError, InvalidOperation) as error:
        raise ValueError(str(error)) from error


def _optional_decimal(value) -> Decimal | None:
    return Decimal(value) if value is not None else None


def _decimal_or_zero(value) -> Decimal:
    return Decimal(value) if value is not None else Decimal("0")


def _optional_str(value) -> str | None:
    return str(value) if value is not None else None
