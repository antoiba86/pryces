from __future__ import annotations

from decimal import Decimal

from ..application.interfaces import FxRateProvider, LoggerFactory, StockProvider
from ..domain.stocks import Currency


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
