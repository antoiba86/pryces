from decimal import Decimal

import pytest

from pryces.application.exceptions import SymbolMappingNotFound
from pryces.application.use_cases.manage_symbol_map import (
    DeleteSymbolMapping,
    GetSymbolMap,
    SetSymbolMapping,
    SetSymbolMappingRequest,
)
from pryces.domain.stocks import Currency, Stock


class _FakeStore:
    def __init__(self, mapping=None):
        self.mapping = dict(mapping or {})

    def all(self):
        return dict(self.mapping)

    def get(self, key):
        return self.mapping.get(key.strip().upper())

    def put(self, key, ticker):
        self.mapping[key.strip().upper()] = ticker.strip()

    def delete(self, key):
        return self.mapping.pop(key.strip().upper(), None) is not None


class _FakeStockProvider:
    def __init__(self, known=None, raises=False):
        self._known = known or {}
        self._raises = raises

    def get_stocks(self, symbols):
        if self._raises:
            raise RuntimeError("Yahoo is throttling")
        return [self._known[s] for s in symbols if s in self._known]


def _stock(symbol, name="A Fund", currency=Currency.EUR):
    return Stock(symbol=symbol, current_price=Decimal("1"), currency=currency, name=name)


class TestGetSymbolMap:
    def test_returns_entries_sorted_by_key(self):
        store = _FakeStore({"ZZZ": "z", "AAA": "a", "MMM": "m"})

        entries = GetSymbolMap(store).handle()

        assert [e.key for e in entries] == ["AAA", "MMM", "ZZZ"]
        assert [e.ticker for e in entries] == ["a", "m", "z"]

    def test_empty_map_returns_nothing(self):
        assert GetSymbolMap(_FakeStore()).handle() == []


class TestSetSymbolMapping:
    def test_stores_the_mapping(self):
        store = _FakeStore()

        SetSymbolMapping(store).handle(
            SetSymbolMappingRequest(key="HOROS VALUE INTERNACIONAL, FI", ticker="0P0001DFE8.F")
        )

        assert store.get("HOROS VALUE INTERNACIONAL, FI") == "0P0001DFE8.F"

    def test_verified_mapping_reports_the_instrument(self):
        # Saving is only useful if the ticker prices, so the name comes back as
        # confirmation that the right fund was picked.
        provider = _FakeStockProvider({"0P000168OI.F": _stock("0P000168OI.F", "Renta 4 Numantia")})
        use_case = SetSymbolMapping(_FakeStore(), provider)

        entry = use_case.handle(SetSymbolMappingRequest(key="R4 FUND", ticker="0P000168OI.F"))

        assert entry.verified is True
        assert entry.name == "Renta 4 Numantia"
        assert entry.currency == "EUR"

    def test_unknown_ticker_is_reported_but_still_saved(self):
        # Reported, not enforced: refusing to save would leave the user with no
        # way to fix an instrument when Yahoo happens to be unreachable.
        store = _FakeStore()
        use_case = SetSymbolMapping(store, _FakeStockProvider({}))

        entry = use_case.handle(SetSymbolMappingRequest(key="R4 FUND", ticker="NOPE"))

        assert entry.verified is False
        assert entry.name is None
        assert store.get("R4 FUND") == "NOPE"

    def test_a_failing_provider_leaves_verification_unknown(self):
        store = _FakeStore()
        use_case = SetSymbolMapping(store, _FakeStockProvider(raises=True))

        entry = use_case.handle(SetSymbolMappingRequest(key="R4 FUND", ticker="0P000168OI.F"))

        assert entry.verified is False
        assert store.get("R4 FUND") == "0P000168OI.F"

    def test_no_provider_skips_verification(self):
        entry = SetSymbolMapping(_FakeStore()).handle(
            SetSymbolMappingRequest(key="R4 FUND", ticker="0P000168OI.F")
        )

        assert entry.verified is None

    def test_verify_false_skips_the_lookup(self):
        provider = _FakeStockProvider({"AAPL": _stock("AAPL")})
        use_case = SetSymbolMapping(_FakeStore(), provider)

        entry = use_case.handle(
            SetSymbolMappingRequest(key="US0378331005", ticker="AAPL", verify=False)
        )

        assert entry.verified is None

    def test_replaces_an_existing_mapping(self):
        store = _FakeStore({"R4 FUND": "WRONG"})

        SetSymbolMapping(store).handle(SetSymbolMappingRequest(key="R4 FUND", ticker="RIGHT"))

        assert store.get("R4 FUND") == "RIGHT"

    @pytest.mark.parametrize(
        "key,ticker", [("", "AAPL"), ("   ", "AAPL"), ("KEY", ""), ("KEY", " ")]
    )
    def test_rejects_blank_key_or_ticker(self, key, ticker):
        with pytest.raises(ValueError):
            SetSymbolMapping(_FakeStore()).handle(SetSymbolMappingRequest(key=key, ticker=ticker))


class TestDeleteSymbolMapping:
    def test_removes_the_mapping(self):
        store = _FakeStore({"R4 FUND": "0P000168OI.F"})

        DeleteSymbolMapping(store).handle("R4 FUND")

        assert store.get("R4 FUND") is None

    def test_raises_when_the_key_is_not_mapped(self):
        with pytest.raises(SymbolMappingNotFound):
            DeleteSymbolMapping(_FakeStore()).handle("MISSING")
