from __future__ import annotations

import threading
import time
from collections.abc import Callable, Hashable
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Generic, TypeVar

from ..application.interfaces import (
    FxRateProvider,
    HistoricalFxRateProvider,
    HistoricalPriceProvider,
    LoggerFactory,
    StockProvider,
)
from ..domain.stocks import Currency, MarketState, Stock

# Quotes move every tick; FX is far steadier, so it gets a much longer TTL. When an
# exchange is closed (nights, weekends, holidays) the price won't change until it
# reopens, so closed-market quotes are held far longer to avoid pointless calls.
# Historical closes for past dates never change at all, so they get the longest TTL
# of the lot — a day, bounded only so a long-running process eventually re-reads.
DEFAULT_CACHE_TTL_SECONDS = 300
DEFAULT_FX_CACHE_TTL_SECONDS = 3600
DEFAULT_CLOSED_CACHE_TTL_SECONDS = 3600
DEFAULT_HISTORICAL_CACHE_TTL_SECONDS = 86400

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

    Entries expire `ttl_seconds` after they are written; `put` may override that
    per entry (e.g. a longer life for data known not to change soon). A default
    TTL of 0 disables caching entirely (every read misses), acting as a global
    kill switch regardless of per-entry overrides. The clock is injectable for
    deterministic tests and defaults to a monotonic clock so wall-clock changes
    can't skew expiry. One instance is shared process-wide (see
    `dependencies.py`) so the cache survives across requests.
    """

    def __init__(self, ttl_seconds: int, clock: Callable[[], float] = time.monotonic) -> None:
        self._ttl = ttl_seconds
        self._clock = clock
        self._entries: dict[K, tuple[float, V]] = {}  # key -> (expires_at, value)
        self._lock = threading.Lock()

    def get(self, key: K) -> V | None:
        if self._ttl <= 0:
            return None
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if self._clock() >= expires_at:
                del self._entries[key]
                return None
            return value

    def put(self, key: K, value: V, ttl_seconds: int | None = None) -> None:
        if self._ttl <= 0:
            return
        ttl = self._ttl if ttl_seconds is None else ttl_seconds
        if ttl <= 0:
            return
        with self._lock:
            self._entries[key] = (self._clock() + ttl, value)

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

    A quote whose `market_state` is CLOSED won't change until the exchange
    reopens, so it is cached with `closed_ttl_seconds` (typically much longer)
    instead of the short default — this is what stops needless calls overnight,
    on weekends, and on holidays, per-exchange, using the state Yahoo already
    reports. Quotes in extended hours (PRE/POST) still move, so they keep the
    short TTL.

    When the quote also carries `next_market_open`, the closed TTL is capped so
    the entry expires no later than the reopen — otherwise a fetch shortly before
    the open would serve a frozen price for up to `closed_ttl_seconds` into the
    live session.

    Pass `use_cache=False` to bypass the cache for that call: missing-and-stale
    symbols are fetched fresh and the cache is refreshed with the results.
    """

    def __init__(
        self,
        inner: StockProvider,
        cache: TtlCache[str, Stock],
        logger_factory: LoggerFactory,
        closed_ttl_seconds: int = DEFAULT_CLOSED_CACHE_TTL_SECONDS,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._inner = inner
        self._cache = cache
        self._logger = logger_factory.get_logger(__name__)
        self._closed_ttl = closed_ttl_seconds
        self._now = now

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
                self._cache.put(stock.symbol.upper(), stock, self._ttl_for(stock))
            for symbol in missing:
                stock = fetched.get(symbol.upper())
                if stock is not None:
                    resolved[symbol] = stock

        # Preserve the caller's order and drop unresolved symbols, matching the
        # inner provider's contract (omits symbols with no data).
        return [resolved[symbol] for symbol in symbols if symbol in resolved]

    def _ttl_for(self, stock: Stock) -> int | None:
        # Open/extended-hours quotes use the cache's short default (None = default).
        if stock.market_state != MarketState.CLOSED:
            return None
        # Closed: hold long, but never past the reopen if we know when that is.
        if stock.next_market_open is None:
            return self._closed_ttl
        seconds_to_open = int((stock.next_market_open - self._now()).total_seconds())
        if seconds_to_open <= 0:
            return self._closed_ttl
        return min(self._closed_ttl, seconds_to_open)


class HistorySeriesCache:
    """Caches whole fetched daily series, keyed by Yahoo symbol.

    The per-date caches below stop a *settled* date being re-fetched, but they
    can't stop this: one Yahoo history call returns an entire span, and two
    callers asking for different dates of the same symbol both miss and both
    pay for the full span again. Building an overview does exactly that — each
    portfolio contributes its own transaction dates for the same currency pair,
    and TWR asks again for the cashflow boundaries.

    Requested starts are floored to the start of their year before both the
    lookup and the fetch. Without that, callers whose earliest date differs by
    days keep missing each other and re-fetching near-identical spans; with it
    they share one entry, and pulling from January instead of March costs the
    same single request. A cached series is still only reused when it begins no
    later than the request, so a query reaching into an earlier year re-fetches
    (once) and then serves everyone.

    The series always runs to today and so always ends on an unsettled close —
    hence a short TTL. Collapsing duplicates *within* a request is the point;
    the per-date caches are what make later requests free.
    """

    def __init__(self, cache: TtlCache[str, tuple[date, dict[date, Decimal]]]) -> None:
        self._cache = cache

    def fetch(
        self, key: str, start: date, loader: Callable[[date], dict[date, Decimal]]
    ) -> dict[date, Decimal]:
        floored = date(start.year, 1, 1)
        entry = self._cache.get(key)
        if entry is not None:
            cached_start, series = entry
            if cached_start <= floored:
                return series
        series = loader(floored)
        if series:
            self._cache.put(key, (floored, series))
        return series


class CachedHistoricalPriceProvider(HistoricalPriceProvider):
    """Decorator serving historical close prices from a TtlCache.

    Keyed per `(symbol, date)` rather than per query, so overlapping date sets
    share entries — the same portfolio's transaction dates are re-requested
    several times while building an overview (once per portfolio, again for the
    unified return math, and again for TWR), and every repeat becomes a hit.

    A close for a past date is final, so those entries are held for the cache's
    long default TTL. Dates from today onwards are not settled yet, so they get
    `unsettled_ttl_seconds` (the short quote TTL) instead. Pairs the inner
    provider can't price are left uncached so they're retried next time.
    """

    def __init__(
        self,
        inner: HistoricalPriceProvider,
        cache: TtlCache[tuple[str, date], Decimal],
        logger_factory: LoggerFactory,
        unsettled_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
        today: Callable[[], date] = lambda: datetime.now(timezone.utc).date(),
    ) -> None:
        self._inner = inner
        self._cache = cache
        self._logger = logger_factory.get_logger(__name__)
        self._unsettled_ttl = unsettled_ttl_seconds
        self._today = today

    def get_prices(self, symbols: list[str], dates: list[date]) -> dict[tuple[str, date], Decimal]:
        if not symbols or not dates:
            return {}

        prices: dict[tuple[str, date], Decimal] = {}
        missing_dates_by_symbol: dict[str, list[date]] = {}
        for symbol in dict.fromkeys(symbols):
            for day in dates:
                cached = self._cache.get((symbol, day))
                if cached is not None:
                    prices[(symbol, day)] = cached
                else:
                    missing_dates_by_symbol.setdefault(symbol, []).append(day)

        if missing_dates_by_symbol:
            # One batch for every symbol still missing, over the union of the
            # dates they need — the inner provider fetches a span per symbol
            # anyway, so a narrower per-symbol date list would not save a call.
            missing_dates = sorted(
                {day for days in missing_dates_by_symbol.values() for day in days}
            )
            self._logger.debug(
                f"Historical price cache miss for {len(missing_dates_by_symbol)}/{len(symbols)} "
                f"symbols; fetching"
            )
            fetched = self._inner.get_prices(list(missing_dates_by_symbol), missing_dates)
            for (symbol, day), price in fetched.items():
                self._cache.put((symbol, day), price, self._ttl_for(day))
                if day in missing_dates_by_symbol.get(symbol, ()):
                    prices[(symbol, day)] = price

        return prices

    def _ttl_for(self, day: date) -> int | None:
        # A past close never changes; today's is still moving (None = the
        # cache's long default).
        return None if day < self._today() else self._unsettled_ttl


class CachedHistoricalFxRateProvider(HistoricalFxRateProvider):
    """Decorator serving historical FX rates from a TtlCache.

    The counterpart to CachedHistoricalPriceProvider, keyed per
    `(base, quote, date)`. Same reasoning: past rates are final and held for the
    long default TTL, today's gets the short one, and unavailable pairs stay
    uncached so they're retried.
    """

    def __init__(
        self,
        inner: HistoricalFxRateProvider,
        cache: TtlCache[tuple[Currency, Currency, date], Decimal],
        logger_factory: LoggerFactory,
        unsettled_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
        today: Callable[[], date] = lambda: datetime.now(timezone.utc).date(),
    ) -> None:
        self._inner = inner
        self._cache = cache
        self._logger = logger_factory.get_logger(__name__)
        self._unsettled_ttl = unsettled_ttl_seconds
        self._today = today

    def get_rates(
        self, base: Currency, dates_by_quote: dict[Currency, list[date]]
    ) -> dict[tuple[Currency, date], Decimal]:
        if not dates_by_quote:
            return {}

        rates: dict[tuple[Currency, date], Decimal] = {}
        missing: dict[Currency, list[date]] = {}
        for quote, dates in dates_by_quote.items():
            for day in dict.fromkeys(dates):
                cached = self._cache.get((base, quote, day))
                if cached is not None:
                    rates[(quote, day)] = cached
                else:
                    missing.setdefault(quote, []).append(day)

        if missing:
            self._logger.debug(
                f"Historical FX cache miss for {len(missing)}/{len(dates_by_quote)} quotes; fetching"
            )
            fetched = self._inner.get_rates(base, missing)
            for (quote, day), rate in fetched.items():
                self._cache.put((base, quote, day), rate, self._ttl_for(day))
                rates[(quote, day)] = rate

        return rates

    def _ttl_for(self, day: date) -> int | None:
        return None if day < self._today() else self._unsettled_ttl


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
