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


from datetime import date

from pryces.infrastructure.fx import YahooFinanceHistoricalFxProvider


class _StubLoggerFactory:
    def get_logger(self, name):
        return Mock()


class TestYahooFinanceHistoricalFxProvider:

    def _provider(self, fetcher):
        return YahooFinanceHistoricalFxProvider(_StubLoggerFactory(), history_fetcher=fetcher)

    def test_same_currency_maps_to_one(self):
        provider = self._provider(lambda symbol, start: {})

        rates = provider.get_rates(Currency.EUR, Currency.EUR, [date(2024, 1, 1)])

        assert rates == {date(2024, 1, 1): Decimal("1")}

    def test_empty_dates_returns_empty(self):
        provider = self._provider(lambda symbol, start: {})

        assert provider.get_rates(Currency.EUR, Currency.USD, []) == {}

    def test_direct_pair_lookup(self):
        calls = []

        def fetch(symbol, start):
            calls.append(symbol)
            return {date(2024, 1, 1): Decimal("0.90")}

        provider = self._provider(fetch)
        rates = provider.get_rates(Currency.EUR, Currency.USD, [date(2024, 1, 1)])

        assert calls == ["USDEUR=X"]
        assert rates == {date(2024, 1, 1): Decimal("0.90")}

    def test_falls_back_to_inverted_pair(self):
        def fetch(symbol, start):
            if symbol == "USDEUR=X":
                return {}
            return {date(2024, 1, 1): Decimal("1.25")}  # EURUSD

        provider = self._provider(fetch)
        rates = provider.get_rates(Currency.EUR, Currency.USD, [date(2024, 1, 1)])

        assert rates[date(2024, 1, 1)] == Decimal("1") / Decimal("1.25")

    def test_nearest_prior_for_weekend_date(self):
        def fetch(symbol, start):
            return {date(2024, 1, 5): Decimal("0.90")}  # Friday

        provider = self._provider(fetch)
        # Sunday the 7th falls back to Friday the 5th.
        rates = provider.get_rates(Currency.EUR, Currency.USD, [date(2024, 1, 7)])

        assert rates[date(2024, 1, 7)] == Decimal("0.90")

    def test_date_before_series_uses_earliest(self):
        def fetch(symbol, start):
            return {date(2024, 1, 10): Decimal("0.90")}

        provider = self._provider(fetch)
        rates = provider.get_rates(Currency.EUR, Currency.USD, [date(2024, 1, 1)])

        assert rates[date(2024, 1, 1)] == Decimal("0.90")

    def test_unavailable_pair_yields_no_rates(self):
        provider = self._provider(lambda symbol, start: {})

        rates = provider.get_rates(Currency.EUR, Currency.USD, [date(2024, 1, 1)])

        assert rates == {}
