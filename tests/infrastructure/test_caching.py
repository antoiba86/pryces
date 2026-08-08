from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import Mock

import pytest

from pryces.domain.stocks import Currency, MarketState, Stock
from pryces.infrastructure.caching import (
    CachedFxRateProvider,
    CachedHistoricalFxRateProvider,
    CachedHistoricalPriceProvider,
    CachedStockProvider,
    CacheSettings,
    HistorySeriesCache,
    TtlCache,
)

_NOW = datetime(2026, 6, 8, 13, 55, tzinfo=timezone.utc)  # a Monday, 5 min before a 14:00 open


def _stock(
    symbol: str,
    price: str = "100",
    market_state: MarketState | None = None,
    next_market_open: datetime | None = None,
) -> Stock:
    return Stock(
        symbol=symbol,
        current_price=Decimal(price),
        market_state=market_state,
        next_market_open=next_market_open,
    )


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class RecordingStockProvider:
    """Returns a preset stock per requested symbol and records every batch asked for."""

    def __init__(self, stocks: dict[str, Stock]) -> None:
        self._stocks = stocks
        self.calls: list[list[str]] = []

    def get_stocks(self, symbols, use_cache: bool = True):
        self.calls.append(list(symbols))
        return [self._stocks[s] for s in symbols if s in self._stocks]


class TestCacheSettings:
    def test_rejects_negative_ttl(self):
        with pytest.raises(ValueError):
            CacheSettings(ttl_seconds=-1)

    def test_accepts_zero_and_positive(self):
        assert CacheSettings(ttl_seconds=0).ttl_seconds == 0
        assert CacheSettings(ttl_seconds=300).ttl_seconds == 300


class TestTtlCache:
    def test_returns_value_within_ttl(self):
        clock = FakeClock()
        cache: TtlCache[str, int] = TtlCache(ttl_seconds=10, clock=clock)
        cache.put("a", 1)
        clock.advance(9)
        assert cache.get("a") == 1

    def test_expires_value_at_ttl(self):
        clock = FakeClock()
        cache: TtlCache[str, int] = TtlCache(ttl_seconds=10, clock=clock)
        cache.put("a", 1)
        clock.advance(10)
        assert cache.get("a") is None

    def test_miss_returns_none(self):
        assert TtlCache(ttl_seconds=10).get("absent") is None

    def test_zero_ttl_never_caches(self):
        cache: TtlCache[str, int] = TtlCache(ttl_seconds=0)
        cache.put("a", 1)
        assert cache.get("a") is None

    def test_clear_drops_entries(self):
        cache: TtlCache[str, int] = TtlCache(ttl_seconds=10)
        cache.put("a", 1)
        cache.clear()
        assert cache.get("a") is None

    def test_per_entry_ttl_overrides_default(self):
        clock = FakeClock()
        cache: TtlCache[str, int] = TtlCache(ttl_seconds=10, clock=clock)
        cache.put("short", 1)  # default TTL of 10
        cache.put("long", 2, ttl_seconds=100)
        clock.advance(50)
        assert cache.get("short") is None  # default TTL elapsed
        assert cache.get("long") == 2  # longer per-entry TTL still valid

    def test_disabled_cache_ignores_per_entry_ttl(self):
        cache: TtlCache[str, int] = TtlCache(ttl_seconds=0)
        cache.put("a", 1, ttl_seconds=1000)
        assert cache.get("a") is None  # ttl=0 is a global kill switch


class TestCachedStockProvider:
    def test_empty_symbols_skips_inner(self):
        inner = RecordingStockProvider({})
        provider = CachedStockProvider(inner, TtlCache(ttl_seconds=300), Mock())
        assert provider.get_stocks([]) == []
        assert inner.calls == []

    def test_first_call_fetches_then_serves_from_cache(self):
        clock = FakeClock()
        inner = RecordingStockProvider({"AAPL": _stock("AAPL")})
        provider = CachedStockProvider(inner, TtlCache(ttl_seconds=300, clock=clock), Mock())

        first = provider.get_stocks(["AAPL"])
        second = provider.get_stocks(["AAPL"])

        assert [s.symbol for s in first] == ["AAPL"]
        assert [s.symbol for s in second] == ["AAPL"]
        assert inner.calls == [["AAPL"]]  # second call served from cache

    def test_refetches_after_ttl_expires(self):
        clock = FakeClock()
        inner = RecordingStockProvider({"AAPL": _stock("AAPL")})
        provider = CachedStockProvider(inner, TtlCache(ttl_seconds=300, clock=clock), Mock())

        provider.get_stocks(["AAPL"])
        clock.advance(300)
        provider.get_stocks(["AAPL"])

        assert inner.calls == [["AAPL"], ["AAPL"]]

    def test_only_missing_symbols_are_fetched(self):
        inner = RecordingStockProvider({"AAPL": _stock("AAPL"), "MSFT": _stock("MSFT")})
        provider = CachedStockProvider(inner, TtlCache(ttl_seconds=300), Mock())

        provider.get_stocks(["AAPL"])
        result = provider.get_stocks(["AAPL", "MSFT"])

        assert [s.symbol for s in result] == ["AAPL", "MSFT"]
        assert inner.calls == [["AAPL"], ["MSFT"]]  # AAPL reused, only MSFT fetched

    def test_preserves_requested_order(self):
        inner = RecordingStockProvider(
            {"AAPL": _stock("AAPL"), "MSFT": _stock("MSFT"), "TSLA": _stock("TSLA")}
        )
        provider = CachedStockProvider(inner, TtlCache(ttl_seconds=300), Mock())
        result = provider.get_stocks(["TSLA", "AAPL", "MSFT"])
        assert [s.symbol for s in result] == ["TSLA", "AAPL", "MSFT"]

    def test_unresolved_symbols_are_omitted_and_not_cached(self):
        inner = RecordingStockProvider({"AAPL": _stock("AAPL")})
        provider = CachedStockProvider(inner, TtlCache(ttl_seconds=300), Mock())

        first = provider.get_stocks(["AAPL", "NOPE"])
        second = provider.get_stocks(["NOPE"])

        assert [s.symbol for s in first] == ["AAPL"]
        assert second == []
        # NOPE was not cached as a failure, so it is retried.
        assert inner.calls == [["AAPL", "NOPE"], ["NOPE"]]

    def test_case_insensitive_cache_key(self):
        inner = RecordingStockProvider({"aapl": _stock("AAPL")})
        provider = CachedStockProvider(inner, TtlCache(ttl_seconds=300), Mock())

        provider.get_stocks(["aapl"])
        provider.get_stocks(["AAPL"])

        assert inner.calls == [["aapl"]]  # second lookup hits the cache despite casing

    def test_use_cache_false_bypasses_and_refreshes(self):
        inner = RecordingStockProvider({"AAPL": _stock("AAPL", "100")})
        cache: TtlCache[str, Stock] = TtlCache(ttl_seconds=300)
        provider = CachedStockProvider(inner, cache, Mock())

        provider.get_stocks(["AAPL"])
        # Inner now returns a fresher price; a bypass must re-fetch and update cache.
        inner._stocks["AAPL"] = _stock("AAPL", "200")
        bypassed = provider.get_stocks(["AAPL"], use_cache=False)
        cached_after = provider.get_stocks(["AAPL"])

        assert bypassed[0].current_price == Decimal("200")
        assert cached_after[0].current_price == Decimal("200")  # cache was refreshed
        assert inner.calls == [["AAPL"], ["AAPL"]]

    def test_closed_market_quote_uses_the_longer_ttl(self):
        clock = FakeClock()
        inner = RecordingStockProvider({"AAPL": _stock("AAPL", market_state=MarketState.CLOSED)})
        provider = CachedStockProvider(
            inner,
            TtlCache(ttl_seconds=300, clock=clock),
            Mock(),
            closed_ttl_seconds=3600,
        )

        provider.get_stocks(["AAPL"])
        clock.advance(300)  # past the short TTL...
        provider.get_stocks(["AAPL"])  # ...but the market is closed, so still cached
        clock.advance(3300)  # now past the closed TTL (3600 total)
        provider.get_stocks(["AAPL"])

        assert inner.calls == [["AAPL"], ["AAPL"]]  # one fetch, then one after the long TTL

    def test_open_market_quote_uses_the_short_ttl(self):
        clock = FakeClock()
        inner = RecordingStockProvider({"AAPL": _stock("AAPL", market_state=MarketState.OPEN)})
        provider = CachedStockProvider(
            inner,
            TtlCache(ttl_seconds=300, clock=clock),
            Mock(),
            closed_ttl_seconds=3600,
        )

        provider.get_stocks(["AAPL"])
        clock.advance(300)  # short TTL elapsed; an open market must be re-fetched
        provider.get_stocks(["AAPL"])

        assert inner.calls == [["AAPL"], ["AAPL"]]

    def test_closed_quote_is_capped_to_next_open(self):
        # Fetched 5 min before the open: the long closed TTL must be clamped so the
        # entry expires at the open, not ~an hour into the live session.
        clock = FakeClock()
        inner = RecordingStockProvider(
            {
                "BME": _stock(
                    "BME",
                    market_state=MarketState.CLOSED,
                    next_market_open=_NOW + timedelta(minutes=5),
                )
            }
        )
        provider = CachedStockProvider(
            inner,
            TtlCache(ttl_seconds=300, clock=clock),
            Mock(),
            closed_ttl_seconds=3600,
            now=lambda: _NOW,
        )

        provider.get_stocks(["BME"])
        clock.advance(299)  # just before the open — still cached
        provider.get_stocks(["BME"])
        clock.advance(1)  # market has opened (300s) — entry expired, must re-fetch
        provider.get_stocks(["BME"])

        assert inner.calls == [["BME"], ["BME"]]

    def test_next_open_in_the_past_falls_back_to_closed_ttl(self):
        clock = FakeClock()
        inner = RecordingStockProvider(
            {
                "BME": _stock(
                    "BME",
                    market_state=MarketState.CLOSED,
                    next_market_open=_NOW - timedelta(hours=1),
                )
            }
        )
        provider = CachedStockProvider(
            inner,
            TtlCache(ttl_seconds=300, clock=clock),
            Mock(),
            closed_ttl_seconds=3600,
            now=lambda: _NOW,
        )

        provider.get_stocks(["BME"])
        clock.advance(300)  # past the short TTL but within the 1h closed fallback
        provider.get_stocks(["BME"])

        assert inner.calls == [["BME"]]  # served from cache; stale next-open ignored

    def test_extended_hours_quote_uses_the_short_ttl(self):
        clock = FakeClock()
        inner = RecordingStockProvider({"AAPL": _stock("AAPL", market_state=MarketState.POST)})
        provider = CachedStockProvider(
            inner,
            TtlCache(ttl_seconds=300, clock=clock),
            Mock(),
            closed_ttl_seconds=3600,
        )

        provider.get_stocks(["AAPL"])
        clock.advance(300)  # POST-market prices still move, so no long TTL
        provider.get_stocks(["AAPL"])

        assert inner.calls == [["AAPL"], ["AAPL"]]


class RecordingFxRateProvider:
    """Returns a preset rate per requested quote and records every batch asked for."""

    def __init__(self, rates: dict[Currency, Decimal]) -> None:
        self._rates = rates
        self.calls: list[list[Currency]] = []

    def get_rates(self, base, quotes, use_cache: bool = True):
        self.calls.append(list(quotes))
        return {q: self._rates[q] for q in quotes if q in self._rates}


class TestCachedFxRateProvider:
    def test_empty_quotes_skips_inner(self):
        inner = RecordingFxRateProvider({})
        provider = CachedFxRateProvider(inner, TtlCache(ttl_seconds=3600), Mock())
        assert provider.get_rates(Currency.EUR, []) == {}
        assert inner.calls == []

    def test_first_call_fetches_then_serves_from_cache(self):
        inner = RecordingFxRateProvider({Currency.USD: Decimal("0.92")})
        provider = CachedFxRateProvider(inner, TtlCache(ttl_seconds=3600), Mock())

        first = provider.get_rates(Currency.EUR, [Currency.USD])
        second = provider.get_rates(Currency.EUR, [Currency.USD])

        assert first == {Currency.USD: Decimal("0.92")}
        assert second == {Currency.USD: Decimal("0.92")}
        assert inner.calls == [[Currency.USD]]  # second served from cache

    def test_refetches_after_ttl_expires(self):
        clock = FakeClock()
        inner = RecordingFxRateProvider({Currency.USD: Decimal("0.92")})
        provider = CachedFxRateProvider(inner, TtlCache(ttl_seconds=3600, clock=clock), Mock())

        provider.get_rates(Currency.EUR, [Currency.USD])
        clock.advance(3600)
        provider.get_rates(Currency.EUR, [Currency.USD])

        assert inner.calls == [[Currency.USD], [Currency.USD]]

    def test_only_missing_quotes_are_fetched(self):
        inner = RecordingFxRateProvider(
            {Currency.USD: Decimal("0.92"), Currency.GBP: Decimal("1.17")}
        )
        provider = CachedFxRateProvider(inner, TtlCache(ttl_seconds=3600), Mock())

        provider.get_rates(Currency.EUR, [Currency.USD])
        result = provider.get_rates(Currency.EUR, [Currency.USD, Currency.GBP])

        assert result == {Currency.USD: Decimal("0.92"), Currency.GBP: Decimal("1.17")}
        assert inner.calls == [[Currency.USD], [Currency.GBP]]  # USD reused

    def test_cache_key_includes_base(self):
        inner = RecordingFxRateProvider({Currency.USD: Decimal("0.92")})
        provider = CachedFxRateProvider(inner, TtlCache(ttl_seconds=3600), Mock())

        provider.get_rates(Currency.EUR, [Currency.USD])
        provider.get_rates(Currency.GBP, [Currency.USD])  # same quote, different base

        assert inner.calls == [[Currency.USD], [Currency.USD]]  # not a cache hit

    def test_unpriced_quotes_are_omitted_and_not_cached(self):
        inner = RecordingFxRateProvider({Currency.USD: Decimal("0.92")})
        provider = CachedFxRateProvider(inner, TtlCache(ttl_seconds=3600), Mock())

        first = provider.get_rates(Currency.EUR, [Currency.USD, Currency.JPY])
        second = provider.get_rates(Currency.EUR, [Currency.JPY])

        assert first == {Currency.USD: Decimal("0.92")}
        assert second == {}
        assert inner.calls == [[Currency.USD, Currency.JPY], [Currency.JPY]]  # JPY retried

    def test_use_cache_false_bypasses_and_refreshes(self):
        inner = RecordingFxRateProvider({Currency.USD: Decimal("0.92")})
        provider = CachedFxRateProvider(inner, TtlCache(ttl_seconds=3600), Mock())

        provider.get_rates(Currency.EUR, [Currency.USD])
        inner._rates[Currency.USD] = Decimal("0.95")
        bypassed = provider.get_rates(Currency.EUR, [Currency.USD], use_cache=False)
        cached_after = provider.get_rates(Currency.EUR, [Currency.USD])

        assert bypassed == {Currency.USD: Decimal("0.95")}
        assert cached_after == {Currency.USD: Decimal("0.95")}  # cache refreshed
        assert inner.calls == [[Currency.USD], [Currency.USD]]


_TODAY = date(2026, 6, 8)


class RecordingHistoricalPriceProvider:
    """Prices every (symbol, date) it knows and records each batch asked for."""

    def __init__(self, prices: dict[tuple[str, date], Decimal]) -> None:
        self._prices = prices
        self.calls: list[tuple[list[str], list[date]]] = []

    def get_prices(self, symbols, dates):
        self.calls.append((list(symbols), list(dates)))
        return {
            (symbol, day): self._prices[(symbol, day)]
            for symbol in symbols
            for day in dates
            if (symbol, day) in self._prices
        }


class TestCachedHistoricalPriceProvider:

    def _provider(self, inner, ttl_seconds=86400, clock=None):
        return CachedHistoricalPriceProvider(
            inner,
            TtlCache(ttl_seconds=ttl_seconds, clock=clock or FakeClock()),
            Mock(),
            unsettled_ttl_seconds=300,
            today=lambda: _TODAY,
        )

    def test_second_call_is_served_from_cache(self):
        past = date(2026, 6, 1)
        inner = RecordingHistoricalPriceProvider({("AAPL", past): Decimal("150")})
        provider = self._provider(inner)

        first = provider.get_prices(["AAPL"], [past])
        second = provider.get_prices(["AAPL"], [past])

        assert first == second == {("AAPL", past): Decimal("150")}
        assert inner.calls == [(["AAPL"], [past])]  # fetched once

    def test_only_missing_pairs_are_fetched(self):
        first_day, second_day = date(2026, 6, 1), date(2026, 6, 2)
        inner = RecordingHistoricalPriceProvider(
            {("AAPL", first_day): Decimal("150"), ("AAPL", second_day): Decimal("151")}
        )
        provider = self._provider(inner)

        provider.get_prices(["AAPL"], [first_day])
        provider.get_prices(["AAPL"], [first_day, second_day])

        assert inner.calls == [(["AAPL"], [first_day]), (["AAPL"], [second_day])]

    def test_repeated_symbol_within_one_call_fetched_once(self):
        past = date(2026, 6, 1)
        inner = RecordingHistoricalPriceProvider({("AAPL", past): Decimal("150")})
        provider = self._provider(inner)

        provider.get_prices(["AAPL", "AAPL"], [past])

        assert inner.calls == [(["AAPL"], [past])]

    def test_past_close_is_held_for_the_long_ttl(self):
        past = date(2026, 6, 1)
        clock = FakeClock()
        inner = RecordingHistoricalPriceProvider({("AAPL", past): Decimal("150")})
        provider = self._provider(inner, clock=clock)

        provider.get_prices(["AAPL"], [past])
        clock.advance(3600)  # well past the short TTL — a settled close never changes
        provider.get_prices(["AAPL"], [past])

        assert len(inner.calls) == 1

    def test_todays_close_expires_on_the_short_ttl(self):
        clock = FakeClock()
        inner = RecordingHistoricalPriceProvider({("AAPL", _TODAY): Decimal("150")})
        provider = self._provider(inner, clock=clock)

        provider.get_prices(["AAPL"], [_TODAY])
        clock.advance(300)  # today's close is still moving
        provider.get_prices(["AAPL"], [_TODAY])

        assert len(inner.calls) == 2

    def test_unavailable_pair_is_not_cached(self):
        past = date(2026, 6, 1)
        inner = RecordingHistoricalPriceProvider({})
        provider = self._provider(inner)

        provider.get_prices(["AAPL"], [past])
        provider.get_prices(["AAPL"], [past])

        assert len(inner.calls) == 2  # retried rather than pinned as a failure

    def test_empty_inputs_skip_the_inner_provider(self):
        inner = RecordingHistoricalPriceProvider({})
        provider = self._provider(inner)

        assert provider.get_prices([], [date(2026, 6, 1)]) == {}
        assert provider.get_prices(["AAPL"], []) == {}
        assert inner.calls == []


class RecordingHistoricalFxProvider:
    """Rates every (quote, date) it knows and records each batch asked for."""

    def __init__(self, rates: dict[tuple[Currency, date], Decimal]) -> None:
        self._rates = rates
        self.calls: list[dict[Currency, list[date]]] = []

    def get_rates(self, base, dates_by_quote):
        self.calls.append({q: list(d) for q, d in dates_by_quote.items()})
        return {
            (quote, day): self._rates[(quote, day)]
            for quote, days in dates_by_quote.items()
            for day in days
            if (quote, day) in self._rates
        }


class TestCachedHistoricalFxRateProvider:

    def _provider(self, inner, ttl_seconds=86400, clock=None):
        return CachedHistoricalFxRateProvider(
            inner,
            TtlCache(ttl_seconds=ttl_seconds, clock=clock or FakeClock()),
            Mock(),
            unsettled_ttl_seconds=300,
            today=lambda: _TODAY,
        )

    def test_second_call_is_served_from_cache(self):
        past = date(2026, 6, 1)
        inner = RecordingHistoricalFxProvider({(Currency.USD, past): Decimal("0.92")})
        provider = self._provider(inner)

        first = provider.get_rates(Currency.EUR, {Currency.USD: [past]})
        second = provider.get_rates(Currency.EUR, {Currency.USD: [past]})

        assert first == second == {(Currency.USD, past): Decimal("0.92")}
        assert inner.calls == [{Currency.USD: [past]}]

    def test_only_missing_quotes_are_fetched(self):
        past = date(2026, 6, 1)
        inner = RecordingHistoricalFxProvider(
            {(Currency.USD, past): Decimal("0.92"), (Currency.AUD, past): Decimal("0.60")}
        )
        provider = self._provider(inner)

        provider.get_rates(Currency.EUR, {Currency.USD: [past]})
        provider.get_rates(Currency.EUR, {Currency.USD: [past], Currency.AUD: [past]})

        assert inner.calls == [{Currency.USD: [past]}, {Currency.AUD: [past]}]

    def test_rates_are_keyed_per_base(self):
        past = date(2026, 6, 1)
        inner = RecordingHistoricalFxProvider({(Currency.USD, past): Decimal("0.92")})
        provider = self._provider(inner)

        provider.get_rates(Currency.EUR, {Currency.USD: [past]})
        provider.get_rates(Currency.GBP, {Currency.USD: [past]})

        # A USD rate in EUR says nothing about the same quote in GBP.
        assert len(inner.calls) == 2

    def test_past_rate_is_held_for_the_long_ttl(self):
        past = date(2026, 6, 1)
        clock = FakeClock()
        inner = RecordingHistoricalFxProvider({(Currency.USD, past): Decimal("0.92")})
        provider = self._provider(inner, clock=clock)

        provider.get_rates(Currency.EUR, {Currency.USD: [past]})
        clock.advance(3600)
        provider.get_rates(Currency.EUR, {Currency.USD: [past]})

        assert len(inner.calls) == 1

    def test_todays_rate_expires_on_the_short_ttl(self):
        clock = FakeClock()
        inner = RecordingHistoricalFxProvider({(Currency.USD, _TODAY): Decimal("0.92")})
        provider = self._provider(inner, clock=clock)

        provider.get_rates(Currency.EUR, {Currency.USD: [_TODAY]})
        clock.advance(300)
        provider.get_rates(Currency.EUR, {Currency.USD: [_TODAY]})

        assert len(inner.calls) == 2

    def test_unavailable_pair_is_not_cached(self):
        past = date(2026, 6, 1)
        inner = RecordingHistoricalFxProvider({})
        provider = self._provider(inner)

        provider.get_rates(Currency.EUR, {Currency.USD: [past]})
        provider.get_rates(Currency.EUR, {Currency.USD: [past]})

        assert len(inner.calls) == 2

    def test_no_quotes_skips_the_inner_provider(self):
        inner = RecordingHistoricalFxProvider({})
        provider = self._provider(inner)

        assert provider.get_rates(Currency.EUR, {}) == {}
        assert inner.calls == []


class TestHistorySeriesCache:

    def _cache(self, ttl_seconds=300, clock=None):
        return HistorySeriesCache(TtlCache(ttl_seconds=ttl_seconds, clock=clock or FakeClock()))

    def test_second_lookup_reuses_the_series(self):
        cache = self._cache()
        calls = []

        def load(since):
            calls.append(since)
            return {date(2026, 3, 2): Decimal("150")}

        first = cache.fetch("AAPL", date(2026, 3, 1), load)
        second = cache.fetch("AAPL", date(2026, 3, 1), load)

        assert first == second
        assert len(calls) == 1

    def test_start_is_floored_to_the_year(self):
        cache = self._cache()
        calls = []

        def load(since):
            calls.append(since)
            return {date(2026, 3, 2): Decimal("150")}

        cache.fetch("AAPL", date(2026, 6, 30), load)

        assert calls == [date(2026, 1, 1)]

    def test_different_dates_in_the_same_year_share_one_fetch(self):
        cache = self._cache()
        calls = []

        def load(since):
            calls.append(since)
            return {date(2026, 3, 2): Decimal("150")}

        # The exact case that made an overview re-fetch: each portfolio's
        # earliest transaction differs by days.
        cache.fetch("USDEUR", date(2026, 2, 4), load)
        cache.fetch("USDEUR", date(2026, 9, 18), load)

        assert len(calls) == 1

    def test_earlier_year_refetches_then_serves_everyone(self):
        cache = self._cache()
        calls = []

        def load(since):
            calls.append(since)
            return {date(2024, 3, 2): Decimal("150")}

        cache.fetch("AAPL", date(2026, 3, 1), load)
        cache.fetch("AAPL", date(2024, 3, 1), load)  # reaches further back
        cache.fetch("AAPL", date(2026, 3, 1), load)  # now covered by the wider span

        assert calls == [date(2026, 1, 1), date(2024, 1, 1)]

    def test_empty_series_is_not_cached(self):
        cache = self._cache()
        calls = []

        def load(since):
            calls.append(since)
            return {}

        cache.fetch("NOPE", date(2026, 3, 1), load)
        cache.fetch("NOPE", date(2026, 3, 1), load)

        assert len(calls) == 2  # retried rather than pinned as a failure

    def test_entry_expires_on_the_ttl(self):
        clock = FakeClock()
        cache = self._cache(clock=clock)
        calls = []

        def load(since):
            calls.append(since)
            return {date(2026, 3, 2): Decimal("150")}

        cache.fetch("AAPL", date(2026, 3, 1), load)
        clock.advance(300)  # the series ends on today's unsettled close
        cache.fetch("AAPL", date(2026, 3, 1), load)

        assert len(calls) == 2
