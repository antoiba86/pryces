from __future__ import annotations

import math
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

import pandas as pd
import yfinance as yf

from collections.abc import Callable

from ..application.interfaces import (
    HistoricalPriceProvider,
    LoggerFactory,
    StockProvider,
    StockStatisticsProvider,
)
from ..domain.stock_statistics import HistoricalClose, StatisticsPeriod, StockStatistics
from ..domain.stocks import Currency, InstrumentType, MarketState, Stock

_CURRENCY_ALIASES: dict[str, Currency] = {
    "GBp": Currency.GBP,
}


def map_currency(value: str | None) -> Currency | None:
    if value is None:
        return None
    if value in _CURRENCY_ALIASES:
        return _CURRENCY_ALIASES[value]
    try:
        return Currency(value)
    except ValueError:
        return None


@dataclass(frozen=True, slots=True)
class YahooFinanceSettings:
    max_workers: int
    extra_delay_in_minutes: int


class YahooFinanceMapper:
    def __init__(self, extra_delay_in_minutes: int, logger_factory: LoggerFactory) -> None:
        self._extra_delay_in_minutes = extra_delay_in_minutes
        self._logger = logger_factory.get_logger(__name__)

    def map(self, symbol: str, info: dict) -> Stock | None:
        # yfinance returns a small metadata-only dict (≤3 keys) for invalid/delisted symbols.
        # FX pairs legitimately return small dicts, so let CURRENCY quoteType through.
        if not info or (len(info) <= 3 and info.get("quoteType") != "CURRENCY"):
            self._logger.error(f"No data available for symbol: {symbol}")
            return None

        current_price = None
        for price_key in ["currentPrice", "regularMarketPrice", "previousClose"]:
            if price_key in info and info[price_key] is not None:
                current_price = info[price_key]
                break

        if current_price is None:
            self._logger.error(f"Unable to retrieve current price for symbol: {symbol}")
            return None

        return self._to_stock(symbol, info, current_price)

    def _to_stock(self, symbol: str, info: dict, current_price: float) -> Stock:
        previous_close = info.get("previousClose")
        open_price = info.get("open")
        day_high = info.get("dayHigh")
        day_low = info.get("dayLow")
        fifty_day_avg = info.get("fiftyDayAverage")
        two_hundred_day_avg = info.get("twoHundredDayAverage")
        fifty_two_week_high = info.get("fiftyTwoWeekHigh")
        fifty_two_week_low = info.get("fiftyTwoWeekLow")
        market_cap = info.get("marketCap")
        company_name = info.get("longName") or info.get("shortName")
        currency = self._map_currency(info.get("currency"))
        market_state = self._map_market_state(info.get("marketState"))
        exchange_delay = info.get("exchangeDataDelayedBy") or 0
        price_delay_in_minutes = exchange_delay + self._extra_delay_in_minutes
        kind = self._map_instrument_type(info.get("quoteType"))

        return Stock(
            symbol=symbol.upper(),
            current_price=Decimal(str(current_price)),
            name=company_name,
            currency=currency,
            previous_close_price=(
                Decimal(str(previous_close)) if previous_close is not None else None
            ),
            open_price=Decimal(str(open_price)) if open_price is not None else None,
            day_high=Decimal(str(day_high)) if day_high is not None else None,
            day_low=Decimal(str(day_low)) if day_low is not None else None,
            fifty_day_average=Decimal(str(fifty_day_avg)) if fifty_day_avg is not None else None,
            two_hundred_day_average=(
                Decimal(str(two_hundred_day_avg)) if two_hundred_day_avg is not None else None
            ),
            fifty_two_week_high=(
                Decimal(str(fifty_two_week_high)) if fifty_two_week_high is not None else None
            ),
            fifty_two_week_low=(
                Decimal(str(fifty_two_week_low)) if fifty_two_week_low is not None else None
            ),
            market_cap=Decimal(str(market_cap)) if market_cap is not None else None,
            market_state=market_state,
            price_delay_in_minutes=price_delay_in_minutes,
            kind=kind,
        )

    def _map_instrument_type(self, value: str | None) -> InstrumentType | None:
        mapping = {
            "EQUITY": InstrumentType.STOCK,
            "ETF": InstrumentType.ETF,
            "CRYPTOCURRENCY": InstrumentType.CRYPTO,
            "INDEX": InstrumentType.INDEX,
            "CURRENCY": InstrumentType.FX,
        }
        if value is None:
            return None
        return mapping.get(value)

    def _map_currency(self, value: str | None) -> Currency | None:
        return map_currency(value)

    def _map_market_state(self, value: str | None) -> MarketState | None:
        match value:
            case "REGULAR":
                return MarketState.OPEN
            case "PRE" | "PREPRE":
                return MarketState.PRE
            case "POST" | "POSTPOST":
                return MarketState.POST
            case "CLOSED":
                return MarketState.CLOSED
            case None:
                return None
            case _:
                self._logger.warning(f"Unknown market state: {value}")
                return None


class YahooFinanceProvider(StockProvider):
    def __init__(self, settings: YahooFinanceSettings, logger_factory: LoggerFactory) -> None:
        self._max_workers = settings.max_workers
        self._mapper = YahooFinanceMapper(settings.extra_delay_in_minutes, logger_factory)
        self._logger = logger_factory.get_logger(__name__)

    def _get_stock(self, symbol: str) -> Stock | None:
        try:
            self._logger.debug(f"Fetching stock data for {symbol}")
            ticker_obj = yf.Ticker(symbol)
            info = ticker_obj.info
            stock = self._mapper.map(symbol, info)
            del info, ticker_obj
            return stock
        except Exception as e:
            self._logger.error(f"Error fetching data for {symbol}: {e}")
            return None

    def get_stocks(self, symbols: list[str]) -> list[Stock]:
        if not symbols:
            return []

        with ThreadPoolExecutor(max_workers=min(len(symbols), self._max_workers)) as executor:
            results = list(executor.map(self._get_stock, symbols))

        return [stock for stock in results if stock is not None]


_PERIOD_DELTAS: dict[StatisticsPeriod, timedelta | None] = {
    StatisticsPeriod.ONE_DAY: timedelta(days=1),
    StatisticsPeriod.ONE_WEEK: timedelta(weeks=1),
    StatisticsPeriod.THREE_MONTHS: timedelta(days=90),
    StatisticsPeriod.ONE_YEAR: timedelta(days=365),
    StatisticsPeriod.YEAR_TO_DATE: None,
}


class YahooFinanceStatisticsMapper:
    def __init__(self, logger_factory: LoggerFactory) -> None:
        self._logger = logger_factory.get_logger(__name__)

    def map(self, symbol: str, info: dict, history: pd.DataFrame) -> StockStatistics | None:
        if not info or len(info) <= 3:
            self._logger.error(f"No data available for symbol: {symbol}")
            return None

        if history.empty:
            self._logger.error(f"No historical data available for symbol: {symbol}")
            return None

        last_trading_date = history.index[-1].date()
        raw_current_price = history.iloc[-1]["Close"]
        if math.isnan(raw_current_price):
            self._logger.error(f"Current price is NaN for symbol: {symbol}")
            return None
        current_price = Decimal(str(raw_current_price))

        return StockStatistics(
            symbol=symbol.upper(),
            current_price=current_price,
            historical_closes=self._build_historical_closes(history, last_trading_date),
            name=info.get("longName") or info.get("shortName"),
            currency=map_currency(info.get("currency")),
        )

    def _build_historical_closes(
        self, history: pd.DataFrame, last_trading_date: date
    ) -> list[HistoricalClose]:
        closes: list[HistoricalClose] = []

        for period, delta in _PERIOD_DELTAS.items():
            if delta is not None:
                target_date = last_trading_date - delta
            else:
                target_date = date(last_trading_date.year - 1, 12, 31)

            subset = history[history.index.date <= target_date]
            if subset.empty:
                continue

            close_price = subset.iloc[-1]["Close"]
            if math.isnan(close_price):
                continue
            closes.append(
                HistoricalClose(
                    period=period,
                    close_price=Decimal(str(close_price)),
                )
            )

        return closes


class YahooFinanceStatisticsProvider(StockStatisticsProvider):
    def __init__(self, settings: YahooFinanceSettings, logger_factory: LoggerFactory) -> None:
        self._max_workers = settings.max_workers
        self._mapper = YahooFinanceStatisticsMapper(logger_factory)
        self._logger = logger_factory.get_logger(__name__)

    def _get_stock_statistics(self, symbol: str) -> StockStatistics | None:
        try:
            self._logger.debug(f"Fetching stock statistics for {symbol}")
            ticker_obj = yf.Ticker(symbol)
            info = ticker_obj.info
            history = ticker_obj.history(start=date.today() - timedelta(days=400))
            stats = self._mapper.map(symbol, info, history)
            del info, history, ticker_obj
            return stats
        except Exception as e:
            self._logger.error(f"Error fetching statistics for {symbol}: {e}")
            return None

    def get_stock_statistics(self, symbols: list[str]) -> list[StockStatistics]:
        if not symbols:
            return []

        with ThreadPoolExecutor(max_workers=min(len(symbols), self._max_workers)) as executor:
            results = list(executor.map(self._get_stock_statistics, symbols))

        return [stats for stats in results if stats is not None]


# Fetches a daily close series for a Yahoo symbol from `start` to today.
PriceHistoryFetcher = Callable[[str, date], dict[date, Decimal]]


class YahooFinanceHistoricalPriceProvider(HistoricalPriceProvider):
    """Date-accurate close prices from Yahoo Finance daily history.

    Fetches a symbol's close series once over the requested span and resolves
    each requested date to its nearest prior trading day (weekends/holidays
    fall back to the last available close; dates before the series start use
    the earliest). Symbols that can't be fetched yield no prices. Injects an
    optional `history_fetcher` for testing.
    """

    def __init__(
        self,
        logger_factory: LoggerFactory,
        history_fetcher: PriceHistoryFetcher | None = None,
    ) -> None:
        self._logger = logger_factory.get_logger(__name__)
        self._fetch = history_fetcher if history_fetcher is not None else _yahoo_price_history

    def get_prices(self, symbol: str, dates: list[date]) -> dict[date, Decimal]:
        if not dates:
            return {}
        series = self._fetch(symbol, min(dates))
        if not series:
            self._logger.warning(f"No historical prices for {symbol}")
            return {}
        ordered = sorted(series.items())
        return {day: price for day in dates if (price := _nearest_prior_price(ordered, day))}


def _nearest_prior_price(ordered: list[tuple[date, Decimal]], target: date) -> Decimal | None:
    chosen: Decimal | None = None
    for day, price in ordered:
        if day <= target:
            chosen = price
        else:
            break
    if chosen is None and ordered:
        return ordered[0][1]
    return chosen


def _yahoo_price_history(symbol: str, start: date) -> dict[date, Decimal]:
    history = yf.Ticker(symbol).history(start=start.isoformat())
    if history.empty or "Close" not in history:
        return {}
    return {
        timestamp.date(): Decimal(str(close))
        for timestamp, close in history["Close"].items()
        if close == close  # skip NaN
    }
