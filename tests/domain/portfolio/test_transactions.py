from datetime import date
from decimal import Decimal

import pytest

from pryces.domain.portfolio.transactions import (
    Transaction,
    TransactionType,
    TransactionValidationError,
    normalize_transactions,
)
from pryces.domain.stocks import Currency


def _buy(**overrides) -> Transaction:
    defaults = dict(
        date=date(2024, 1, 10),
        type=TransactionType.BUY,
        symbol="AAPL",
        currency=Currency.USD,
        quantity=Decimal("5"),
        price=Decimal("185.00"),
        fee=Decimal("1"),
    )
    defaults.update(overrides)
    return Transaction(**defaults)


def _dividend(**overrides) -> Transaction:
    defaults = dict(
        date=date(2024, 2, 15),
        type=TransactionType.DIVIDEND,
        symbol="AAPL",
        currency=Currency.USD,
        amount=Decimal("1.20"),
    )
    defaults.update(overrides)
    return Transaction(**defaults)


class TestNormalizeTrades:
    def test_passes_valid_buy(self):
        result = normalize_transactions([_buy()])
        assert result[0].quantity == Decimal("5")

    def test_rejects_missing_quantity(self):
        with pytest.raises(TransactionValidationError):
            normalize_transactions([_buy(quantity=None)])

    def test_rejects_missing_price(self):
        with pytest.raises(TransactionValidationError):
            normalize_transactions([_buy(price=None)])

    def test_rejects_zero_quantity(self):
        with pytest.raises(TransactionValidationError):
            normalize_transactions([_buy(quantity=Decimal("0"))])

    def test_rejects_negative_quantity(self):
        with pytest.raises(TransactionValidationError):
            normalize_transactions([_buy(quantity=Decimal("-1"))])

    def test_rejects_zero_price(self):
        with pytest.raises(TransactionValidationError):
            normalize_transactions([_buy(price=Decimal("0"))])

    def test_rejects_negative_fee(self):
        with pytest.raises(TransactionValidationError):
            normalize_transactions([_buy(fee=Decimal("-0.5"))])

    def test_passes_valid_sell(self):
        sell = _buy(type=TransactionType.SELL)
        result = normalize_transactions([sell])
        assert result[0].type == TransactionType.SELL


class TestNormalizeDividends:
    def test_passes_valid_dividend(self):
        result = normalize_transactions([_dividend()])
        assert result[0].amount == Decimal("1.20")

    def test_rejects_missing_amount(self):
        with pytest.raises(TransactionValidationError):
            normalize_transactions([_dividend(amount=None)])

    def test_rejects_zero_amount(self):
        with pytest.raises(TransactionValidationError):
            normalize_transactions([_dividend(amount=Decimal("0"))])


class TestTransactionDefaults:
    def test_fee_defaults_to_zero(self):
        txn = Transaction(
            date=date(2024, 1, 1),
            type=TransactionType.BUY,
            symbol="AAPL",
            currency=Currency.USD,
            quantity=Decimal("1"),
            price=Decimal("100"),
        )
        assert txn.fee == Decimal("0")

    def test_optional_fields_default_to_none(self):
        txn = Transaction(
            date=date(2024, 1, 1),
            type=TransactionType.BUY,
            symbol="AAPL",
            currency=Currency.USD,
            quantity=Decimal("1"),
            price=Decimal("100"),
        )
        assert txn.broker is None
        assert txn.raw_id is None
