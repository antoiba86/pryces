from __future__ import annotations

import threading
import time
from collections.abc import Callable, Hashable
from dataclasses import dataclass
from decimal import Decimal
from typing import Generic, TypeVar

from ..application.interfaces import FxRateProvider, LoggerFactory, StockProvider
from ..domain.stocks import Currency, Stock

# Quotes move every tick; FX is far steadier, so it gets a much longer TTL.
DEFAULT_CACHE_TTL_SECONDS = 300
DEFAULT_FX_CACHE_TTL_SECONDS = 3600

K = TypeVar("K", bound=Hashable)
V = TypeVar("V")


@dataclass(frozen=True, slots=True)
class CacheSettings:
    ttl_seconds: int

    def __post_init__(self) -> None:
        if not isinstance(self.ttl_seconds, int) or self.ttl_seconds < 0:
            raise ValueError("ttl_seconds must be a non-negative integer")


class TtlCache(Generic[K, V]):
    """A small thread-safe, time-to-live key/value store.

    Entries expire `ttl_seconds` after they are written; a TTL of 0 disables
    caching (every read misses). The clock is injectable for deterministic
    tests and defaults to a monotonic clock so wall-clock changes can't skew
    expiry. One instance is shared process-wide (see `dependencies.py`) so the
    cache survives across requests.
    """

    def __init__(self, ttl_seconds: int, clock: Callable[[], float] = time.monotonic) -> None:
        self._ttl = ttl_seconds
        self._clock = clock
        self._entries: dict[K, tuple[float, V]] = {}
        self._lock = threading.Lock()

    def get(self, key: K) -> V | None:
        if self._ttl <= 0:
            return None
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            stored_at, value = entry
            if self._clock() - stored_at >= self._ttl:
                del self._entries[key]
                return None
            return value

    def put(self, key: K, value: V) -> None:
        if self._ttl <= 0:
            return
        with self._lock:
            self._entries[key] = (self._clock(), value)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


class CachedStockProvider(StockProvider):
    """Decorator that serves recent stock quotes from a TtlCache before the network.

    Every live Yahoo lookup — both stock prices and live FX pairs (the FX
    provider fetches `EURUSD=X`-style symbols through a StockProvider) — funnels
    through `get_stocks`, so caching here covers both. Cache hits are returned
    without a network call; only the still-missing symbols are fetched in one
    batch and recorded. Symbols the inner provider can't resolve are left
    uncached so they're retried next time rather than pinned as failures.

    Pass `use_cache=False` to bypass the cache for that call: missing-and-stale
    symbols are fetched fresh and the cache is refreshed with the results.
    """

    def __init__(
        self,
        inner: StockProvider,
        cache: TtlCache[str, Stock],
        logger_factory: LoggerFactory,
    ) -> None:
        self._inner = inner
        self._cache = cache
        self._logger = logger_factory.get_logger(__name__)

    def get_stocks(self, symbols: list[str], use_cache: bool = True) -> list[Stock]:
        if not symbols:
            return []

        resolved: dict[str, Stock] = {}
        missing: list[str] = []
        for symbol in symbols:
            cached = self._cache.get(symbol.upper()) if use_cache else None
            if cached is not None:
                resolved[symbol] = cached
            else:
                missing.append(symbol)

        if missing:
            self._logger.debug(f"Cache miss for {len(missing)}/{len(symbols)} symbols; fetching")
            fetched = {stock.symbol.upper(): stock for stock in self._inner.get_stocks(missing)}
            for stock in fetched.values():
                self._cache.put(stock.symbol.upper(), stock)
            for symbol in missing:
                stock = fetched.get(symbol.upper())
                if stock is not None:
                    resolved[symbol] = stock

        # Preserve the caller's order and drop unresolved symbols, matching the
        # inner provider's contract (omits symbols with no data).
        return [resolved[symbol] for symbol in symbols if symbol in resolved]


class CachedFxRateProvider(FxRateProvider):
    """Decorator that serves FX rates from a TtlCache (typically a longer TTL).

    Rates are cached per `(base, quote)` pair, so currencies shared across
    portfolios are reused. Only the quotes missing from the cache are fetched
    from the inner provider; quotes the inner provider can't price are left
    uncached so they're retried next time. `use_cache=False` bypasses the cache
    and refreshes the fetched pairs.

    The inner FX provider is given an *uncached* StockProvider so FX pairs live
    only here (at the FX TTL), not also in the shorter-lived quote cache.
    """

    def __init__(
        self,
        inner: FxRateProvider,
        cache: TtlCache[tuple[Currency, Currency], Decimal],
        logger_factory: LoggerFactory,
    ) -> None:
        self._inner = inner
        self._cache = cache
        self._logger = logger_factory.get_logger(__name__)

    def get_rates(
        self, base: Currency, quotes: list[Currency], use_cache: bool = True
    ) -> dict[Currency, Decimal]:
        if not quotes:
            return {}

        rates: dict[Currency, Decimal] = {}
        missing: list[Currency] = []
        for quote in quotes:
            cached = self._cache.get((base, quote)) if use_cache else None
            if cached is not None:
                rates[quote] = cached
            elif quote not in missing:
                missing.append(quote)

        if missing:
            self._logger.debug(f"FX cache miss for {len(missing)}/{len(quotes)} quotes; fetching")
            fetched = self._inner.get_rates(base, missing, use_cache=use_cache)
            for quote, rate in fetched.items():
                self._cache.put((base, quote), rate)
                rates[quote] = rate

        return rates
