from datetime import date
from decimal import Decimal

import pytest

from pryces.domain.portfolio.returns import (
    XirrConvergenceError,
    build_xirr_cashflows,
    total_return,
    twr,
    xirr,
)
from pryces.domain.portfolio.transactions import Transaction, TransactionType
from pryces.domain.stocks import Currency


class TestTotalReturn:
    def test_simple_gain(self):
        result = total_return(
            value=Decimal("110"),
            cost=Decimal("100"),
        )
        assert result == Decimal("10")

    def test_includes_dividends(self):
        # (120 + 5 - 100 - 0) / 100 * 100 = 25
        result = total_return(
            value=Decimal("120"),
            cost=Decimal("100"),
            dividends=Decimal("5"),
        )
        assert result == Decimal("25")

    def test_fees_reduce_return(self):
        # (120 + 5 - 100 - 2) / 100 * 100 = 23
        result = total_return(
            value=Decimal("120"),
            cost=Decimal("100"),
            dividends=Decimal("5"),
            fees=Decimal("2"),
        )
        assert result == Decimal("23")

    def test_loss(self):
        result = total_return(value=Decimal("80"), cost=Decimal("100"))
        assert result == Decimal("-20")

    def test_zero_cost_returns_zero(self):
        result = total_return(value=Decimal("100"), cost=Decimal("0"))
        assert result == Decimal("0")


class TestXirr:
    def test_one_year_doubling_yields_100_pct(self):
        # 365-day span (non-leap year) doubling = exactly 100% annualized.
        # Excel =XIRR({-1000, 2000}, {1/1/2025, 1/1/2026}) → 100.00%
        result = xirr(
            [
                (date(2025, 1, 1), Decimal("-1000")),
                (date(2026, 1, 1), Decimal("2000")),
            ]
        )
        assert result.quantize(Decimal("0.01")) == Decimal("100.00")

    def test_one_year_10_pct_gain(self):
        # Excel =XIRR({-1000, 1100}, {1/1/2025, 1/1/2026}) → 10.00%
        result = xirr(
            [
                (date(2025, 1, 1), Decimal("-1000")),
                (date(2026, 1, 1), Decimal("1100")),
            ]
        )
        assert result.quantize(Decimal("0.01")) == Decimal("10.00")

    def test_six_month_5_pct_gain_annualizes(self):
        # 181 days. 1.05^(365/181) - 1 ≈ 10.34% annualized.
        result = xirr(
            [
                (date(2025, 1, 1), Decimal("-1000")),
                (date(2025, 7, 1), Decimal("1050")),
            ]
        )
        assert result.quantize(Decimal("0.01")) == Decimal("10.34")

    def test_loss(self):
        # Excel =XIRR({-1000, 900}, {1/1/2025, 1/1/2026}) → -10.00%
        result = xirr(
            [
                (date(2025, 1, 1), Decimal("-1000")),
                (date(2026, 1, 1), Decimal("900")),
            ]
        )
        assert result.quantize(Decimal("0.01")) == Decimal("-10.00")

    def test_multiple_cashflows(self):
        # Verified by hand: NPV(-1000, -500@0.5y, +1700@1y) = 0 at r ≈ 16.09%.
        result = xirr(
            [
                (date(2025, 1, 1), Decimal("-1000")),
                (date(2025, 7, 1), Decimal("-500")),
                (date(2026, 1, 1), Decimal("1700")),
            ]
        )
        assert result.quantize(Decimal("0.01")) == Decimal("16.09")

    def test_requires_at_least_two_cashflows(self):
        with pytest.raises(ValueError):
            xirr([(date(2024, 1, 1), Decimal("-1000"))])

    def test_requires_both_signs(self):
        with pytest.raises(ValueError):
            xirr(
                [
                    (date(2024, 1, 1), Decimal("-1000")),
                    (date(2025, 1, 1), Decimal("-2000")),
                ]
            )

    def test_cashflows_in_any_order_yield_same_rate(self):
        forward = xirr(
            [
                (date(2024, 1, 1), Decimal("-1000")),
                (date(2025, 1, 1), Decimal("1100")),
            ]
        )
        backward = xirr(
            [
                (date(2025, 1, 1), Decimal("1100")),
                (date(2024, 1, 1), Decimal("-1000")),
            ]
        )
        assert forward.quantize(Decimal("0.0001")) == backward.quantize(Decimal("0.0001"))


class TestTwr:
    def test_single_period_10_pct_gain(self):
        # 100 → 110 = +10%
        assert twr([(Decimal("100"), Decimal("110"))]) == Decimal("10")

    def test_chained_periods_compound(self):
        # 1.10 * 1.10 - 1 = 0.21 = +21%
        result = twr(
            [
                (Decimal("100"), Decimal("110")),
                (Decimal("110"), Decimal("121")),
            ]
        )
        assert result.quantize(Decimal("0.01")) == Decimal("21.00")

    def test_chained_gain_then_loss(self):
        # 1.20 * 0.90 - 1 = 0.08 = +8%
        result = twr(
            [
                (Decimal("100"), Decimal("120")),
                (Decimal("120"), Decimal("108")),
            ]
        )
        assert result.quantize(Decimal("0.01")) == Decimal("8.00")

    def test_strips_cashflow_effect(self):
        # Classic textbook case: Period 1 starts at 100, grows to 110 (+10%).
        # User then DEPOSITS 1000 (start of period 2 = 1110). Period 2 grows
        # to 1221 (+10%). TWR = 1.10 * 1.10 - 1 = 21% — the deposit does
        # not flatter the return even though the absolute gain is huge.
        result = twr(
            [
                (Decimal("100"), Decimal("110")),
                (Decimal("1110"), Decimal("1221")),
            ]
        )
        assert result.quantize(Decimal("0.01")) == Decimal("21.00")

    def test_empty_returns_zero(self):
        assert twr([]) == Decimal("0")

    def test_rejects_non_positive_start(self):
        with pytest.raises(ValueError):
            twr([(Decimal("0"), Decimal("10"))])


class TestBuildXirrCashflows:

    def _buy(self, when, currency=Currency.USD, qty="10", price="100", fee="5"):
        return Transaction(
            date=when,
            type=TransactionType.BUY,
            symbol="AAPL",
            currency=currency,
            quantity=Decimal(qty),
            price=Decimal(price),
            fee=Decimal(fee),
        )

    def _identity(self, on, currency, amount):
        return amount

    def test_buy_is_negative_including_fee(self):
        flows = build_xirr_cashflows(
            [self._buy(date(2024, 1, 1))], self._identity, Decimal("0"), date(2024, 6, 1)
        )

        assert flows == [(date(2024, 1, 1), Decimal("-1005"))]

    def test_sell_is_positive_net_of_fee(self):
        sell = Transaction(
            date=date(2024, 2, 1),
            type=TransactionType.SELL,
            symbol="AAPL",
            currency=Currency.USD,
            quantity=Decimal("10"),
            price=Decimal("120"),
            fee=Decimal("5"),
        )

        flows = build_xirr_cashflows([sell], self._identity, Decimal("0"), date(2024, 6, 1))

        assert flows == [(date(2024, 2, 1), Decimal("1195"))]

    def test_dividend_and_fee_signs(self):
        dividend = Transaction(
            date=date(2024, 3, 1),
            type=TransactionType.DIVIDEND,
            symbol="AAPL",
            currency=Currency.USD,
            amount=Decimal("12"),
        )
        standalone_fee = Transaction(
            date=date(2024, 3, 2),
            type=TransactionType.FEE,
            symbol="AAPL",
            currency=Currency.USD,
            amount=Decimal("3"),
        )

        flows = build_xirr_cashflows(
            [dividend, standalone_fee], self._identity, Decimal("0"), date(2024, 6, 1)
        )

        assert flows == [(date(2024, 3, 1), Decimal("12")), (date(2024, 3, 2), Decimal("-3"))]

    def test_appends_terminal_value(self):
        flows = build_xirr_cashflows(
            [self._buy(date(2024, 1, 1))], self._identity, Decimal("1200"), date(2024, 6, 1)
        )

        assert flows[-1] == (date(2024, 6, 1), Decimal("1200"))

    def test_skips_terminal_when_zero(self):
        flows = build_xirr_cashflows(
            [self._buy(date(2024, 1, 1))], self._identity, Decimal("0"), date(2024, 6, 1)
        )

        assert len(flows) == 1

    def test_applies_convert_with_date_and_currency(self):
        flows = build_xirr_cashflows(
            [self._buy(date(2024, 1, 1), currency=Currency.USD)],
            lambda on, currency, amount: amount * Decimal("2"),
            Decimal("0"),
            date(2024, 6, 1),
        )

        assert flows == [(date(2024, 1, 1), Decimal("-2010"))]

    def test_round_trip_through_xirr(self):
        # Buy 1000 out, value 1100 a year later -> ~10% money-weighted return.
        buy = self._buy(date(2024, 1, 1), qty="10", price="100", fee="0")
        flows = build_xirr_cashflows([buy], self._identity, Decimal("1100"), date(2025, 1, 1))

        assert abs(xirr(flows) - Decimal("10")) < Decimal("0.5")
