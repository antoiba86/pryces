import urllib.parse
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from pryces.domain.stocks import Currency, Stock
from pryces.infrastructure.resolvers import JsonSymbolMap
from pryces.presentation.api.dependencies import get_stock_provider, get_symbol_map_store
from pryces.presentation.api.main import create_app

# A real broker product name: spaces, a comma and a dot, none of which survive a
# plain path segment — which is why the routes declare `{key:path}`.
FUND = "HOROS VALUE INTERNACIONAL, FI"
TICKER = "0P0001DFE8.F"


class _FakeStockProvider:
    def __init__(self, known=()):
        self._known = set(known)

    def get_stocks(self, symbols):
        return [
            Stock(
                symbol=s,
                current_price=Decimal("221.85"),
                currency=Currency.EUR,
                name="Horos Value Internacional FI",
            )
            for s in symbols
            if s in self._known
        ]


@pytest.fixture
def client(tmp_path):
    app = create_app()
    store = JsonSymbolMap(tmp_path / "symbol_map.json")
    app.dependency_overrides[get_symbol_map_store] = lambda: store
    app.dependency_overrides[get_stock_provider] = lambda: _FakeStockProvider({TICKER})
    yield TestClient(app)
    app.dependency_overrides.clear()


def _url(key: str) -> str:
    return f"/api/symbol-map/{urllib.parse.quote(key)}"


class TestListSymbolMap:
    def test_empty_map_returns_an_empty_list(self, client):
        assert client.get("/api/symbol-map").json() == []

    def test_lists_entries_sorted_by_key(self, client):
        client.put(_url("ZZZ FUND"), json={"ticker": TICKER})
        client.put(_url("AAA FUND"), json={"ticker": TICKER})

        keys = [entry["key"] for entry in client.get("/api/symbol-map").json()]

        assert keys == ["AAA FUND", "ZZZ FUND"]


class TestSetSymbolMapping:
    def test_stores_a_mapping_keyed_by_a_product_name(self, client):
        response = client.put(_url(FUND), json={"ticker": TICKER})

        assert response.status_code == 200
        assert response.json()["key"] == FUND
        assert response.json()["ticker"] == TICKER
        assert client.get("/api/symbol-map").json()[0]["key"] == FUND

    def test_a_known_ticker_comes_back_verified_with_its_name(self, client):
        body = client.put(_url(FUND), json={"ticker": TICKER}).json()

        assert body["verified"] is True
        assert body["name"] == "Horos Value Internacional FI"
        assert body["currency"] == "EUR"

    def test_an_unknown_ticker_is_flagged_but_still_saved(self, client):
        body = client.put(_url(FUND), json={"ticker": "NOT-A-TICKER"}).json()

        assert body["verified"] is False
        assert body["name"] is None
        assert client.get("/api/symbol-map").json()[0]["ticker"] == "NOT-A-TICKER"

    def test_replacing_a_mapping_keeps_one_entry(self, client):
        client.put(_url(FUND), json={"ticker": "WRONG"})
        client.put(_url(FUND), json={"ticker": TICKER})

        entries = client.get("/api/symbol-map").json()

        assert len(entries) == 1
        assert entries[0]["ticker"] == TICKER

    def test_blank_ticker_is_rejected(self, client):
        response = client.put(_url(FUND), json={"ticker": "   "})

        assert response.status_code == 422
        assert "ticker" in response.json()["detail"]


class TestDeleteSymbolMapping:
    def test_removes_the_mapping(self, client):
        client.put(_url(FUND), json={"ticker": TICKER})

        assert client.delete(_url(FUND)).status_code == 204
        assert client.get("/api/symbol-map").json() == []

    def test_unmapped_key_returns_404(self, client):
        assert client.delete(_url("NEVER MAPPED")).status_code == 404
