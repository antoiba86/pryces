import urllib.error

from pryces.domain.portfolio.transactions import Instrument
from pryces.domain.stocks import Currency
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


class _FakeStockProvider:
    """Returns a Stock per requested symbol with a preset currency (or None)."""

    def __init__(self, currencies: dict[str, "Currency | None"]) -> None:
        self._currencies = currencies
        self.calls: list[list[str]] = []

    def get_stocks(self, symbols, use_cache: bool = True):
        from decimal import Decimal

        from pryces.domain.stocks import Stock

        self.calls.append(list(symbols))
        return [
            Stock(symbol=s, current_price=Decimal("1"), currency=self._currencies.get(s))
            for s in symbols
        ]


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

    def test_all_returns_every_entry(self, tmp_path):
        symbol_map = JsonSymbolMap(tmp_path / "symbol_map.json")
        symbol_map.put("US0378331005", "AAPL")
        symbol_map.put("HOROS VALUE INTERNACIONAL, FI", "0P0001DFE8.F")

        assert symbol_map.all() == {
            "US0378331005": "AAPL",
            "HOROS VALUE INTERNACIONAL, FI": "0P0001DFE8.F",
        }

    def test_all_on_a_missing_file_is_empty(self, tmp_path):
        assert JsonSymbolMap(tmp_path / "absent.json").all() == {}

    def test_delete_removes_the_entry(self, tmp_path):
        symbol_map = JsonSymbolMap(tmp_path / "symbol_map.json")
        symbol_map.put("US0378331005", "AAPL")

        assert symbol_map.delete("us0378331005") is True
        assert symbol_map.get("US0378331005") is None

    def test_delete_reports_a_key_that_was_not_mapped(self, tmp_path):
        symbol_map = JsonSymbolMap(tmp_path / "symbol_map.json")

        assert symbol_map.delete("US0378331005") is False

    def test_put_trims_the_ticker(self, tmp_path):
        symbol_map = JsonSymbolMap(tmp_path / "symbol_map.json")

        symbol_map.put("US0378331005", "  AAPL  ")

        assert symbol_map.get("US0378331005") == "AAPL"


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

    def test_disambiguates_by_currency_when_no_exchange_hint(self):
        # IBKR gives no exchange code; an AUD trade must pin the ASX listing
        # rather than the US OTC cross-listing that search may surface first.
        def search(query):
            if query == "TTT":
                return [
                    _quote("TITMF", exchange="PNK"),
                    _quote("TTT.AX", exchange="ASX"),
                ]
            return []

        resolver = self._resolver(search)
        result = resolver.resolve(
            Instrument(symbol="TTT", name="TITOMIC LTD", currency=Currency.AUD)
        )

        assert result == "TTT.AX"

    def test_currency_hint_ignored_for_eur_multi_venue(self):
        # EUR spans many venues, so it gives no useful hint: first equity wins.
        def search(query):
            return [_quote("AAA.DE", exchange="GER"), _quote("AAA.AS", exchange="AMS")]

        resolver = self._resolver(search)
        result = resolver.resolve(
            Instrument(symbol="AAA", name="SOME EURO CO", currency=Currency.EUR)
        )

        assert result == "AAA.DE"

    def test_exchange_match_beats_currency_match(self):
        def search(query):
            return [_quote("FOO.AX", exchange="ASX"), _quote("FOO.MC", exchange="MCE")]

        resolver = self._resolver(search)
        result = resolver.resolve(
            Instrument(
                symbol="ES0000000001",
                name="FOO",
                exchange="MAD",
                isin="ES0000000001",
                currency=Currency.AUD,
            )
        )

        assert result == "FOO.MC"

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

    def test_resolves_mutual_funds(self):
        # A fund ISIN search returns only a MUTUALFUND quote; it must resolve
        # (funds price by NAV like a normal position).
        def search(query):
            return [_quote("0P000168OI.F", exchange="FRA", quote_type="MUTUALFUND")]

        resolver = self._resolver(search)
        result = resolver.resolve(
            Instrument(symbol="ES0173311103", name="R4 Numantia", isin="ES0173311103")
        )

        assert result == "0P000168OI.F"

    def test_returns_none_on_search_error(self):
        def search(query):
            raise urllib.error.URLError("boom")

        resolver = self._resolver(search)
        result = resolver.resolve(Instrument(symbol="US0000000004", isin="US0000000004"))

        assert result is None

    def test_prefers_listing_in_instrument_currency_via_quote(self):
        # The Trade Republic case: ISIN search lists an MXN and a USD cross-listing
        # before the EUR one. With a provider to read each candidate's real
        # currency, the EUR-settled instrument resolves to its EUR listing.
        def search(query):
            if query == "FR0013416716":
                return [
                    _quote("AMGOLDN.MX", exchange="MEX", quote_type="ETF"),
                    _quote("GLDA.SG", exchange="STU", quote_type="ETF"),
                    _quote("GOLD.AS", exchange="AMS", quote_type="ETF"),
                ]
            return []

        provider = _FakeStockProvider(
            {"AMGOLDN.MX": None, "GLDA.SG": Currency.EUR, "GOLD.AS": Currency.USD}
        )
        resolver = YahooSymbolResolver(_StubLoggerFactory(), search=search, stock_provider=provider)
        result = resolver.resolve(
            Instrument(
                symbol="FR0013416716",
                name="Physical Gold",
                isin="FR0013416716",
                currency=Currency.EUR,
            )
        )

        assert result == "GLDA.SG"

    def test_quote_currency_match_overrides_first_equity_fallback(self):
        # Without a provider, EUR can't disambiguate and the first equity wins
        # (see test_currency_hint_ignored_for_eur_multi_venue). With one, the
        # listing actually quoted in EUR is chosen instead.
        def search(query):
            return [_quote("MXWO.L", exchange="LSE"), _quote("SC0J.DE", exchange="GER")]

        provider = _FakeStockProvider({"MXWO.L": Currency.USD, "SC0J.DE": Currency.EUR})
        resolver = YahooSymbolResolver(_StubLoggerFactory(), search=search, stock_provider=provider)
        result = resolver.resolve(
            Instrument(symbol="IE00B60SX394", isin="IE00B60SX394", currency=Currency.EUR)
        )

        assert result == "SC0J.DE"

    def test_exchange_hint_skips_currency_quote_lookup(self):
        # When the exchange hint resolves it (DEGIRO), no quote lookup is needed.
        def search(query):
            return [_quote("FOO.MC", exchange="MCE"), _quote("FOO.F", exchange="FRA")]

        provider = _FakeStockProvider({"FOO.MC": Currency.EUR, "FOO.F": Currency.EUR})
        resolver = YahooSymbolResolver(_StubLoggerFactory(), search=search, stock_provider=provider)
        result = resolver.resolve(
            Instrument(
                symbol="ES0000000001",
                exchange="MAD",
                isin="ES0000000001",
                currency=Currency.EUR,
            )
        )

        assert result == "FOO.MC"
        assert provider.calls == []  # exchange match returned before any quote fetch

    def test_falls_back_to_first_equity_when_no_currency_matches(self):
        def search(query):
            return [_quote("AAA.L", exchange="LSE"), _quote("BBB.MX", exchange="MEX")]

        provider = _FakeStockProvider({"AAA.L": Currency.USD, "BBB.MX": None})
        resolver = YahooSymbolResolver(_StubLoggerFactory(), search=search, stock_provider=provider)
        result = resolver.resolve(
            Instrument(symbol="X0000000001", isin="X0000000001", currency=Currency.EUR)
        )

        assert result == "AAA.L"  # no EUR candidate → first equity, as before

    def test_venue_match_in_later_query_beats_earlier_quote_currency_match(self):
        # DEGIRO-style instrument with an exchange hint: the ISIN query only
        # surfaces foreign listings (one quoted in EUR), but the name query
        # surfaces the reference-venue listing — the venue must still win.
        def search(query):
            if query == "ES0000000001":
                return [_quote("FOO.DE", exchange="GER"), _quote("FOO.L", exchange="LSE")]
            if query == "Foo Corp":
                return [_quote("FOO.MC", exchange="MCE")]
            return []

        provider = _FakeStockProvider({"FOO.DE": Currency.EUR, "FOO.L": Currency.USD})
        resolver = YahooSymbolResolver(_StubLoggerFactory(), search=search, stock_provider=provider)
        result = resolver.resolve(
            Instrument(
                symbol="ES0000000001",
                name="Foo Corp",
                exchange="MAD",
                isin="ES0000000001",
                currency=Currency.EUR,
            )
        )

        assert result == "FOO.MC"
        assert provider.calls == [["FOO.DE", "FOO.L"]]  # quote lookup ran once, first query only

    def test_quote_currency_match_kept_when_exchange_hint_never_matches(self):
        def search(query):
            if query == "ES0000000001":
                return [_quote("FOO.L", exchange="LSE"), _quote("FOO.DE", exchange="GER")]
            return []

        provider = _FakeStockProvider({"FOO.L": Currency.USD, "FOO.DE": Currency.EUR})
        resolver = YahooSymbolResolver(_StubLoggerFactory(), search=search, stock_provider=provider)
        result = resolver.resolve(
            Instrument(
                symbol="ES0000000001",
                name="Foo Corp",
                exchange="MAD",
                isin="ES0000000001",
                currency=Currency.EUR,
            )
        )

        assert result == "FOO.DE"  # full scan found no venue → verified currency wins

    def test_quote_currency_match_returns_immediately_without_exchange_hint(self):
        # Trade Republic/IBKR-style instrument (no exchange code): nothing can
        # beat a verified quote-currency match, so later queries are skipped.
        searched = []

        def search(query):
            searched.append(query)
            return [_quote("MXWO.L", exchange="LSE"), _quote("SC0J.DE", exchange="GER")]

        provider = _FakeStockProvider({"MXWO.L": Currency.USD, "SC0J.DE": Currency.EUR})
        resolver = YahooSymbolResolver(_StubLoggerFactory(), search=search, stock_provider=provider)
        result = resolver.resolve(
            Instrument(
                symbol="IE00B60SX394",
                name="MSCI World",
                isin="IE00B60SX394",
                currency=Currency.EUR,
            )
        )

        assert result == "SC0J.DE"
        assert searched == ["IE00B60SX394"]

    def test_unmapped_exchange_code_counts_as_no_hint(self):
        # An exchange code with no Yahoo alias can never match, so it must not
        # force the full multi-query scan.
        searched = []

        def search(query):
            searched.append(query)
            return [_quote("MXWO.L", exchange="LSE"), _quote("SC0J.DE", exchange="GER")]

        provider = _FakeStockProvider({"MXWO.L": Currency.USD, "SC0J.DE": Currency.EUR})
        resolver = YahooSymbolResolver(_StubLoggerFactory(), search=search, stock_provider=provider)
        result = resolver.resolve(
            Instrument(
                symbol="IE00B60SX394",
                name="MSCI World",
                exchange="XXX",
                isin="IE00B60SX394",
                currency=Currency.EUR,
            )
        )

        assert result == "SC0J.DE"
        assert searched == ["IE00B60SX394"]


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
