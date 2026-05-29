from decimal import Decimal
from unittest.mock import Mock

from pryces.application.interfaces import StockProvider
from pryces.domain.stocks import Currency, InstrumentType, Stock
from pryces.infrastructure.fx import YahooFinanceFxProvider


def _fx_stock(symbol: str, price: str) -> Stock:
    return Stock(
        symbol=symbol.upper(),
        current_price=Decimal(price),
        kind=InstrumentType.FX,
    )


class TestYahooFinanceFxProvider:

    def setup_method(self):
        self.mock_stock_provider = Mock(spec=StockProvider)
        self.fx = YahooFinanceFxProvider(
            stock_provider=self.mock_stock_provider,
            logger_factory=Mock(),
        )

    def test_returns_unit_rate_for_base_only(self):
        rates = self.fx.get_rates(Currency.EUR, [Currency.EUR])

        assert rates == {Currency.EUR: Decimal("1")}
        self.mock_stock_provider.get_stocks.assert_not_called()

    def test_returns_empty_dict_for_no_quotes(self):
        rates = self.fx.get_rates(Currency.EUR, [])

        assert rates == {}
        self.mock_stock_provider.get_stocks.assert_not_called()

    def test_fetches_direct_pair(self):
        self.mock_stock_provider.get_stocks.return_value = [
            _fx_stock("USDEUR=X", "0.92"),
        ]

        rates = self.fx.get_rates(Currency.EUR, [Currency.USD])

        assert rates == {Currency.USD: Decimal("0.92")}
        self.mock_stock_provider.get_stocks.assert_called_once_with(["USDEUR=X"])

    def test_falls_back_to_inverted_pair(self):
        # First call (direct) returns nothing; second call (inverted) returns rate.
        self.mock_stock_provider.get_stocks.side_effect = [
            [],
            [_fx_stock("EURUSD=X", "1.0825")],
        ]

        rates = self.fx.get_rates(Currency.EUR, [Currency.USD])

        assert Currency.USD in rates
        assert rates[Currency.USD] == Decimal("1") / Decimal("1.0825")
        assert self.mock_stock_provider.get_stocks.call_count == 2

    def test_omits_currency_when_both_lookups_fail(self):
        self.mock_stock_provider.get_stocks.side_effect = [[], []]

        rates = self.fx.get_rates(Currency.EUR, [Currency.JPY])

        assert Currency.JPY not in rates

    def test_mixes_base_direct_and_inverted(self):
        # Direct call: returns USDEUR=X; inverted call: returns EURJPY=X for the JPY fallback.
        self.mock_stock_provider.get_stocks.side_effect = [
            [_fx_stock("USDEUR=X", "0.92")],
            [_fx_stock("EURJPY=X", "160.50")],
        ]

        rates = self.fx.get_rates(Currency.EUR, [Currency.EUR, Currency.USD, Currency.JPY])

        assert rates[Currency.EUR] == Decimal("1")
        assert rates[Currency.USD] == Decimal("0.92")
        assert rates[Currency.JPY] == Decimal("1") / Decimal("160.50")

    def test_deduplicates_quote_currencies(self):
        self.mock_stock_provider.get_stocks.return_value = [
            _fx_stock("USDEUR=X", "0.92"),
        ]

        self.fx.get_rates(Currency.EUR, [Currency.USD, Currency.USD])

        self.mock_stock_provider.get_stocks.assert_called_once_with(["USDEUR=X"])

    def test_skips_zero_or_negative_price(self):
        # Zero price (bad data) treated as missing → fallback to inverted, also missing → omitted.
        self.mock_stock_provider.get_stocks.side_effect = [
            [_fx_stock("USDEUR=X", "0")],
            [],
        ]

        rates = self.fx.get_rates(Currency.EUR, [Currency.USD])

        assert Currency.USD not in rates
