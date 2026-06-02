from datetime import date
from decimal import Decimal

import pytest

from pryces.domain.portfolio.holdings import (
    CurrencyMismatchError,
    OversoldError,
    active_holdings,
    aggregate_by_symbol,
    replay,
)
from pryces.domain.portfolio.transactions import Transaction, TransactionType
from pryces.domain.stocks import Currency


def _buy(
    symbol="AAPL",
    quantity="10",
    price="100",
    fee="1",
    on=date(2024, 1, 10),
    broker=None,
    currency=Currency.USD,
) -> Transaction:
    return Transaction(
        date=on,
        type=TransactionType.BUY,
        symbol=symbol,
        currency=currency,
        quantity=Decimal(quantity),
        price=Decimal(price),
        fee=Decimal(fee),
        broker=broker,
    )


def _sell(
    symbol="AAPL",
    quantity="5",
    price="150",
    fee="1",
    on=date(2024, 6, 10),
    broker=None,
) -> Transaction:
    return Transaction(
        date=on,
        type=TransactionType.SELL,
        symbol=symbol,
        currency=Currency.USD,
        quantity=Decimal(quantity),
        price=Decimal(price),
        fee=Decimal(fee),
        broker=broker,
    )


def _dividend(symbol="AAPL", amount="2.40", on=date(2024, 3, 1), broker=None) -> Transaction:
    return Transaction(
        date=on,
        type=TransactionType.DIVIDEND,
        symbol=symbol,
        currency=Currency.USD,
        amount=Decimal(amount),
        broker=broker,
    )


class TestReplaySingleBuy:
    def test_quantity_equals_buy_quantity(self):
        holdings = replay([_buy(quantity="10", price="100", fee="1")])
        assert holdings[("AAPL", None)].quantity == Decimal("10")

    def test_cost_total_includes_fee(self):
        holdings = replay([_buy(quantity="10", price="100", fee="1")])
        assert holdings[("AAPL", None)].cost_total == Decimal("1001")

    def test_avg_cost_includes_fee(self):
        holdings = replay([_buy(quantity="10", price="100", fee="1")])
        assert holdings[("AAPL", None)].avg_cost == Decimal("100.1")

    def test_realized_pnl_starts_zero(self):
        holdings = replay([_buy()])
        assert holdings[("AAPL", None)].realized_pnl == Decimal("0")


class TestReplayMultipleBuys:
    def test_quantities_sum(self):
        holdings = replay(
            [
                _buy(quantity="10", price="100", fee="0", on=date(2024, 1, 10)),
                _buy(quantity="5", price="200", fee="0", on=date(2024, 2, 10)),
            ]
        )
        assert holdings[("AAPL", None)].quantity == Decimal("15")

    def test_avg_cost_is_weighted(self):
        # 10 @ 100 + 5 @ 200 = 1000 + 1000 = 2000 over 15 = 133.333...
        holdings = replay(
            [
                _buy(quantity="10", price="100", fee="0", on=date(2024, 1, 10)),
                _buy(quantity="5", price="200", fee="0", on=date(2024, 2, 10)),
            ]
        )
        avg = holdings[("AAPL", None)].avg_cost
        assert avg.quantize(Decimal("0.0001")) == Decimal("133.3333")


class TestReplaySell:
    def test_sell_reduces_quantity(self):
        holdings = replay(
            [
                _buy(quantity="10", price="100", fee="0", on=date(2024, 1, 10)),
                _sell(quantity="3", price="150", fee="0", on=date(2024, 6, 10)),
            ]
        )
        assert holdings[("AAPL", None)].quantity == Decimal("7")

    def test_sell_realizes_profit(self):
        # Bought 10 @ 100, sold 3 @ 150: realized = 3 * (150 - 100) = 150
        holdings = replay(
            [
                _buy(quantity="10", price="100", fee="0", on=date(2024, 1, 10)),
                _sell(quantity="3", price="150", fee="0", on=date(2024, 6, 10)),
            ]
        )
        assert holdings[("AAPL", None)].realized_pnl == Decimal("150")

    def test_sell_realizes_loss(self):
        holdings = replay(
            [
                _buy(quantity="10", price="100", fee="0"),
                _sell(quantity="3", price="80", fee="0"),
            ]
        )
        assert holdings[("AAPL", None)].realized_pnl == Decimal("-60")

    def test_sell_fee_reduces_proceeds(self):
        # 3 @ 150 - 5 fee = 445, basis 300 → realized 145
        holdings = replay(
            [
                _buy(quantity="10", price="100", fee="0"),
                _sell(quantity="3", price="150", fee="5"),
            ]
        )
        assert holdings[("AAPL", None)].realized_pnl == Decimal("145")

    def test_cost_total_reduces_by_basis_removed(self):
        holdings = replay(
            [
                _buy(quantity="10", price="100", fee="0"),
                _sell(quantity="3", price="150", fee="0"),
            ]
        )
        # 1000 - 300 = 700
        assert holdings[("AAPL", None)].cost_total == Decimal("700")

    def test_oversold_raises(self):
        with pytest.raises(OversoldError):
            replay(
                [
                    _buy(quantity="2", price="100", fee="0"),
                    _sell(quantity="3", price="150", fee="0"),
                ]
            )


class TestReplayDividends:
    def test_dividend_accumulates(self):
        holdings = replay(
            [
                _buy(),
                _dividend(amount="2.40"),
                _dividend(amount="2.50", on=date(2024, 6, 1)),
            ]
        )
        assert holdings[("AAPL", None)].dividends == Decimal("4.90")

    def test_dividend_does_not_affect_quantity(self):
        holdings = replay([_buy(quantity="10"), _dividend(amount="2.40")])
        assert holdings[("AAPL", None)].quantity == Decimal("10")


class TestReplayChronologicalOrder:
    def test_sells_after_buys_even_if_unordered(self):
        # Sell listed first but dated later — must be applied after.
        holdings = replay(
            [
                _sell(quantity="3", price="150", on=date(2024, 6, 10)),
                _buy(quantity="10", price="100", on=date(2024, 1, 10)),
            ]
        )
        assert holdings[("AAPL", None)].quantity == Decimal("7")

    def test_sell_before_buy_raises_oversold(self):
        with pytest.raises(OversoldError):
            replay(
                [
                    _sell(quantity="3", price="150", on=date(2024, 1, 5)),
                    _buy(quantity="10", price="100", on=date(2024, 1, 10)),
                ]
            )


class TestActiveHoldings:
    def test_excludes_fully_sold_positions(self):
        holdings = replay(
            [
                _buy(quantity="5"),
                _sell(quantity="5", price="100", fee="0"),
            ]
        )
        assert ("AAPL", None) not in active_holdings(holdings)

    def test_includes_partially_sold_positions(self):
        holdings = replay(
            [
                _buy(quantity="5"),
                _sell(quantity="3", price="100", fee="0"),
            ]
        )
        active = active_holdings(holdings)
        assert active[("AAPL", None)].quantity == Decimal("2")


class TestMultipleSymbols:
    def test_holdings_are_keyed_by_symbol(self):
        holdings = replay(
            [
                _buy(symbol="AAPL", quantity="5"),
                _buy(symbol="MSFT", quantity="10"),
            ]
        )
        assert set(holdings.keys()) == {("AAPL", None), ("MSFT", None)}
        assert holdings[("AAPL", None)].quantity == Decimal("5")
        assert holdings[("MSFT", None)].quantity == Decimal("10")


class TestBrokerKeying:
    def test_same_symbol_different_brokers_are_separate(self):
        holdings = replay(
            [
                _buy(symbol="AAPL", quantity="10", price="100", broker="IBKR"),
                _buy(symbol="AAPL", quantity="5", price="200", broker="DEGIRO"),
            ]
        )
        assert set(holdings.keys()) == {("AAPL", "IBKR"), ("AAPL", "DEGIRO")}
        assert holdings[("AAPL", "IBKR")].quantity == Decimal("10")
        assert holdings[("AAPL", "DEGIRO")].quantity == Decimal("5")

    def test_per_broker_cost_basis_is_independent(self):
        # If they merged, avg would be (10*100 + 5*200) / 15 = 133.33.
        # Kept separate, IBKR avg = 100, DEGIRO avg = 200.
        holdings = replay(
            [
                _buy(symbol="AAPL", quantity="10", price="100", fee="0", broker="IBKR"),
                _buy(symbol="AAPL", quantity="5", price="200", fee="0", broker="DEGIRO"),
            ]
        )
        assert holdings[("AAPL", "IBKR")].avg_cost == Decimal("100")
        assert holdings[("AAPL", "DEGIRO")].avg_cost == Decimal("200")

    def test_sell_at_one_broker_does_not_affect_other(self):
        holdings = replay(
            [
                _buy(symbol="AAPL", quantity="10", broker="IBKR"),
                _buy(symbol="AAPL", quantity="10", broker="DEGIRO"),
                _sell(symbol="AAPL", quantity="5", price="150", broker="IBKR"),
            ]
        )
        assert holdings[("AAPL", "IBKR")].quantity == Decimal("5")
        assert holdings[("AAPL", "DEGIRO")].quantity == Decimal("10")

    def test_oversell_against_one_broker_does_not_borrow_from_another(self):
        # IBKR has 2, DEGIRO has 10 — selling 5 at IBKR must raise.
        with pytest.raises(OversoldError):
            replay(
                [
                    _buy(symbol="AAPL", quantity="2", broker="IBKR"),
                    _buy(symbol="AAPL", quantity="10", broker="DEGIRO"),
                    _sell(symbol="AAPL", quantity="5", price="100", broker="IBKR"),
                ]
            )

    def test_holding_carries_broker(self):
        holdings = replay([_buy(symbol="AAPL", broker="IBKR")])
        assert holdings[("AAPL", "IBKR")].broker == "IBKR"


class TestAggregateBySymbol:
    def test_collapses_per_broker_into_unified(self):
        holdings = replay(
            [
                _buy(symbol="AAPL", quantity="10", price="100", fee="0", broker="IBKR"),
                _buy(symbol="AAPL", quantity="5", price="200", fee="0", broker="DEGIRO"),
            ]
        )
        unified = aggregate_by_symbol(holdings)
        assert set(unified.keys()) == {"AAPL"}
        assert unified["AAPL"].quantity == Decimal("15")
        # Weighted avg: (1000 + 1000) / 15 = 133.33
        assert unified["AAPL"].avg_cost.quantize(Decimal("0.01")) == Decimal("133.33")

    def test_unified_holding_has_no_broker(self):
        holdings = replay([_buy(symbol="AAPL", broker="IBKR")])
        unified = aggregate_by_symbol(holdings)
        assert unified["AAPL"].broker is None

    def test_sums_dividends_and_fees(self):
        holdings = replay(
            [
                _buy(symbol="AAPL", quantity="10", price="100", fee="2", broker="IBKR"),
                _buy(symbol="AAPL", quantity="5", price="200", fee="3", broker="DEGIRO"),
                _dividend(symbol="AAPL", amount="4", broker="IBKR"),
                _dividend(symbol="AAPL", amount="2", broker="DEGIRO"),
            ]
        )
        unified = aggregate_by_symbol(holdings)
        assert unified["AAPL"].dividends == Decimal("6")
        assert unified["AAPL"].fees == Decimal("5")

    def test_rejects_currency_mismatch(self):
        holdings = replay(
            [
                _buy(symbol="AAPL", broker="IBKR", currency=Currency.USD),
                _buy(symbol="AAPL", broker="DEGIRO", currency=Currency.EUR),
            ]
        )
        with pytest.raises(CurrencyMismatchError):
            aggregate_by_symbol(holdings)

    def test_passes_through_single_broker_holdings(self):
        holdings = replay([_buy(symbol="AAPL", broker="IBKR", quantity="10", price="100", fee="0")])
        unified = aggregate_by_symbol(holdings)
        assert unified["AAPL"].quantity == Decimal("10")
        assert unified["AAPL"].avg_cost == Decimal("100")


class TestRealizedSales:
    def test_records_a_realized_sale_with_basis_and_proceeds(self):
        holdings = replay(
            [_buy(quantity="10", price="100", fee="0"), _sell(quantity="4", price="150", fee="0")]
        )
        holding = holdings[("AAPL", None)]

        assert len(holding.realized_sales) == 1
        sale = holding.realized_sales[0]
        assert sale.quantity == Decimal("4")
        assert sale.basis_native == Decimal("400")
        assert sale.proceeds_native == Decimal("600")
        assert sale.pnl_native == Decimal("200")
        assert sale.date == date(2024, 6, 10)

    def test_cost_basis_sold_sums_across_sales(self):
        holdings = replay(
            [
                _buy(quantity="10", price="100", fee="0"),
                _sell(quantity="4", price="150", fee="0", on=date(2024, 6, 10)),
                _sell(quantity="6", price="120", fee="0", on=date(2024, 7, 1)),
            ]
        )
        holding = holdings[("AAPL", None)]
        assert holding.cost_basis_sold == Decimal("1000")

    def test_tracks_first_buy_and_last_sell_dates(self):
        holdings = replay(
            [
                _buy(quantity="10", price="100", fee="0", on=date(2024, 1, 10)),
                _sell(quantity="4", price="150", fee="0", on=date(2024, 6, 10)),
                _sell(quantity="6", price="120", fee="0", on=date(2024, 9, 1)),
            ]
        )
        holding = holdings[("AAPL", None)]
        assert holding.first_buy_date == date(2024, 1, 10)
        assert holding.last_sell_date == date(2024, 9, 1)


class TestClosedHoldings:
    def test_fully_sold_holding_is_closed_not_active(self):
        from pryces.domain.portfolio.holdings import closed_holdings

        holdings = replay(
            [_buy(quantity="10", price="100", fee="0"), _sell(quantity="10", price="150", fee="0")]
        )

        assert active_holdings(holdings) == {}
        closed = closed_holdings(holdings)
        assert ("AAPL", None) in closed
        assert closed[("AAPL", None)].realized_pnl == Decimal("500")

    def test_open_holding_is_not_closed(self):
        from pryces.domain.portfolio.holdings import closed_holdings

        holdings = replay(
            [_buy(quantity="10", price="100", fee="0"), _sell(quantity="4", price="150", fee="0")]
        )

        assert closed_holdings(holdings) == {}
        assert ("AAPL", None) in active_holdings(holdings)

    def test_never_sold_holding_is_not_closed(self):
        from pryces.domain.portfolio.holdings import closed_holdings

        holdings = replay([_buy(quantity="10", price="100", fee="0")])
        assert closed_holdings(holdings) == {}


class TestAggregateMergesRealized:
    def test_aggregate_merges_realized_sales_and_first_buy_date(self):
        holdings = replay(
            [
                _buy(broker="IBKR", quantity="10", price="100", fee="0", on=date(2024, 1, 1)),
                _sell(broker="IBKR", quantity="10", price="150", fee="0", on=date(2024, 6, 1)),
                _buy(broker="DEGIRO", quantity="5", price="80", fee="0", on=date(2023, 12, 1)),
                _sell(broker="DEGIRO", quantity="5", price="90", fee="0", on=date(2024, 5, 1)),
            ]
        )
        unified = aggregate_by_symbol(holdings)["AAPL"]
        assert len(unified.realized_sales) == 2
        assert unified.first_buy_date == date(2023, 12, 1)
        assert unified.cost_basis_sold == Decimal("1400")
