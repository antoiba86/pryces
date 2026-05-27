from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum

from pryces.domain.stocks import Currency


class TransactionType(str, Enum):
    BUY = "buy"
    SELL = "sell"
    DIVIDEND = "dividend"
    FEE = "fee"


@dataclass(frozen=True, slots=True)
class Transaction:
    date: date
    type: TransactionType
    symbol: str
    currency: Currency
    quantity: Decimal | None = None
    price: Decimal | None = None
    amount: Decimal | None = None
    fee: Decimal = Decimal("0")
    broker: str | None = None
    raw_id: str | None = None


class WarningLevel(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class ImportWarning:
    code: str
    level: WarningLevel
    message: str
    affected_rows: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class ImportResult:
    transactions: tuple[Transaction, ...]
    warnings: tuple[ImportWarning, ...] = ()


class TransactionValidationError(ValueError):
    pass


def normalize_transactions(transactions: list[Transaction]) -> list[Transaction]:
    normalized: list[Transaction] = []
    for transaction in transactions:
        normalized.append(_normalize(transaction))
    return normalized


def _normalize(transaction: Transaction) -> Transaction:
    if transaction.fee < 0:
        raise TransactionValidationError(
            f"Fee must be non-negative for {transaction.symbol} on {transaction.date}"
        )

    if transaction.type in (TransactionType.BUY, TransactionType.SELL):
        return _normalize_trade(transaction)
    if transaction.type == TransactionType.DIVIDEND:
        return _normalize_dividend(transaction)
    return _normalize_fee(transaction)


def _normalize_trade(transaction: Transaction) -> Transaction:
    if transaction.quantity is None or transaction.price is None:
        raise TransactionValidationError(
            f"Trade requires quantity and price for {transaction.symbol} on {transaction.date}"
        )
    if transaction.quantity <= 0:
        raise TransactionValidationError(
            f"Quantity must be positive for {transaction.symbol} on {transaction.date}"
        )
    if transaction.price <= 0:
        raise TransactionValidationError(
            f"Price must be positive for {transaction.symbol} on {transaction.date}"
        )
    return transaction


def _normalize_dividend(transaction: Transaction) -> Transaction:
    if transaction.amount is None or transaction.amount <= 0:
        raise TransactionValidationError(
            f"Dividend requires a positive amount for {transaction.symbol} on {transaction.date}"
        )
    return transaction


def _normalize_fee(transaction: Transaction) -> Transaction:
    if transaction.amount is None or transaction.amount <= 0:
        raise TransactionValidationError(
            f"Standalone fee requires a positive amount for {transaction.symbol} on {transaction.date}"
        )
    return transaction
