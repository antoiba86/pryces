from decimal import Decimal

import pytest

from pryces.domain.portfolio.portfolio import ManualAsset, Portfolio, Position
from pryces.domain.stocks import Currency
from pryces.infrastructure.portfolio_formatters import TelegramPortfolioFormatter


def _position(
    symbol: str = "AAPL",
    quantity: str = "10",
    avg_cost: str = "100",
    price: str = "150",
    currency: Currency = Currency.USD,
    value_base: str = "1500",
    cost_base: str = "1000",
    dividends_base: str = "0",
    fees_base: str = "0",
    broker: str | None = None,
) -> Position:
    return Position(
        symbol=symbol,
        quantity=Decimal(quantity),
        avg_cost=Decimal(avg_cost),
        price=Decimal(price),
        currency=currency,
        value_base=Decimal(value_base),
        cost_base=Decimal(cost_base),
        dividends_base=Decimal(dividends_base),
        fees_base=Decimal(fees_base),
        broker=broker,
    )


class TestTelegramPortfolioFormatter:

    def setup_method(self):
        self.formatter = TelegramPortfolioFormatter()

    def test_formats_empty_portfolio(self):
        portfolio = Portfolio(base_currency="EUR")

        messages = self.formatter.format(portfolio)

        assert len(messages) == 1
        body = messages[0]
        assert "Portfolio (EUR)" in body
        assert "Total value: 0.00 EUR" in body
        assert "Holdings" not in body
        assert "Manual assets" not in body
        assert "Total return" not in body

    def test_formats_single_position(self):
        portfolio = Portfolio(
            base_currency="USD",
            positions=(_position(),),
        )

        messages = self.formatter.format(portfolio)

        body = messages[0]
        assert "AAPL" in body
        assert "10 @ 150.00 USD" in body
        assert "1,500.00 USD" in body
        # 1500-1000 = +500 → +50%
        assert "+50.00%" in body
        assert "Unrealized P&L: +500.00 USD" in body

    def test_formats_multi_currency_position(self):
        portfolio = Portfolio(
            base_currency="EUR",
            positions=(
                _position(
                    symbol="AAPL",
                    currency=Currency.USD,
                    price="150",
                    value_base="1350",
                    cost_base="900",
                ),
            ),
        )

        body = self.formatter.format(portfolio)[0]
        assert "AAPL — 10 @ 150.00 USD" in body
        assert "1,350.00 EUR" in body

    def test_includes_manual_assets(self):
        portfolio = Portfolio(
            base_currency="EUR",
            manual_assets=(
                ManualAsset(name="Home", asset_type="real_estate", value_base=Decimal("250000")),
            ),
        )

        body = self.formatter.format(portfolio)[0]
        assert "Manual assets" in body
        assert "Home (real_estate)" in body
        assert "250,000.00 EUR" in body
        assert "100.00%" in body

    def test_collapses_brokers_in_unified_view(self):
        portfolio = Portfolio(
            base_currency="USD",
            positions=(
                _position(broker="IBKR", quantity="10", value_base="1500", cost_base="1000"),
                _position(broker="DEGIRO", quantity="5", value_base="750", cost_base="600"),
            ),
        )

        body = self.formatter.format(portfolio)[0]
        # unified_positions collapses to single AAPL with broker=None → no suffix
        assert body.count("AAPL") == 1
        assert "[IBKR]" not in body
        assert "[DEGIRO]" not in body
        # quantity sum 15
        assert "15 @" in body

    def test_unified_view_omits_broker_for_single_holder(self):
        portfolio = Portfolio(
            base_currency="USD",
            positions=(_position(broker="IBKR"),),
        )

        body = self.formatter.format(portfolio)[0]
        # unified_positions strips the broker even with a single holder.
        assert "[IBKR]" not in body
        assert "AAPL —" in body

    def test_includes_xirr_and_twr_when_present(self):
        portfolio = Portfolio(
            base_currency="EUR",
            positions=(_position(value_base="1500", cost_base="1000"),),
            xirr_pct=Decimal("12.34"),
            twr_pct=Decimal("-3.21"),
        )

        body = self.formatter.format(portfolio)[0]
        assert "XIRR: +12.34%" in body
        assert "TWR: -3.21%" in body

    def test_omits_xirr_and_twr_when_absent(self):
        portfolio = Portfolio(base_currency="EUR", positions=(_position(),))

        body = self.formatter.format(portfolio)[0]
        assert "XIRR" not in body
        assert "TWR" not in body

    def test_splits_into_multiple_messages_when_too_long(self):
        # Build a portfolio whose total formatted output exceeds 4096 chars.
        many_assets = tuple(
            ManualAsset(
                name=f"Asset {i:03d}",
                asset_type="other",
                value_base=Decimal("1000"),
            )
            for i in range(200)
        )
        portfolio = Portfolio(base_currency="EUR", manual_assets=many_assets)

        messages = self.formatter.format(portfolio)

        assert len(messages) >= 2
        for message in messages:
            assert len(message) <= 4096

    def test_fits_in_one_message_when_under_limit(self):
        portfolio = Portfolio(
            base_currency="EUR",
            positions=(_position(),),
            manual_assets=(
                ManualAsset(name="Home", asset_type="real_estate", value_base=Decimal("250000")),
            ),
        )

        messages = self.formatter.format(portfolio)
        assert len(messages) == 1

    def test_signed_money_handles_negative_pnl(self):
        portfolio = Portfolio(
            base_currency="EUR",
            positions=(_position(value_base="800", cost_base="1000"),),
        )

        body = self.formatter.format(portfolio)[0]
        assert "Unrealized P&L: -200.00 EUR" in body
        assert "-20.00%" in body

    @pytest.mark.parametrize(
        "quantity,expected",
        [
            ("10", "10"),
            ("10.5", "10.5"),
            ("0.001", "0.001"),
            ("100.0000", "100"),
        ],
    )
    def test_quantity_formatting(self, quantity, expected):
        portfolio = Portfolio(
            base_currency="USD",
            positions=(_position(quantity=quantity),),
        )

        body = self.formatter.format(portfolio)[0]
        assert f"{expected} @" in body
