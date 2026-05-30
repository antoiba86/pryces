import urllib.error

from pryces.domain.portfolio.transactions import Instrument
from pryces.infrastructure.resolvers import (
    CachedSymbolResolver,
    JsonSymbolMap,
    YahooSymbolResolver,
)


class _StubLogger:
    def debug(self, message): ...

    def info(self, message): ...

    def warning(self, message): ...

    def error(self, message): ...


class _StubLoggerFactory:
    def get_logger(self, name):
        return _StubLogger()


def _quote(symbol, exchange="NMS", quote_type="EQUITY"):
    return {"symbol": symbol, "exchange": exchange, "quoteType": quote_type}


class TestJsonSymbolMap:

    def test_put_then_get_roundtrips(self, tmp_path):
        symbol_map = JsonSymbolMap(tmp_path / "symbol_map.json")

        symbol_map.put("US0378331005", "AAPL")

        assert symbol_map.get("US0378331005") == "AAPL"

    def test_keys_are_case_insensitive(self, tmp_path):
        symbol_map = JsonSymbolMap(tmp_path / "symbol_map.json")
        symbol_map.put("us0378331005", "AAPL")

        assert symbol_map.get("US0378331005") == "AAPL"

    def test_missing_file_returns_none(self, tmp_path):
        symbol_map = JsonSymbolMap(tmp_path / "absent.json")

        assert symbol_map.get("US0378331005") is None


class TestYahooSymbolResolver:

    def _resolver(self, search):
        return YahooSymbolResolver(_StubLoggerFactory(), search=search)

    def test_passes_through_plain_ticker(self):
        calls = []
        resolver = self._resolver(lambda q: calls.append(q) or [])

        result = resolver.resolve(Instrument(symbol="AAPL"))

        assert result == "AAPL"
        assert calls == []  # no network for an already-resolved ticker

    def test_queries_isin_first(self):
        seen = []

        def search(query):
            seen.append(query)
            return [_quote("IONQ")]

        resolver = self._resolver(search)
        result = resolver.resolve(
            Instrument(symbol="US46222L1089", name="IONQ INC", isin="US46222L1089")
        )

        assert result == "IONQ"
        assert seen[0] == "US46222L1089"

    def test_falls_back_to_name_when_isin_yields_nothing(self):
        def search(query):
            return [_quote("FOO")] if query == "FOO INC" else []

        resolver = self._resolver(search)
        result = resolver.resolve(
            Instrument(symbol="US0000000001", name="FOO INC", isin="US0000000001")
        )

        assert result == "FOO"

    def test_disambiguates_by_exchange(self):
        def search(query):
            return [_quote("VYTR.F", exchange="FRA"), _quote("VYTR.MC", exchange="MCE")]

        resolver = self._resolver(search)
        result = resolver.resolve(
            Instrument(symbol="ES0105618005", name="VYTRUS", exchange="MAD", isin="ES0105618005")
        )

        assert result == "VYTR.MC"

    def test_prefers_exchange_match_from_trimmed_name_over_isin_hit(self):
        # ISIN search only surfaces a foreign cross-listing; the trimmed name
        # (verbose share-class suffix stripped) surfaces the home-exchange one.
        def search(query):
            if query == "IE00B3XXRP09":
                return [_quote("VUSD.L", exchange="LSE", quote_type="ETF")]
            if query == "VANGUARD S&P 500 UCITS ETF":
                return [
                    _quote("VUSD.L", exchange="LSE", quote_type="ETF"),
                    _quote("VUSA.AS", exchange="AMS", quote_type="ETF"),
                ]
            return []

        resolver = self._resolver(search)
        result = resolver.resolve(
            Instrument(
                symbol="IE00B3XXRP09",
                name="VANGUARD S&P 500 UCITS ETF USD DIS",
                exchange="EAM",
                isin="IE00B3XXRP09",
            )
        )

        assert result == "VUSA.AS"

    def test_returns_first_equity_when_exchange_unmatched(self):
        def search(query):
            return [_quote("BAR.XX", exchange="ZZZ"), _quote("BAR.YY", exchange="WWW")]

        resolver = self._resolver(search)
        result = resolver.resolve(
            Instrument(symbol="US0000000002", exchange="MAD", isin="US0000000002")
        )

        assert result == "BAR.XX"

    def test_ignores_non_equity_quotes(self):
        def search(query):
            return [_quote("X", quote_type="CURRENCY"), _quote("REAL", quote_type="EQUITY")]

        resolver = self._resolver(search)
        result = resolver.resolve(Instrument(symbol="US0000000003", isin="US0000000003"))

        assert result == "REAL"

    def test_returns_none_on_search_error(self):
        def search(query):
            raise urllib.error.URLError("boom")

        resolver = self._resolver(search)
        result = resolver.resolve(Instrument(symbol="US0000000004", isin="US0000000004"))

        assert result is None


class TestCachedSymbolResolver:

    class _RecordingResolver:
        def __init__(self, result):
            self.result = result
            self.calls = 0

        def resolve(self, instrument):
            self.calls += 1
            return self.result

    def test_cache_hit_skips_inner(self, tmp_path):
        symbol_map = JsonSymbolMap(tmp_path / "m.json")
        symbol_map.put("US0378331005", "AAPL")
        inner = self._RecordingResolver("WRONG")
        resolver = CachedSymbolResolver(inner, symbol_map, _StubLoggerFactory())

        result = resolver.resolve(Instrument(symbol="US0378331005", isin="US0378331005"))

        assert result == "AAPL"
        assert inner.calls == 0

    def test_cache_miss_delegates_and_stores(self, tmp_path):
        symbol_map = JsonSymbolMap(tmp_path / "m.json")
        inner = self._RecordingResolver("IONQ")
        resolver = CachedSymbolResolver(inner, symbol_map, _StubLoggerFactory())

        result = resolver.resolve(Instrument(symbol="US46222L1089", isin="US46222L1089"))

        assert result == "IONQ"
        assert inner.calls == 1
        assert symbol_map.get("US46222L1089") == "IONQ"

    def test_passthrough_resolution_is_not_cached(self, tmp_path):
        symbol_map = JsonSymbolMap(tmp_path / "m.json")
        inner = self._RecordingResolver("AAPL")
        resolver = CachedSymbolResolver(inner, symbol_map, _StubLoggerFactory())

        resolver.resolve(Instrument(symbol="AAPL"))

        assert symbol_map.get("AAPL") is None
