from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import uuid4

from ...domain.portfolio.transactions import (
    Instrument,
    Transaction,
    TransactionType,
    normalize_transactions,
)
from ...domain.stocks import Currency
from ..interfaces import PortfolioRepository, SymbolResolver


@dataclass(frozen=True)
class AddTransactionRequest:
    portfolio_name: str
    date: date
    type: TransactionType
    symbol: str
    currency: Currency
    quantity: Decimal | None = None
    price: Decimal | None = None
    amount: Decimal | None = None
    fee: Decimal = Decimal("0")
    user_id: int = 1


@dataclass(frozen=True)
class UpdateTransactionRequest:
    portfolio_name: str
    transaction_id: str
    date: date
    type: TransactionType
    symbol: str
    currency: Currency
    quantity: Decimal | None = None
    price: Decimal | None = None
    amount: Decimal | None = None
    fee: Decimal = Decimal("0")
    user_id: int = 1


class AddTransaction:
    """Hand-adds a single, broker-less transaction to a portfolio.

    Manual entries never carry a broker, so they're always allowed and never
    lock the portfolio to a broker (only file imports do that). The typed symbol
    is resolved to a Yahoo ticker, falling back to as-typed when unresolved.
    """

    def __init__(self, repository: PortfolioRepository, resolver: SymbolResolver) -> None:
        self._repository = repository
        self._resolver = resolver

    def handle(self, request: AddTransactionRequest) -> str:
        # Raises PortfolioNotFound when the portfolio is missing.
        symbol = self._resolve(request.symbol, request.currency)
        transaction = normalize_transactions(
            [
                Transaction(
                    date=request.date,
                    type=request.type,
                    symbol=symbol,
                    currency=request.currency,
                    quantity=request.quantity,
                    price=request.price,
                    amount=request.amount,
                    fee=request.fee,
                    broker=None,
                    raw_id="manual-" + uuid4().hex,
                )
            ]
        )[0]
        return self._repository.add_transaction(
            request.portfolio_name, transaction, request.user_id
        )

    def _resolve(self, symbol: str, currency: Currency) -> str:
        ticker = self._resolver.resolve(Instrument(symbol=symbol, name=symbol, currency=currency))
        return ticker or symbol


class UpdateTransaction:
    """Edits the fields of an existing transaction by id.

    The stored row's broker and raw_id are identity/dedup keys and are preserved
    by the repository; the symbol is taken as given (the caller pre-fills the
    current one) so editing an imported row's quantity never re-resolves it.
    """

    def __init__(self, repository: PortfolioRepository) -> None:
        self._repository = repository

    def handle(self, request: UpdateTransactionRequest) -> None:
        # Raises PortfolioNotFound / TransactionNotFound.
        transaction = normalize_transactions(
            [
                Transaction(
                    date=request.date,
                    type=request.type,
                    symbol=request.symbol,
                    currency=request.currency,
                    quantity=request.quantity,
                    price=request.price,
                    amount=request.amount,
                    fee=request.fee,
                )
            ]
        )[0]
        self._repository.update_transaction(
            request.portfolio_name, request.transaction_id, transaction, request.user_id
        )


class DeleteTransaction:
    def __init__(self, repository: PortfolioRepository) -> None:
        self._repository = repository

    def handle(self, portfolio_name: str, transaction_id: str, user_id: int = 1) -> None:
        # Raises PortfolioNotFound / TransactionNotFound.
        self._repository.delete_transaction(portfolio_name, transaction_id, user_id)
