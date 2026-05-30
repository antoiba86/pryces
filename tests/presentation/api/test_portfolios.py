import json
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from pryces.domain.stocks import Currency, Stock
from pryces.infrastructure.repositories import JsonPortfolioRepository
from pryces.presentation.api.dependencies import (
    get_fx_provider,
    get_historical_fx_provider,
    get_portfolio_repository,
    get_stock_provider,
    get_symbol_resolver,
)
from pryces.presentation.api.main import create_app


class _FakeStockProvider:
    def get_stocks(self, symbols):
        return [
            Stock(symbol=s.upper(), current_price=Decimal("100"), currency=Currency.USD)
            for s in symbols
        ]


class _FakeFx:
    def get_rates(self, base, quotes):
        return {quote: Decimal("1") for quote in quotes}


class _FakeHistoricalFx:
    def get_rates(self, base, quote, dates):
        return {day: Decimal("1") for day in dates}


class _FakeResolver:
    def resolve(self, instrument):
        return instrument.symbol


def _ledger(symbol="AAPL", raw_id="t1"):
    return json.dumps(
        {
            "base_currency": "EUR",
            "transactions": [
                {
                    "date": "2024-01-10",
                    "type": "buy",
                    "symbol": symbol,
                    "currency": "USD",
                    "quantity": "5",
                    "price": "100.00",
                    "fee": "1.0",
                    "broker": "TEST",
                    "raw_id": raw_id,
                }
            ],
        }
    )


@pytest.fixture()
def client(tmp_path):
    app = create_app()
    repository = JsonPortfolioRepository(data_dir=tmp_path)
    app.dependency_overrides[get_portfolio_repository] = lambda: repository
    app.dependency_overrides[get_stock_provider] = lambda: _FakeStockProvider()
    app.dependency_overrides[get_fx_provider] = lambda: _FakeFx()
    app.dependency_overrides[get_historical_fx_provider] = lambda: _FakeHistoricalFx()
    app.dependency_overrides[get_symbol_resolver] = lambda: _FakeResolver()
    return TestClient(app)


def _upload(client, name, content, broker=None):
    params = {"broker": broker} if broker else {}
    return client.post(
        f"/portfolios/{name}/transactions",
        files={"file": ("ledger.json", content, "application/json")},
        params=params,
    )


class TestPortfoliosApi:

    def test_create_then_appears_in_list(self, client):
        created = client.post("/portfolios", json={"base_currency": "EUR", "name": "main"})

        assert created.status_code == 201
        assert created.json()["name"] == "main"

        listed = client.get("/portfolios")
        assert listed.status_code == 200
        assert [p["name"] for p in listed.json()] == ["main"]

    def test_duplicate_create_conflicts(self, client):
        client.post("/portfolios", json={"base_currency": "EUR", "name": "main"})

        again = client.post("/portfolios", json={"base_currency": "EUR", "name": "main"})

        assert again.status_code == 409

    def test_get_missing_returns_404(self, client):
        assert client.get("/portfolios/ghost").status_code == 404

    def test_delete_then_get_404(self, client):
        client.post("/portfolios", json={"base_currency": "EUR", "name": "main"})

        deleted = client.delete("/portfolios/main")
        assert deleted.status_code == 204

        assert client.get("/portfolios/main").status_code == 404

    def test_delete_missing_returns_404(self, client):
        assert client.delete("/portfolios/ghost").status_code == 404

    def test_import_then_get_shows_position(self, client):
        client.post("/portfolios", json={"base_currency": "EUR", "name": "main"})

        result = _upload(client, "main", _ledger())
        assert result.status_code == 200
        assert result.json()["inserted"] == 1

        portfolio = client.get("/portfolios/main").json()
        assert portfolio["base_currency"] == "EUR"
        assert [p["symbol"] for p in portfolio["positions"]] == ["AAPL"]

    def test_reimport_dedupes(self, client):
        client.post("/portfolios", json={"base_currency": "EUR", "name": "main"})
        _upload(client, "main", _ledger())

        second = _upload(client, "main", _ledger())

        assert second.json()["inserted"] == 0
        assert second.json()["duplicates"] == 1

    def test_import_into_missing_portfolio_404(self, client):
        assert _upload(client, "ghost", _ledger()).status_code == 404

    def test_unrecognized_format_422(self, client):
        client.post("/portfolios", json={"base_currency": "EUR", "name": "main"})

        result = _upload(client, "main", "not a recognized export")

        assert result.status_code == 422
