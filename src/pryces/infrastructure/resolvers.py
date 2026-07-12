from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path

from ..application.interfaces import LoggerFactory, StockProvider, SymbolResolver
from ..domain.portfolio.transactions import Instrument
from ..domain.stocks import Currency
from .repositories import resolve_data_dir

SYMBOL_MAP_FILENAME = "symbol_map.json"
_SEARCH_URL = "https://query2.finance.yahoo.com/v1/finance/search"
_USER_AGENT = "Mozilla/5.0 (compatible; pryces/1.0)"
_ISIN_PATTERN = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")
# Yahoo quoteTypes we treat as resolvable holdings: shares, ETFs, and mutual funds
# (funds price by NAV exactly like a stock position).
_RESOLVABLE_QUOTE_TYPES = {"EQUITY", "ETF", "MUTUALFUND"}

# DEGIRO reference-exchange code → the Yahoo `exchange` codes that represent the
# same venue, used to disambiguate when a name/ISIN search returns several
# listings of the same instrument.
_EXCHANGE_ALIASES: dict[str, set[str]] = {
    "NDQ": {"NMS", "NGM", "NCM"},
    "NSY": {"NYQ", "PCX", "ASE"},
    "MAD": {"MCE"},
    "EAM": {"AMS"},
    "EPA": {"PAR"},
    "FRA": {"GER", "FRA"},
    "XET": {"GER"},
    "LSE": {"LSE"},
    "MIL": {"MIL"},
    "SWX": {"EBS"},
}

# Trade currency → the Yahoo `exchange` codes for that currency's home market(s),
# used to disambiguate when no exchange code is available (e.g. IBKR rows). A
# single-venue currency like AUD pins the ASX listing over a US OTC cross-listing.
# EUR is intentionally omitted: it spans many venues, so it gives no useful hint.
_CURRENCY_EXCHANGES: dict[Currency, set[str]] = {
    Currency.AUD: {"ASX"},
    Currency.GBP: {"LSE"},
    Currency.CAD: {"TOR"},
    Currency.HKD: {"HKG"},
    Currency.JPY: {"JPX", "TYO"},
    Currency.KRW: {"KSC", "KOE"},
    Currency.USD: {"NMS", "NGM", "NCM", "NYQ", "PCX", "ASE", "BTS", "NAS"},
}

# Trailing share-class / currency tokens that make a broker product name too
# specific for Yahoo's name search (stripped to broaden the fallback query).
_NAME_NOISE = {
    "USD",
    "EUR",
    "GBP",
    "CHF",
    "JPY",
    "CAD",
    "AUD",
    "ACC",
    "DIS",
    "DIST",
    "INC",
    "DISTRIBUTING",
    "ACCUMULATING",
    "HEDGED",
}

SearchFn = Callable[[str], list[dict]]


def _is_isin(value: str) -> bool:
    return bool(_ISIN_PATTERN.match(value.strip().upper()))


def _trimmed_name(name: str | None) -> str | None:
    if not name:
        return None
    tokens = name.split()
    while tokens and tokens[-1].upper().strip(".") in _NAME_NOISE:
        tokens.pop()
    trimmed = " ".join(tokens)
    return trimmed if trimmed and trimmed != name else None


class JsonSymbolMap:
    """User-editable ISIN/symbol → Yahoo ticker cache, stored as one JSON file.

    Keys are uppercased (ISINs for broker imports). The file lives in the
    Pryces data dir and is meant to be hand-corrected when a guess is wrong;
    writes are atomic via tmp-file + os.replace.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = path if path is not None else resolve_data_dir() / SYMBOL_MAP_FILENAME

    def get(self, key: str) -> str | None:
        return self._load().get(key.strip().upper())

    def put(self, key: str, ticker: str) -> None:
        mapping = self._load()
        mapping[key.strip().upper()] = ticker
        self._write(mapping)

    def _load(self) -> dict[str, str]:
        if not self._path.exists():
            return {}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError, OSError):
            return {}
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}

    def _write(self, mapping: dict[str, str]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps(mapping, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self._path)


class YahooSymbolResolver(SymbolResolver):
    """Resolves an Instrument to a Yahoo ticker via Yahoo Finance search.

    Queries by ISIN first (most precise) and falls back to the product name,
    then disambiguates among candidates using the instrument's reference
    exchange. Instruments whose symbol is already a plain ticker (no ISIN, no
    name) pass through unchanged. Any network/parse failure yields None.
    """

    def __init__(
        self,
        logger_factory: LoggerFactory,
        search: SearchFn | None = None,
        stock_provider: StockProvider | None = None,
    ) -> None:
        self._logger = logger_factory.get_logger(__name__)
        self._search = search if search is not None else _yahoo_search
        # Optional: when supplied, candidates are disambiguated by their *actual*
        # quote currency (the search API omits currency), so an instrument with a
        # known currency resolves to a listing in that currency.
        self._stock_provider = stock_provider

    def resolve(self, instrument: Instrument) -> str | None:
        isin = instrument.isin or (instrument.symbol if _is_isin(instrument.symbol) else None)
        if isin is None and not instrument.name:
            # Already a usable ticker (e.g. from the JSON ledger).
            return instrument.symbol

        # Scan every query for a candidate on the instrument's own exchange
        # first; a venue match anywhere beats the first hit of an earlier query
        # (e.g. an ISIN search that only surfaces a foreign cross-listing). Only
        # if no query yields an exchange match do we fall back to the first
        # equity seen.
        fallback: str | None = None
        by_currency: str | None = None
        for query in self._queries(isin, instrument.symbol, instrument.name):
            equities = self._equities(query)
            if not equities:
                continue
            matched = self._match_exchange(equities, instrument.exchange)
            if matched is not None:
                return matched.get("symbol")
            # Prefer a listing actually quoted in the instrument's currency. The
            # search API omits currency, so this verifies it against the live
            # quote — pinning e.g. a EUR-settled ETF to its EUR listing instead
            # of an arbitrary MXN/USD cross-listing Yahoo happens to return first.
            ccy_match = self._match_quote_currency(equities, instrument.currency)
            if ccy_match is not None:
                return ccy_match
            if by_currency is None:
                currency_match = self._match_currency(equities, instrument.currency)
                if currency_match is not None:
                    by_currency = currency_match.get("symbol")
            if fallback is None:
                fallback = equities[0].get("symbol")
        # Exchange match wins; a currency-home-market match is the next-best
        # signal (pins e.g. an AUD trade to ASX); first equity is the last resort.
        resolved = by_currency or fallback
        if resolved is not None:
            return resolved
        self._logger.warning(f"Could not resolve a Yahoo symbol for {isin or instrument.symbol}")
        return None

    @staticmethod
    def _queries(isin: str | None, symbol: str | None, name: str | None) -> list[str]:
        # Order matters (first hit wins on ties): ISIN is most precise; the raw
        # broker symbol is next (IBKR gives the real exchange ticker, e.g. "TTT",
        # which surfaces the home-market listing that a verbose name search
        # misses); then the product name and a trimmed variant of it (broker
        # names like "... UCITS ETF USD DIS" are too specific, so trimming the
        # trailing share-class/currency tokens broadens the cross-listing set).
        symbol_query = symbol if symbol and not _is_isin(symbol) else None
        queries = [isin, symbol_query, name, _trimmed_name(name)]
        return list(dict.fromkeys(value for value in queries if value))

    def _equities(self, query: str) -> list[dict]:
        try:
            candidates = self._search(query)
        except (urllib.error.URLError, OSError, ValueError) as error:
            self._logger.warning(f"Yahoo search failed for {query!r}: {error}")
            return []
        return [
            quote
            for quote in candidates
            if quote.get("quoteType", "").upper() in _RESOLVABLE_QUOTE_TYPES and quote.get("symbol")
        ]

    @staticmethod
    def _match_exchange(equities: list[dict], exchange: str | None) -> dict | None:
        if not exchange:
            return None
        allowed = _EXCHANGE_ALIASES.get(exchange.strip().upper())
        if not allowed:
            return None
        for quote in equities:
            if quote.get("exchange", "").upper() in allowed:
                return quote
        return None

    def _match_quote_currency(self, equities: list[dict], currency: Currency | None) -> str | None:
        # Needs a known target currency and a provider to read each candidate's
        # real currency; without either, this is a no-op (legacy behaviour).
        if currency is None or self._stock_provider is None:
            return None
        symbols = [quote["symbol"] for quote in equities if quote.get("symbol")]
        if not symbols:
            return None
        stocks = {stock.symbol.upper(): stock for stock in self._stock_provider.get_stocks(symbols)}
        # Return the first candidate (search order) genuinely quoted in `currency`.
        for quote in equities:
            stock = stocks.get((quote.get("symbol") or "").upper())
            if stock is not None and stock.currency == currency:
                return quote.get("symbol")
        return None

    @staticmethod
    def _match_currency(equities: list[dict], currency: Currency | None) -> dict | None:
        if currency is None:
            return None
        allowed = _CURRENCY_EXCHANGES.get(currency)
        if not allowed:
            return None
        for quote in equities:
            if quote.get("exchange", "").upper() in allowed:
                return quote
        return None


class CachedSymbolResolver(SymbolResolver):
    """Decorator that serves resolutions from a JsonSymbolMap before the network.

    Looks the instrument up in the map (by ISIN, else symbol); on a miss it
    delegates to the wrapped resolver and records any genuine resolution (one
    that differs from the lookup key) so it is reused and remains editable.
    """

    def __init__(
        self,
        inner: SymbolResolver,
        symbol_map: JsonSymbolMap,
        logger_factory: LoggerFactory,
    ) -> None:
        self._inner = inner
        self._map = symbol_map
        self._logger = logger_factory.get_logger(__name__)

    def resolve(self, instrument: Instrument) -> str | None:
        key = instrument.isin or instrument.symbol
        cached = self._map.get(key)
        if cached is not None:
            return cached
        resolved = self._inner.resolve(instrument)
        if resolved is not None and resolved != key:
            self._map.put(key, resolved)
            self._logger.info(f"Resolved {key} -> {resolved}")
        return resolved


def _yahoo_search(query: str) -> list[dict]:
    params = urllib.parse.urlencode({"q": query, "quotesCount": 10, "newsCount": 0})
    request = urllib.request.Request(f"{_SEARCH_URL}?{params}", headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))
    quotes = payload.get("quotes", [])
    return quotes if isinstance(quotes, list) else []
