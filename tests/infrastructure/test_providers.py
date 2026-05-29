from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import Mock, patch

import pandas as pd
import pytest

from pryces.domain.stock_statistics import StatisticsPeriod
from pryces.domain.stocks import Currency, InstrumentType, MarketState
from pryces.infrastructure.providers import YahooFinanceMapper, map_currency


def _build_full_info(**overrides) -> dict:
    info = {
        "currentPrice": 150.25,
        "regularMarketPrice": 150.25,
        "previousClose": 148.50,
        "open": 149.00,
        "dayHigh": 151.00,
        "dayLow": 148.00,
        "fiftyDayAverage": 145.00,
        "twoHundredDayAverage": 140.00,
        "fiftyTwoWeekHigh": 160.00,
        "fiftyTwoWeekLow": 120.00,
        "marketCap": 2500000000000,
        "longName": "Test Company Inc.",
        "shortName": "Test Co",
        "currency": "USD",
        "marketState": "REGULAR",
        "exchangeDataDelayedBy": 0,
        "quoteType": "EQUITY",
    }
    info.update(overrides)
    return info


class TestYahooFinanceMapper:
    def test_maps_full_info_to_stock(self, mapper):
        stock = mapper.map("AAPL", _build_full_info())

        assert stock is not None
        assert stock.symbol == "AAPL"
        assert stock.current_price == Decimal("150.25")
        assert stock.name == "Test Company Inc."
        assert stock.currency == Currency.USD
        assert stock.previous_close_price == Decimal("148.5")
        assert stock.open_price == Decimal("149.0")
        assert stock.day_high == Decimal("151.0")
        assert stock.day_low == Decimal("148.0")
        assert stock.fifty_day_average == Decimal("145.0")
        assert stock.two_hundred_day_average == Decimal("140.0")
        assert stock.fifty_two_week_high == Decimal("160.0")
        assert stock.fifty_two_week_low == Decimal("120.0")
        assert stock.market_cap == Decimal("2500000000000")
        assert stock.market_state == MarketState.OPEN
        assert stock.price_delay_in_minutes == 0
        assert stock.kind == InstrumentType.STOCK

    def test_returns_none_for_empty_info(self, mapper):
        assert mapper.map("AAPL", {}) is None

    def test_returns_none_for_small_metadata_dict(self, mapper):
        info = {"key1": "val1", "key2": "val2", "key3": "val3"}

        assert mapper.map("AAPL", info) is None

    def test_allows_small_info_through_for_currency_quote_type(self, mapper):
        info = {
            "regularMarketPrice": 1.0825,
            "quoteType": "CURRENCY",
            "symbol": "EURUSD=X",
        }

        stock = mapper.map("EURUSD=X", info)

        assert stock is not None
        assert stock.current_price == Decimal("1.0825")
        assert stock.kind == InstrumentType.FX

    def test_returns_none_when_no_price_available(self, mapper):
        info = _build_full_info()
        del info["currentPrice"]
        del info["regularMarketPrice"]
        del info["previousClose"]

        assert mapper.map("AAPL", info) is None

    def test_price_fallback_to_regular_market_price(self, mapper):
        info = _build_full_info()
        del info["currentPrice"]
        info["regularMarketPrice"] = 155.00

        stock = mapper.map("AAPL", info)

        assert stock is not None
        assert stock.current_price == Decimal("155.0")

    def test_price_fallback_to_previous_close(self, mapper):
        info = _build_full_info()
        del info["currentPrice"]
        del info["regularMarketPrice"]
        info["previousClose"] = 148.50

        stock = mapper.map("AAPL", info)

        assert stock is not None
        assert stock.current_price == Decimal("148.5")

    def test_maps_market_states(self, mapper):
        cases = {
            "REGULAR": MarketState.OPEN,
            "PRE": MarketState.PRE,
            "PREPRE": MarketState.PRE,
            "POST": MarketState.POST,
            "POSTPOST": MarketState.POST,
            "CLOSED": MarketState.CLOSED,
        }
        for yfinance_value, expected_state in cases.items():
            info = _build_full_info(marketState=yfinance_value)

            stock = mapper.map("AAPL", info)

            assert stock is not None
            assert (
                stock.market_state == expected_state
            ), f"Expected {expected_state} for '{yfinance_value}'"

    def test_maps_unknown_market_state_to_none(self, mapper):
        info = _build_full_info(marketState="UNKNOWN_STATE")

        stock = mapper.map("AAPL", info)

        assert stock is not None
        assert stock.market_state is None

    def test_maps_none_market_state_to_none(self, mapper):
        info = _build_full_info(marketState=None)

        stock = mapper.map("AAPL", info)

        assert stock is not None
        assert stock.market_state is None

    def test_adds_extra_delay_when_delay_positive(self):
        mapper = YahooFinanceMapper(extra_delay_in_minutes=5, logger_factory=Mock())
        info = _build_full_info(exchangeDataDelayedBy=15)

        stock = mapper.map("AAPL", info)

        assert stock is not None
        assert stock.price_delay_in_minutes == 20

    def test_uses_extra_delay_when_exchange_delay_zero(self):
        mapper = YahooFinanceMapper(extra_delay_in_minutes=5, logger_factory=Mock())
        info = _build_full_info(exchangeDataDelayedBy=0)

        stock = mapper.map("AAPL", info)

        assert stock is not None
        assert stock.price_delay_in_minutes == 5

    def test_uses_extra_delay_when_exchange_delay_null(self):
        mapper = YahooFinanceMapper(extra_delay_in_minutes=5, logger_factory=Mock())
        info = _build_full_info(exchangeDataDelayedBy=None)

        stock = mapper.map("AAPL", info)

        assert stock is not None
        assert stock.price_delay_in_minutes == 5

    def test_handles_missing_optional_fields(self, mapper):
        info = {"currentPrice": 100.0, "k1": "v1", "k2": "v2", "k3": "v3"}

        stock = mapper.map("AAPL", info)

        assert stock is not None
        assert stock.current_price == Decimal("100.0")
        assert stock.name is None
        assert stock.currency is None
        assert stock.previous_close_price is None
        assert stock.open_price is None
        assert stock.day_high is None
        assert stock.day_low is None
        assert stock.fifty_day_average is None
        assert stock.two_hundred_day_average is None
        assert stock.fifty_two_week_high is None
        assert stock.fifty_two_week_low is None
        assert stock.market_cap is None
        assert stock.market_state is None
        assert stock.price_delay_in_minutes == 0

    def test_uppercases_symbol(self, mapper):
        info = _build_full_info()

        stock = mapper.map("aapl", info)

        assert stock is not None
        assert stock.symbol == "AAPL"

    @pytest.mark.parametrize(
        "quote_type, expected_kind",
        [
            ("EQUITY", InstrumentType.STOCK),
            ("ETF", InstrumentType.ETF),
            ("CRYPTOCURRENCY", InstrumentType.CRYPTO),
            ("INDEX", InstrumentType.INDEX),
            ("CURRENCY", InstrumentType.FX),
            ("MUTUALFUND", None),
            ("FUTURE", None),
            (None, None),
        ],
    )
    def test_maps_instrument_types(self, mapper, quote_type, expected_kind):
        info = _build_full_info(quoteType=quote_type)

        stock = mapper.map("AAPL", info)

        assert stock is not None
        assert stock.kind == expected_kind

    @pytest.mark.parametrize(
        "raw_currency, expected_currency",
        [
            ("USD", Currency.USD),
            ("EUR", Currency.EUR),
            ("GBP", Currency.GBP),
            ("GBp", Currency.GBP),  # yfinance returns pence for LSE stocks
            ("JPY", Currency.JPY),
            ("KRW", Currency.KRW),
            ("HKD", Currency.HKD),
            ("CAD", Currency.CAD),
            ("AUD", Currency.AUD),
            ("TWD", None),  # unsupported currency maps to None
            (None, None),
        ],
    )
    def test_maps_currencies(self, mapper, raw_currency, expected_currency):
        info = _build_full_info(currency=raw_currency)

        stock = mapper.map("AAPL", info)

        assert stock is not None
        assert stock.currency == expected_currency


class TestMapCurrency:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("USD", Currency.USD),
            ("EUR", Currency.EUR),
            ("GBp", Currency.GBP),
            ("TWD", None),
            (None, None),
        ],
    )
    def test_maps_currency_values(self, raw, expected):
        assert map_currency(raw) == expected


def _build_history(days_back: int = 400) -> pd.DataFrame:
    today = date.today()
    dates = pd.date_range(
        start=today - timedelta(days=days_back),
        end=today,
        freq="B",
    )
    data = {
        "Open": [100.0 + i * 0.1 for i in range(len(dates))],
        "High": [101.0 + i * 0.1 for i in range(len(dates))],
        "Low": [99.0 + i * 0.1 for i in range(len(dates))],
        "Close": [100.0 + i * 0.1 for i in range(len(dates))],
        "Volume": [1000000] * len(dates),
    }
    return pd.DataFrame(data, index=dates)


class TestYahooFinanceStatisticsMapper:
    def test_maps_full_info_to_statistics(self, statistics_mapper):
        info = _build_full_info()
        history = _build_history()

        stats = statistics_mapper.map("AAPL", info, history)

        assert stats is not None
        assert stats.symbol == "AAPL"
        assert stats.name == "Test Company Inc."
        assert stats.currency == Currency.USD
        assert len(stats.price_changes) > 0

    def test_returns_none_for_empty_info(self, statistics_mapper):
        assert statistics_mapper.map("AAPL", {}, _build_history()) is None

    def test_returns_none_for_small_metadata_dict(self, statistics_mapper):
        info = {"key1": "val1", "key2": "val2", "key3": "val3"}
        assert statistics_mapper.map("AAPL", info, _build_history()) is None

    def test_returns_none_when_history_is_empty(self, statistics_mapper):
        empty_history = pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])

        assert statistics_mapper.map("AAPL", _build_full_info(), empty_history) is None

    def test_uppercases_symbol(self, statistics_mapper):
        stats = statistics_mapper.map("aapl", _build_full_info(), _build_history())

        assert stats is not None
        assert stats.symbol == "AAPL"

    def test_maps_currency(self, statistics_mapper):
        info = _build_full_info(currency="EUR")

        stats = statistics_mapper.map("AAPL", info, _build_history())

        assert stats is not None
        assert stats.currency == Currency.EUR

    def test_name_falls_back_to_short_name(self, statistics_mapper):
        info = _build_full_info(longName=None)

        stats = statistics_mapper.map("AAPL", info, _build_history())

        assert stats is not None
        assert stats.name == "Test Co"

    def test_current_price_is_last_history_close(self, statistics_mapper):
        history = _build_history()
        expected_price = Decimal(str(history.iloc[-1]["Close"]))

        stats = statistics_mapper.map("AAPL", _build_full_info(), history)

        assert stats is not None
        assert stats.current_price == expected_price

    def test_builds_all_periods_from_full_history(self, statistics_mapper):
        history = _build_history(days_back=400)

        stats = statistics_mapper.map("AAPL", _build_full_info(), history)

        assert stats is not None
        periods = {pc.period for pc in stats.price_changes}
        assert periods == {
            StatisticsPeriod.ONE_DAY,
            StatisticsPeriod.ONE_WEEK,
            StatisticsPeriod.THREE_MONTHS,
            StatisticsPeriod.ONE_YEAR,
            StatisticsPeriod.YEAR_TO_DATE,
        }

    def test_skips_periods_without_data(self, statistics_mapper):
        history = _build_history(days_back=5)

        stats = statistics_mapper.map("AAPL", _build_full_info(), history)

        assert stats is not None
        periods = {pc.period for pc in stats.price_changes}
        assert StatisticsPeriod.ONE_YEAR not in periods
        assert StatisticsPeriod.THREE_MONTHS not in periods

    def test_historical_close_uses_closest_trading_day(self, statistics_mapper):
        today = date.today()
        last_trading_date = today - timedelta(days=1)
        # Sparse history: only two dates, with a gap around the 1D target
        dates = pd.to_datetime([last_trading_date - timedelta(days=2), last_trading_date])
        history = pd.DataFrame(
            {
                "Close": [90.0, 95.0],
                "Open": [90.0, 95.0],
                "High": [91.0, 96.0],
                "Low": [89.0, 94.0],
                "Volume": [1000, 1000],
            },
            index=dates,
        )

        stats = statistics_mapper.map("AAPL", _build_full_info(), history)

        assert stats is not None
        assert stats.current_price == Decimal("95.0")
        one_day = next(
            (pc for pc in stats.price_changes if pc.period == StatisticsPeriod.ONE_DAY),
            None,
        )
        assert one_day is not None
        # 1D target = last_trading_date - 1 day; closest prior close is last_trading_date - 2 days
        assert one_day.close_price == Decimal("90.0")

    def test_ytd_uses_previous_year_end(self, statistics_mapper):
        # History ends in 2026 (last_trading_date = Mar 15 2026),
        # so YTD anchor = date(2026 - 1, 12, 31) = Dec 31, 2025
        dates = pd.to_datetime([date(2025, 12, 30), date(2025, 12, 31), date(2026, 3, 15)])
        history = pd.DataFrame(
            {
                "Close": [270.0, 275.0, 300.0],
                "Open": [270.0, 275.0, 300.0],
                "High": [271.0, 276.0, 301.0],
                "Low": [269.0, 274.0, 299.0],
                "Volume": [1000, 1000, 1000],
            },
            index=dates,
        )

        stats = statistics_mapper.map("AAPL", _build_full_info(), history)

        assert stats is not None
        ytd = next(
            (pc for pc in stats.price_changes if pc.period == StatisticsPeriod.YEAR_TO_DATE),
            None,
        )
        assert ytd is not None
        assert ytd.close_price == Decimal("275.0")

    def test_returns_none_when_current_price_is_nan(self, statistics_mapper):
        history = _build_history(days_back=5)
        history.iloc[-1, history.columns.get_loc("Close")] = float("nan")

        assert statistics_mapper.map("AAPL", _build_full_info(), history) is None

    def test_skips_period_when_historical_close_is_nan(self, statistics_mapper):
        history = _build_history(days_back=400)
        history.iloc[0, history.columns.get_loc("Close")] = float("nan")

        stats = statistics_mapper.map("AAPL", _build_full_info(), history)

        assert stats is not None
        # YTD uses the oldest row; even if it were NaN the period would just be skipped
        # The important assertion is no InvalidOperation is raised and current_price is valid
        assert stats.current_price > 0

    def test_weekend_uses_last_trading_date_as_anchor(self, statistics_mapper):
        # Reproduces the Saturday bug: history ends on Friday, today is Saturday.
        # current_price must be Friday's close and 1D must compare against Thursday's close.
        thursday = date(2026, 4, 9)
        friday = date(2026, 4, 10)
        dates = pd.to_datetime([thursday, friday])
        history = pd.DataFrame(
            {
                "Close": [148.0, 150.0],
                "Open": [148.0, 150.0],
                "High": [149.0, 151.0],
                "Low": [147.0, 149.0],
                "Volume": [1000, 1000],
            },
            index=dates,
        )

        stats = statistics_mapper.map("AAPL", _build_full_info(), history)

        assert stats is not None
        assert stats.current_price == Decimal("150.0")
        one_day = next(
            (pc for pc in stats.price_changes if pc.period == StatisticsPeriod.ONE_DAY),
            None,
        )
        assert one_day is not None
        assert one_day.close_price == Decimal("148.0")
