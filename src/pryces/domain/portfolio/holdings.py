from __future__ import annotations

from decimal import Decimal

from pryces.domain.portfolio.transactions import Transaction, TransactionType
from pryces.domain.stocks import Currency

HoldingKey = tuple[str, str | None]


class OversoldError(ValueError):
    pass


class CurrencyMismatchError(ValueError):
    pass


class Holding:
    __slots__ = (
        "_symbol",
        "_broker",
        "_currency",
        "_quantity",
        "_cost_total",
        "_realized_pnl",
        "_dividends",
        "_fees",
    )

    def __init__(self, symbol: str, currency: Currency, broker: str | None = None) -> None:
        self._symbol = symbol
        self._broker = broker
        self._currency = currency
        self._quantity = Decimal("0")
        self._cost_total = Decimal("0")
        self._realized_pnl = Decimal("0")
        self._dividends = Decimal("0")
        self._fees = Decimal("0")

    @property
    def symbol(self) -> str:
        return self._symbol

    @property
    def broker(self) -> str | None:
        return self._broker

    @property
    def currency(self) -> Currency:
        return self._currency

    @property
    def quantity(self) -> Decimal:
        return self._quantity

    @property
    def cost_total(self) -> Decimal:
        return self._cost_total

    @property
    def realized_pnl(self) -> Decimal:
        return self._realized_pnl

    @property
    def dividends(self) -> Decimal:
        return self._dividends

    @property
    def fees(self) -> Decimal:
        return self._fees

    @property
    def avg_cost(self) -> Decimal:
        if self._quantity <= 0:
            return Decimal("0")
        return self._cost_total / self._quantity

    def apply_buy(self, quantity: Decimal, price: Decimal, fee: Decimal) -> None:
        self._quantity += quantity
        self._cost_total += quantity * price + fee
        self._fees += fee

    def apply_sell(self, quantity: Decimal, price: Decimal, fee: Decimal) -> None:
        if quantity > self._quantity:
            raise OversoldError(f"Selling {quantity} {self._symbol} but only {self._quantity} held")
        basis_removed = self.avg_cost * quantity
        proceeds = quantity * price - fee
        self._realized_pnl += proceeds - basis_removed
        self._quantity -= quantity
        self._cost_total -= basis_removed
        self._fees += fee

    def apply_dividend(self, amount: Decimal) -> None:
        self._dividends += amount

    def apply_fee(self, amount: Decimal) -> None:
        self._fees += amount


def replay(transactions: list[Transaction]) -> dict[HoldingKey, Holding]:
    """Replay a transaction log into per-(symbol, broker) holdings.

    Keying by broker preserves broker-accurate cost basis when the same
    symbol is held at multiple platforms. Use aggregate_by_symbol() to
    collapse into a unified per-symbol view.
    """
    holdings: dict[HoldingKey, Holding] = {}
    for transaction in sorted(transactions, key=lambda t: t.date):
        key: HoldingKey = (transaction.symbol, transaction.broker)
        holding = holdings.setdefault(
            key, Holding(transaction.symbol, transaction.currency, transaction.broker)
        )
        _apply(holding, transaction)
    return holdings


def active_holdings(holdings: dict[HoldingKey, Holding]) -> dict[HoldingKey, Holding]:
    return {key: holding for key, holding in holdings.items() if holding.quantity > 0}


def aggregate_by_symbol(holdings: dict[HoldingKey, Holding]) -> dict[str, Holding]:
    """Collapse broker-keyed holdings into a single per-symbol view.

    Cost basis is summed in native currency, so the avg_cost on the result
    is the weighted average across brokers. The broker field on the
    aggregated Holding is None, signalling "all brokers".
    """
    aggregated: dict[str, Holding] = {}
    for (symbol, _broker), holding in holdings.items():
        existing = aggregated.get(symbol)
        if existing is None:
            unified = Holding(symbol, holding.currency, broker=None)
            _absorb(unified, holding)
            aggregated[symbol] = unified
            continue
        if existing.currency != holding.currency:
            raise CurrencyMismatchError(
                f"Cannot aggregate {symbol}: holdings in {existing.currency} and {holding.currency}"
            )
        _absorb(existing, holding)
    return aggregated


def _absorb(target: Holding, source: Holding) -> None:
    target._quantity += source.quantity
    target._cost_total += source.cost_total
    target._realized_pnl += source.realized_pnl
    target._dividends += source.dividends
    target._fees += source.fees


def _apply(holding: Holding, transaction: Transaction) -> None:
    if transaction.type == TransactionType.BUY:
        assert transaction.quantity is not None and transaction.price is not None
        holding.apply_buy(transaction.quantity, transaction.price, transaction.fee)
    elif transaction.type == TransactionType.SELL:
        assert transaction.quantity is not None and transaction.price is not None
        holding.apply_sell(transaction.quantity, transaction.price, transaction.fee)
    elif transaction.type == TransactionType.DIVIDEND:
        assert transaction.amount is not None
        holding.apply_dividend(transaction.amount)
    elif transaction.type == TransactionType.FEE:
        assert transaction.amount is not None
        holding.apply_fee(transaction.amount)
