from datetime import date
from decimal import Decimal
from unittest.mock import Mock

import pytest

from pryces.application.exceptions import PortfolioNotFound
from pryces.application.interfaces import FxRateProvider, PortfolioRepository, StockProvider
from pryces.application.use_cases.get_portfolio import GetPortfolio, GetPortfolioRequest
from pryces.domain.portfolio.portfolio import ManualAsset, PortfolioSummary
from pryces.domain.portfolio.transactions import Transaction, TransactionType
from pryces.domain.stocks import Currency, Stock


def _summary(name: str = "main", base: str = "EUR", count: int = 0) -> PortfolioSummary:
    return PortfolioSummary(name=name, base_currency=base, transaction_count=count)


def _buy(
    symbol: str,
    quantity: str,
    price: str,
    currency: Currency,
    fee: str = "0",
    broker: str | None = None,
    when: date = date(2024, 1, 1),
) -> Transaction:
    return Transaction(
        date=when,
        type=TransactionType.BUY,
        symbol=symbol,
        currency=currency,
        quantity=Decimal(quantity),
        price=Decimal(price),
        fee=Decimal(fee),
        broker=broker,
    )


def _live(symbol: str, price: str) -> Stock:
    return Stock(symbol=symbol.upper(), current_price=Decimal(price))


class TestGetPortfolio:

    def setup_method(self):
        self.mock_repository = Mock(spec=PortfolioRepository)
        self.mock_stock_provider = Mock(spec=StockProvider)
        self.mock_fx_provider = Mock(spec=FxRateProvider)
        self.use_case = GetPortfolio(
            repository=self.mock_repository,
            stock_provider=self.mock_stock_provider,
            fx_provider=self.mock_fx_provider,
        )

    def test_raises_when_portfolio_missing(self):
        self.mock_repository.find_summary_by_name.return_value = None

        with pytest.raises(PortfolioNotFound):
            self.use_case.handle(GetPortfolioRequest(name="ghost"))

    def test_returns_empty_portfolio_when_no_transactions(self):
        self.mock_repository.find_summary_by_name.return_value = _summary()
        self.mock_repository.get_transactions.return_value = []
        self.mock_repository.get_manual_assets.return_value = []

        result = self.use_case.handle(GetPortfolioRequest(name="main"))

        assert result.base_currency == "EUR"
        assert result.positions == ()
        assert result.manual_assets == ()
        self.mock_stock_provider.get_stocks.assert_not_called()
        self.mock_fx_provider.get_rates.assert_not_called()

    def test_includes_manual_assets_even_with_no_transactions(self):
        self.mock_repository.find_summary_by_name.return_value = _summary()
        self.mock_repository.get_transactions.return_value = []
        self.mock_repository.get_manual_assets.return_value = [
            ManualAsset(name="Home", asset_type="real_estate", value_base=Decimal("250000")),
        ]

        result = self.use_case.handle(GetPortfolioRequest(name="main"))

        assert len(result.manual_assets) == 1
        assert result.manual_assets[0].name == "Home"

    def test_builds_position_with_same_base_currency(self):
        self.mock_repository.find_summary_by_name.return_value = _summary(base="USD")
        self.mock_repository.get_transactions.return_value = [
            _buy("AAPL", "10", "100", Currency.USD, fee="1"),
        ]
        self.mock_repository.get_manual_assets.return_value = []
        self.mock_stock_provider.get_stocks.return_value = [_live("AAPL", "150")]
        self.mock_fx_provider.get_rates.return_value = {Currency.USD: Decimal("1")}

        result = self.use_case.handle(GetPortfolioRequest(name="main"))

        assert len(result.positions) == 1
        position = result.positions[0]
        assert position.symbol == "AAPL"
        assert position.quantity == Decimal("10")
        assert position.price == Decimal("150")
        assert position.currency == Currency.USD
        assert position.value_base == Decimal("1500")
        # cost_total = 10 * 100 + 1 fee = 1001
        assert position.cost_base == Decimal("1001")
        assert position.fees_base == Decimal("1")
        assert position.dividends_base == Decimal("0")

    def test_converts_native_amounts_to_base_currency(self):
        self.mock_repository.find_summary_by_name.return_value = _summary(base="EUR")
        self.mock_repository.get_transactions.return_value = [
            _buy("AAPL", "10", "100", Currency.USD, fee="2"),
        ]
        self.mock_repository.get_manual_assets.return_value = []
        self.mock_stock_provider.get_stocks.return_value = [_live("AAPL", "150")]
        self.mock_fx_provider.get_rates.return_value = {Currency.USD: Decimal("0.9")}

        result = self.use_case.handle(GetPortfolioRequest(name="main"))

        position = result.positions[0]
        assert position.value_base == Decimal("10") * Decimal("150") * Decimal("0.9")
        assert position.cost_base == (Decimal("10") * Decimal("100") + Decimal("2")) * Decimal(
            "0.9"
        )

    def test_skips_positions_with_no_live_price(self):
        self.mock_repository.find_summary_by_name.return_value = _summary()
        self.mock_repository.get_transactions.return_value = [
            _buy("AAPL", "10", "100", Currency.USD),
            _buy("MSFT", "5", "200", Currency.USD),
        ]
        self.mock_repository.get_manual_assets.return_value = []
        # MSFT missing from provider response
        self.mock_stock_provider.get_stocks.return_value = [_live("AAPL", "150")]
        self.mock_fx_provider.get_rates.return_value = {Currency.USD: Decimal("0.9")}

        result = self.use_case.handle(GetPortfolioRequest(name="main"))

        assert len(result.positions) == 1
        assert result.positions[0].symbol == "AAPL"

    def test_skips_positions_with_no_fx_rate(self):
        self.mock_repository.find_summary_by_name.return_value = _summary(base="EUR")
        self.mock_repository.get_transactions.return_value = [
            _buy("AAPL", "10", "100", Currency.USD),
            _buy("TYO", "1", "1000", Currency.JPY),
        ]
        self.mock_repository.get_manual_assets.return_value = []
        self.mock_stock_provider.get_stocks.return_value = [
            _live("AAPL", "150"),
            _live("TYO", "1200"),
        ]
        # JPY rate missing → JPY position skipped
        self.mock_fx_provider.get_rates.return_value = {Currency.USD: Decimal("0.9")}

        result = self.use_case.handle(GetPortfolioRequest(name="main"))

        assert len(result.positions) == 1
        assert result.positions[0].symbol == "AAPL"

    def test_separates_positions_by_broker(self):
        self.mock_repository.find_summary_by_name.return_value = _summary(base="USD")
        self.mock_repository.get_transactions.return_value = [
            _buy("AAPL", "10", "100", Currency.USD, broker="IBKR"),
            _buy("AAPL", "5", "120", Currency.USD, broker="DEGIRO"),
        ]
        self.mock_repository.get_manual_assets.return_value = []
        self.mock_stock_provider.get_stocks.return_value = [_live("AAPL", "150")]
        self.mock_fx_provider.get_rates.return_value = {Currency.USD: Decimal("1")}

        result = self.use_case.handle(GetPortfolioRequest(name="main"))

        brokers = {position.broker for position in result.positions}
        assert brokers == {"IBKR", "DEGIRO"}

    def test_deduplicates_symbols_and_currencies(self):
        self.mock_repository.find_summary_by_name.return_value = _summary(base="USD")
        self.mock_repository.get_transactions.return_value = [
            _buy("AAPL", "10", "100", Currency.USD, broker="IBKR"),
            _buy("AAPL", "5", "120", Currency.USD, broker="DEGIRO"),
        ]
        self.mock_repository.get_manual_assets.return_value = []
        self.mock_stock_provider.get_stocks.return_value = [_live("AAPL", "150")]
        self.mock_fx_provider.get_rates.return_value = {Currency.USD: Decimal("1")}

        self.use_case.handle(GetPortfolioRequest(name="main"))

        assert self.mock_stock_provider.get_stocks.call_args[0][0] == ["AAPL"]
        called_quotes = self.mock_fx_provider.get_rates.call_args[0][1]
        assert called_quotes == [Currency.USD]

    def test_passes_through_user_id(self):
        self.mock_repository.find_summary_by_name.return_value = _summary()
        self.mock_repository.get_transactions.return_value = []
        self.mock_repository.get_manual_assets.return_value = []

        self.use_case.handle(GetPortfolioRequest(name="main", user_id=42))

        self.mock_repository.find_summary_by_name.assert_called_once_with("main", user_id=42)
        self.mock_repository.get_transactions.assert_called_once_with("main", user_id=42)
        self.mock_repository.get_manual_assets.assert_called_once_with("main", user_id=42)


class _FakeHistoricalFx:
    def __init__(self, rates=None):
        self.rates = rates or {}
        self.calls = []

    def get_rates(self, base, quote, dates):
        self.calls.append((base, quote, tuple(dates)))
        if quote == base:
            return {d: Decimal("1") for d in dates}
        return {d: self.rates.get((quote, d)) for d in dates if (quote, d) in self.rates}


class TestGetPortfolioXirr:

    def _use_case(self, historical):
        return GetPortfolio(
            repository=self.repo,
            stock_provider=self.stock,
            fx_provider=self.fx,
            historical_fx_provider=historical,
            clock=lambda: date(2025, 1, 1),
        )

    def setup_method(self):
        self.repo = Mock(spec=PortfolioRepository)
        self.stock = Mock(spec=StockProvider)
        self.fx = Mock(spec=FxRateProvider)
        self.repo.get_manual_assets.return_value = []

    def test_xirr_none_without_historical_provider(self):
        use_case = GetPortfolio(self.repo, self.stock, self.fx)
        self.repo.find_summary_by_name.return_value = _summary(base="USD")
        self.repo.get_transactions.return_value = [_buy("AAPL", "10", "100", Currency.USD)]
        self.stock.get_stocks.return_value = [_live("AAPL", "150")]
        self.fx.get_rates.return_value = {Currency.USD: Decimal("1")}

        result = use_case.handle(GetPortfolioRequest(name="main"))

        assert result.xirr_pct is None

    def test_computes_xirr_for_base_currency_holdings(self):
        self.repo.find_summary_by_name.return_value = _summary(base="USD")
        self.repo.get_transactions.return_value = [
            _buy("AAPL", "10", "100", Currency.USD, fee="0", when=date(2024, 1, 1)),
        ]
        self.stock.get_stocks.return_value = [_live("AAPL", "110")]
        self.fx.get_rates.return_value = {Currency.USD: Decimal("1")}

        result = self._use_case(_FakeHistoricalFx()).handle(GetPortfolioRequest(name="main"))

        # -1000 on 2024-01-01, +1100 value on 2025-01-01 -> ~10% annualized.
        assert abs(result.xirr_pct - Decimal("10")) < Decimal("0.5")

    def test_uses_historical_fx_for_foreign_currency(self):
        self.repo.find_summary_by_name.return_value = _summary(base="EUR")
        self.repo.get_transactions.return_value = [
            _buy("AAPL", "10", "100", Currency.USD, fee="0", when=date(2024, 1, 1)),
        ]
        self.stock.get_stocks.return_value = [_live("AAPL", "110")]
        self.fx.get_rates.return_value = {Currency.USD: Decimal("1")}  # current: 1 USD = 1 EUR
        historical = _FakeHistoricalFx({(Currency.USD, date(2024, 1, 1)): Decimal("1")})

        result = self._use_case(historical).handle(GetPortfolioRequest(name="main"))

        assert historical.calls  # historical FX was consulted
        assert abs(result.xirr_pct - Decimal("10")) < Decimal("0.5")

    def test_xirr_none_when_historical_rate_missing(self):
        self.repo.find_summary_by_name.return_value = _summary(base="EUR")
        self.repo.get_transactions.return_value = [
            _buy("AAPL", "10", "100", Currency.USD, fee="0", when=date(2024, 1, 1)),
        ]
        self.stock.get_stocks.return_value = [_live("AAPL", "110")]
        self.fx.get_rates.return_value = {Currency.USD: Decimal("1")}
        historical = _FakeHistoricalFx(rates={})  # no rate for the trade date

        result = self._use_case(historical).handle(GetPortfolioRequest(name="main"))

        assert result.xirr_pct is None
