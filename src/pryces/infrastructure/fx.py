from __future__ import annotations

from collections.abc import Callable
from datetime import date
from decimal import Decimal

from ..application.interfaces import (
    FxRateProvider,
    HistoricalFxRateProvider,
    LoggerFactory,
    StockProvider,
)
from ..domain.stocks import Currency

# Fetches a daily close series for a Yahoo FX symbol from `start` to today.
HistoryFetcher = Callable[[str, date], dict[date, Decimal]]


class YahooFinanceFxProvider(FxRateProvider):
    """FX rates via Yahoo Finance currency pairs.

    Tries the direct pair ({quote}{base}=X) first, then falls back to the
    inverted pair ({base}{quote}=X) and inverts the price. Currencies for
    which neither lookup succeeds are silently omitted from the result.
    """

    def __init__(self, stock_provider: StockProvider, logger_factory: LoggerFactory) -> None:
        self._provider = stock_provider
        self._logger = logger_factory.get_logger(__name__)

    def get_rates(self, base: Currency, quotes: list[Currency]) -> dict[Currency, Decimal]:
        rates: dict[Currency, Decimal] = {}
        needed: list[Currency] = []
        for quote in quotes:
            if quote == base:
                rates[quote] = Decimal("1")
                continue
            if quote not in rates and quote not in needed:
                needed.append(quote)

        if not needed:
            return rates

        direct_lookup = {self._direct_symbol(q, base): q for q in needed}
        direct_results = self._fetch(list(direct_lookup.keys()))
        still_needed: list[Currency] = []
        for symbol, quote in direct_lookup.items():
            stock = direct_results.get(symbol)
            if stock is not None and stock.current_price > 0:
                rates[quote] = stock.current_price
            else:
                still_needed.append(quote)

        if not still_needed:
            return rates

        inverted_lookup = {self._inverted_symbol(q, base): q for q in still_needed}
        inverted_results = self._fetch(list(inverted_lookup.keys()))
        for symbol, quote in inverted_lookup.items():
            stock = inverted_results.get(symbol)
            if stock is not None and stock.current_price > 0:
                rates[quote] = Decimal("1") / stock.current_price
            else:
                self._logger.warning(f"No FX rate available for {quote.value} -> {base.value}")

        return rates

    def _fetch(self, symbols: list[str]) -> dict[str, object]:
        if not symbols:
            return {}
        results = self._provider.get_stocks(symbols)
        return {stock.symbol: stock for stock in results}

    @staticmethod
    def _direct_symbol(quote: Currency, base: Currency) -> str:
        return f"{quote.value}{base.value}=X"

    @staticmethod
    def _inverted_symbol(quote: Currency, base: Currency) -> str:
        return f"{base.value}{quote.value}=X"


class YahooFinanceHistoricalFxProvider(HistoricalFxRateProvider):
    """Date-accurate FX rates from Yahoo Finance daily history.

    Fetches each pair's close series once over the requested span (direct
    `{quote}{base}=X`, else inverted `{base}{quote}=X` with prices inverted) and
    resolves each requested date to its nearest prior trading day — so weekends
    and holidays fall back to the last available rate. Pairs that can't be
    fetched yield no rates for that quote. Injects an optional `history_fetcher`
    for testing.
    """

    def __init__(
        self,
        logger_factory: LoggerFactory,
        history_fetcher: HistoryFetcher | None = None,
    ) -> None:
        self._logger = logger_factory.get_logger(__name__)
        self._fetch = history_fetcher if history_fetcher is not None else _yahoo_fx_history

    def get_rates(self, base: Currency, quote: Currency, dates: list[date]) -> dict[date, Decimal]:
        if quote == base:
            return {day: Decimal("1") for day in dates}
        if not dates:
            return {}

        series = self._fetch_series(base, quote, min(dates))
        if not series:
            self._logger.warning(f"No historical FX rates for {quote.value} -> {base.value}")
            return {}

        ordered = sorted(series.items())
        return {day: rate for day in dates if (rate := _nearest_prior(ordered, day)) is not None}

    def _fetch_series(self, base: Currency, quote: Currency, start: date) -> dict[date, Decimal]:
        direct = self._fetch(f"{quote.value}{base.value}=X", start)
        if direct:
            return direct
        inverted = self._fetch(f"{base.value}{quote.value}=X", start)
        return {day: Decimal("1") / price for day, price in inverted.items() if price > 0}


def _nearest_prior(ordered: list[tuple[date, Decimal]], target: date) -> Decimal | None:
    chosen: Decimal | None = None
    for day, rate in ordered:
        if day <= target:
            chosen = rate
        else:
            break
    # Fall back to the earliest available rate for dates before the series starts.
    if chosen is None and ordered:
        return ordered[0][1]
    return chosen


def _yahoo_fx_history(symbol: str, start: date) -> dict[date, Decimal]:
    import yfinance

    history = yfinance.Ticker(symbol).history(start=start.isoformat())
    if history.empty or "Close" not in history:
        return {}
    return {
        timestamp.date(): Decimal(str(close))
        for timestamp, close in history["Close"].items()
        if close == close  # skip NaN
    }
