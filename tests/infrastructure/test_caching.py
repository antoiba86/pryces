from decimal import Decimal
from unittest.mock import Mock

import pytest

from pryces.domain.stocks import Currency, Stock
from pryces.infrastructure.caching import (
    CachedFxRateProvider,
    CachedStockProvider,
    CacheSettings,
    TtlCache,
)


def _stock(symbol: str, price: str = "100") -> Stock:
    return Stock(symbol=symbol, current_price=Decimal(price))


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
