from __future__ import annotations

from collections.abc import Callable
from datetime import date
from decimal import Decimal

from .transactions import Transaction, TransactionType
from ..stocks import Currency

# Converts a native-currency amount on a given date into the portfolio base
# currency (the caller supplies date-accurate FX rates).
ConvertFn = Callable[[date, Currency, Decimal], Decimal]

_DAYS_PER_YEAR = Decimal("365")
_XIRR_MAX_ITERATIONS = 100
_XIRR_TOLERANCE = Decimal("0.0000001")
_XIRR_MIN_RATE = Decimal("-0.999999")


class XirrConvergenceError(RuntimeError):
    pass


def total_return(
    value: Decimal,
    cost: Decimal,
    dividends: Decimal = Decimal("0"),
    fees: Decimal = Decimal("0"),
) -> Decimal:
    if cost <= 0:
        return Decimal("0")
    return (value + dividends - cost - fees) / cost * 100


def build_xirr_cashflows(
    transactions: list[Transaction],
    convert: ConvertFn,
    terminal_value: Decimal,
    terminal_date: date,
) -> list[tuple[date, Decimal]]:
    """Build a base-currency cashflow stream for XIRR from a transaction log.

    Buys and standalone fees are outflows (negative); sells and dividends are
    inflows (positive). Each native amount is converted to the base currency at
    its own transaction date via `convert`. The current portfolio value is
    appended as a terminal inflow on `terminal_date`.
    """
    cashflows = [
        (transaction.date, convert(transaction.date, transaction.currency, amount))
        for transaction in sorted(transactions, key=lambda t: t.date)
        for amount in (_signed_native_amount(transaction),)
    ]
    if terminal_value != 0:
        cashflows.append((terminal_date, terminal_value))
    return cashflows


def _signed_native_amount(transaction: Transaction) -> Decimal:
    if transaction.type == TransactionType.BUY:
        return -(transaction.quantity * transaction.price + transaction.fee)
    if transaction.type == TransactionType.SELL:
        return transaction.quantity * transaction.price - transaction.fee
    if transaction.type == TransactionType.DIVIDEND:
        return transaction.amount
    return -transaction.amount


def xirr(
    cashflows: list[tuple[date, Decimal]],
    guess: Decimal = Decimal("0.1"),
) -> Decimal:
    if len(cashflows) < 2:
        raise ValueError("XIRR requires at least two cashflows")
    if not any(cf < 0 for _, cf in cashflows) or not any(cf > 0 for _, cf in cashflows):
        raise ValueError("XIRR requires both positive and negative cashflows")

    anchor = min(d for d, _ in cashflows)
    offsets = [Decimal((d - anchor).days) / _DAYS_PER_YEAR for d, _ in cashflows]
    amounts = [cf for _, cf in cashflows]

    rate = guess
    for _ in range(_XIRR_MAX_ITERATIONS):
        npv, dnpv = _npv_and_derivative(rate, amounts, offsets)
        if dnpv == 0:
            break
        new_rate = rate - npv / dnpv
        if new_rate <= _XIRR_MIN_RATE:
            new_rate = (rate + _XIRR_MIN_RATE) / 2
        if abs(new_rate - rate) < _XIRR_TOLERANCE:
            return new_rate * 100
        rate = new_rate
    raise XirrConvergenceError("XIRR did not converge")


def twr(sub_periods: list[tuple[Decimal, Decimal]]) -> Decimal:
    """Chain sub-period returns. Each tuple is (start_value, end_value_before_cashflow).

    Returns the total time-weighted return as a percentage. The caller is
    responsible for chopping the timeline at each external cashflow event.
    """
    if not sub_periods:
        return Decimal("0")

    growth = Decimal("1")
    for start, end in sub_periods:
        if start <= 0:
            raise ValueError("Sub-period start value must be positive")
        growth *= end / start
    return (growth - 1) * 100


def _npv_and_derivative(
    rate: Decimal, amounts: list[Decimal], offsets: list[Decimal]
) -> tuple[Decimal, Decimal]:
    one_plus_rate = Decimal("1") + rate
    if one_plus_rate <= 0:
        return Decimal("0"), Decimal("0")
    npv = Decimal("0")
    dnpv = Decimal("0")
    for amount, offset in zip(amounts, offsets):
        discount = _pow(one_plus_rate, offset)
        npv += amount / discount
        dnpv -= amount * offset / (discount * one_plus_rate)
    return npv, dnpv


def _pow(base: Decimal, exponent: Decimal) -> Decimal:
    # Decimal.__pow__ only supports integer exponents in pure-Decimal context.
    # For fractional exponents in NPV discounting we route through float and
    # bring the result back into Decimal — XIRR tolerance is well above float
    # precision so this is the right trade-off.
    return Decimal(str(float(base) ** float(exponent)))
