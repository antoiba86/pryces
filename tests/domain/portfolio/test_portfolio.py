from decimal import Decimal

import pytest

from pryces.domain.portfolio.portfolio import ManualAsset, Portfolio, Position, PortfolioSummary
from pryces.domain.stocks import Currency


def _position(
    symbol="AAPL",
    value="1100",
    cost="1000",
    dividends="0",
    fees="0",
    broker=None,
    quantity="10",
    avg_cost="100",
    price="110",
) -> Position:
    return Position(
        symbol=symbol,
        quantity=Decimal(quantity),
        avg_cost=Decimal(avg_cost),
        price=Decimal(price),
        currency=Currency.USD,
        value_base=Decimal(value),
        cost_base=Decimal(cost),
        dividends_base=Decimal(dividends),
        fees_base=Decimal(fees),
        broker=broker,
    )


class TestPositionDerivedValues:
    def test_unrealized_pnl_is_value_minus_cost(self):
        p = _position(value="1200", cost="1000")
        assert p.unrealized_pnl_base == Decimal("200")

    def test_unrealized_pnl_can_be_negative(self):
        p = _position(value="800", cost="1000")
        assert p.unrealized_pnl_base == Decimal("-200")

    def test_total_return_includes_dividends_and_fees(self):
        # (1200 + 50 - 1000 - 5) / 1000 * 100 = 24.5
        p = _position(value="1200", cost="1000", dividends="50", fees="5")
        assert p.total_return_pct == Decimal("24.5")


class TestPortfolioAggregates:
    def test_positions_value_sums(self):
        portfolio = Portfolio(
            base_currency="EUR",
            positions=(_position(value="1000"), _position(symbol="MSFT", value="500")),
        )
        assert portfolio.positions_value == Decimal("1500")

    def test_manual_value_sums(self):
        portfolio = Portfolio(
            base_currency="EUR",
            manual_assets=(
                ManualAsset(name="Home", asset_type="real_estate", value_base=Decimal("250000")),
                ManualAsset(name="Pension", asset_type="pension", value_base=Decimal("30000")),
            ),
        )
        assert portfolio.manual_value == Decimal("280000")

    def test_total_value_combines_positions_and_manual(self):
        portfolio = Portfolio(
            base_currency="EUR",
            positions=(_position(value="1000"),),
            manual_assets=(
                ManualAsset(name="Home", asset_type="real_estate", value_base=Decimal("250000")),
            ),
        )
        assert portfolio.total_value == Decimal("251000")

    def test_total_cost_excludes_manual_assets(self):
        portfolio = Portfolio(
            base_currency="EUR",
            positions=(_position(cost="500"),),
            manual_assets=(
                ManualAsset(name="Home", asset_type="real_estate", value_base=Decimal("250000")),
            ),
        )
        assert portfolio.total_cost == Decimal("500")

    def test_total_unrealized_pnl_sums_position_pnl(self):
        portfolio = Portfolio(
            base_currency="EUR",
            positions=(
                _position(value="1200", cost="1000"),
                _position(symbol="MSFT", value="900", cost="1000"),
            ),
        )
        assert portfolio.total_unrealized_pnl == Decimal("100")

    def test_total_return_pct_aggregates(self):
        # Sum: value=2000, cost=2000, dividends=50, fees=5 → (2000+50-2000-5)/2000*100 = 2.25
        portfolio = Portfolio(
            base_currency="EUR",
            positions=(
                _position(value="1000", cost="1000", dividends="20", fees="2"),
                _position(symbol="MSFT", value="1000", cost="1000", dividends="30", fees="3"),
            ),
        )
        assert portfolio.total_return_pct == Decimal("2.25")


class TestPortfolioAllocation:
    def test_allocation_for_position(self):
        portfolio = Portfolio(
            base_currency="EUR",
            positions=(_position(value="750"), _position(symbol="MSFT", value="250")),
        )
        appl = portfolio.positions[0]
        assert portfolio.allocation_for(appl) == Decimal("75")

    def test_manual_allocation(self):
        portfolio = Portfolio(
            base_currency="EUR",
            positions=(_position(value="1000"),),
            manual_assets=(
                ManualAsset(name="Home", asset_type="real_estate", value_base=Decimal("3000")),
            ),
        )
        assert portfolio.manual_allocation(portfolio.manual_assets[0]) == Decimal("75")

    def test_allocation_returns_zero_for_empty_portfolio(self):
        portfolio = Portfolio(base_currency="EUR")
        position = _position()
        assert portfolio.allocation_for(position) == Decimal("0")


class TestEmptyPortfolio:
    def test_empty_defaults(self):
        portfolio = Portfolio(base_currency="EUR")
        assert portfolio.total_value == Decimal("0")
        assert portfolio.total_cost == Decimal("0")
        assert portfolio.total_unrealized_pnl == Decimal("0")
        assert portfolio.total_return_pct == Decimal("0")

    def test_xirr_and_twr_default_to_none(self):
        portfolio = Portfolio(base_currency="EUR")
        assert portfolio.xirr_pct is None
        assert portfolio.twr_pct is None


class TestPositionBroker:
    def test_broker_defaults_to_none(self):
        p = _position()
        assert p.broker is None

    def test_broker_is_stored(self):
        p = _position(broker="IBKR")
        assert p.broker == "IBKR"


class TestUnifiedPositions:
    def test_single_broker_position_keeps_its_broker(self):
        portfolio = Portfolio(
            base_currency="EUR",
            positions=(_position(symbol="AAPL", broker="IBKR"),),
        )
        unified = portfolio.unified_positions
        assert len(unified) == 1
        assert unified[0].symbol == "AAPL"
        assert unified[0].broker == "IBKR"

    def test_collapses_same_symbol_across_brokers(self):
        portfolio = Portfolio(
            base_currency="EUR",
            positions=(
                _position(
                    symbol="AAPL",
                    quantity="10",
                    avg_cost="100",
                    price="110",
                    value="1100",
                    cost="1000",
                    broker="IBKR",
                ),
                _position(
                    symbol="AAPL",
                    quantity="5",
                    avg_cost="200",
                    price="210",
                    value="1050",
                    cost="1000",
                    broker="DEGIRO",
                ),
            ),
        )
        unified = portfolio.unified_positions
        assert len(unified) == 1
        aapl = unified[0]
        assert aapl.symbol == "AAPL"
        assert aapl.broker is None  # cross-broker merge clears the broker
        assert aapl.quantity == Decimal("15")
        # Weighted avg cost: (10*100 + 5*200) / 15 = 133.33
        assert aapl.avg_cost.quantize(Decimal("0.01")) == Decimal("133.33")
        # Weighted price: (10*110 + 5*210) / 15 = 143.33
        assert aapl.price.quantize(Decimal("0.01")) == Decimal("143.33")
        # Base-currency sums
        assert aapl.value_base == Decimal("2150")
        assert aapl.cost_base == Decimal("2000")

    def test_preserves_distinct_symbols(self):
        portfolio = Portfolio(
            base_currency="EUR",
            positions=(
                _position(symbol="AAPL", broker="IBKR"),
                _position(symbol="MSFT", broker="IBKR"),
                _position(symbol="AAPL", broker="DEGIRO"),
            ),
        )
        unified = portfolio.unified_positions
        symbols = sorted(p.symbol for p in unified)
        assert symbols == ["AAPL", "MSFT"]


class TestPositionsByBroker:
    def test_groups_by_broker(self):
        portfolio = Portfolio(
            base_currency="EUR",
            positions=(
                _position(symbol="AAPL", broker="IBKR"),
                _position(symbol="MSFT", broker="IBKR"),
                _position(symbol="AAPL", broker="DEGIRO"),
            ),
        )
        grouped = portfolio.positions_by_broker()
        assert set(grouped.keys()) == {"IBKR", "DEGIRO"}
        assert {p.symbol for p in grouped["IBKR"]} == {"AAPL", "MSFT"}
        assert {p.symbol for p in grouped["DEGIRO"]} == {"AAPL"}

    def test_none_broker_is_its_own_group(self):
        portfolio = Portfolio(
            base_currency="EUR",
            positions=(
                _position(symbol="AAPL", broker=None),
                _position(symbol="MSFT", broker="IBKR"),
            ),
        )
        grouped = portfolio.positions_by_broker()
        assert set(grouped.keys()) == {None, "IBKR"}


class TestPortfolioSummary:
    def test_construction(self):
        summary = PortfolioSummary(name="main", base_currency="EUR", transaction_count=42)
        assert summary.name == "main"
        assert summary.base_currency == "EUR"
        assert summary.transaction_count == 42

    def test_frozen(self):
        summary = PortfolioSummary(name="main", base_currency="EUR", transaction_count=42)
        with pytest.raises(Exception):
            summary.name = "other"


def _closed(
    symbol="AAPL",
    realized="200",
    basis="400",
    return_pct="50",
    hold_days=120,
    broker=None,
):
    from pryces.domain.portfolio.portfolio import ClosedPosition

    return ClosedPosition(
        symbol=symbol,
        currency=Currency.USD,
        realized_pnl_base=Decimal(realized),
        cost_basis_sold_base=Decimal(basis),
        realized_return_pct=Decimal(return_pct),
        hold_period_days=hold_days,
        broker=broker,
    )


class TestRealizedAndProfit:
    def test_total_realized_sums_open_and_closed(self):
        portfolio = Portfolio(
            base_currency="EUR",
            positions=(_position(value="1100", cost="1000"),),
            closed_positions=(_closed(realized="200"),),
        )
        # open position default realized_pnl_base is 0
        assert portfolio.total_realized_pnl == Decimal("200")

    def test_total_realized_includes_partial_sells_on_open_positions(self):
        position = Position(
            symbol="AAPL",
            quantity=Decimal("6"),
            avg_cost=Decimal("100"),
            price=Decimal("110"),
            currency=Currency.USD,
            value_base=Decimal("660"),
            cost_base=Decimal("600"),
            dividends_base=Decimal("0"),
            fees_base=Decimal("0"),
            realized_pnl_base=Decimal("150"),
        )
        portfolio = Portfolio(base_currency="EUR", positions=(position,))
        assert portfolio.total_realized_pnl == Decimal("150")

    def test_total_profit_combines_unrealized_realized_dividends(self):
        position = Position(
            symbol="AAPL",
            quantity=Decimal("10"),
            avg_cost=Decimal("100"),
            price=Decimal("110"),
            currency=Currency.USD,
            value_base=Decimal("1100"),
            cost_base=Decimal("1000"),
            dividends_base=Decimal("30"),
            fees_base=Decimal("0"),
            realized_pnl_base=Decimal("0"),
        )
        portfolio = Portfolio(
            base_currency="EUR",
            positions=(position,),
            closed_positions=(_closed(realized="200"),),
        )
        # unrealized 100 + realized 200 + dividends 30
        assert portfolio.total_profit == Decimal("330")

    def test_merged_positions_sum_realized(self):
        a = Position(
            symbol="AAPL",
            quantity=Decimal("5"),
            avg_cost=Decimal("100"),
            price=Decimal("110"),
            currency=Currency.USD,
            value_base=Decimal("550"),
            cost_base=Decimal("500"),
            dividends_base=Decimal("0"),
            fees_base=Decimal("0"),
            broker="IBKR",
            realized_pnl_base=Decimal("40"),
        )
        b = Position(
            symbol="AAPL",
            quantity=Decimal("5"),
            avg_cost=Decimal("100"),
            price=Decimal("110"),
            currency=Currency.USD,
            value_base=Decimal("550"),
            cost_base=Decimal("500"),
            dividends_base=Decimal("0"),
            fees_base=Decimal("0"),
            broker="DEGIRO",
            realized_pnl_base=Decimal("60"),
        )
        portfolio = Portfolio(base_currency="EUR", positions=(a, b))
        unified = portfolio.unified_positions
        assert len(unified) == 1
        assert unified[0].realized_pnl_base == Decimal("100")
