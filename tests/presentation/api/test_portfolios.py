import json
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from pryces.domain.stocks import Currency, Stock
from pryces.infrastructure.repositories import JsonPortfolioRepository
from pryces.presentation.api.dependencies import (
    get_fx_provider,
    get_historical_fx_provider,
    get_historical_price_provider,
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


class _FakeHistoricalPrices:
    def get_prices(self, symbol, dates):
        return {day: Decimal("100") for day in dates}


class _FakeResolver:
    def resolve(self, instrument):
        return instrument.symbol


def _ledger(symbol="AAPL", raw_id="t1", broker="TEST"):
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
                    "broker": broker,
                    "raw_id": raw_id,
                }
            ],
        }
    )


def _closed_ledger():
    return json.dumps(
        {
            "base_currency": "EUR",
            "transactions": [
                {
                    "date": "2024-01-10",
                    "type": "buy",
                    "symbol": "AAPL",
                    "currency": "USD",
                    "quantity": "10",
                    "price": "100.00",
                    "fee": "0",
                    "broker": "TEST",
                    "raw_id": "b1",
                },
                {
                    "date": "2024-06-10",
                    "type": "sell",
                    "symbol": "AAPL",
                    "currency": "USD",
                    "quantity": "10",
                    "price": "150.00",
                    "fee": "0",
                    "broker": "TEST",
                    "raw_id": "s1",
                },
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
    app.dependency_overrides[get_historical_price_provider] = lambda: _FakeHistoricalPrices()
    app.dependency_overrides[get_symbol_resolver] = lambda: _FakeResolver()
    return TestClient(app)


def _upload(client, name, content, broker=None):
    params = {"broker": broker} if broker else {}
    return client.post(
        f"/api/portfolios/{name}/transactions",
        files={"file": ("ledger.json", content, "application/json")},
        params=params,
    )


class TestPortfoliosApi:

    def test_create_then_appears_in_list(self, client):
        created = client.post("/api/portfolios", json={"base_currency": "EUR", "name": "main"})

        assert created.status_code == 201
        assert created.json()["name"] == "main"

        listed = client.get("/api/portfolios")
        assert listed.status_code == 200
        assert [p["name"] for p in listed.json()] == ["main"]

    def test_duplicate_create_conflicts(self, client):
        client.post("/api/portfolios", json={"base_currency": "EUR", "name": "main"})

        again = client.post("/api/portfolios", json={"base_currency": "EUR", "name": "main"})

        assert again.status_code == 409

    def test_get_missing_returns_404(self, client):
        assert client.get("/api/portfolios/ghost").status_code == 404

    def test_delete_then_get_404(self, client):
        client.post("/api/portfolios", json={"base_currency": "EUR", "name": "main"})

        deleted = client.delete("/api/portfolios/main")
        assert deleted.status_code == 204

        assert client.get("/api/portfolios/main").status_code == 404

    def test_delete_missing_returns_404(self, client):
        assert client.delete("/api/portfolios/ghost").status_code == 404

    def test_import_then_get_shows_position(self, client):
        client.post("/api/portfolios", json={"base_currency": "EUR", "name": "main"})

        result = _upload(client, "main", _ledger())
        assert result.status_code == 200
        assert result.json()["inserted"] == 1

        portfolio = client.get("/api/portfolios/main").json()
        assert portfolio["base_currency"] == "EUR"
        assert [p["symbol"] for p in portfolio["positions"]] == ["AAPL"]

    def test_get_shows_closed_position_and_totals(self, client):
        client.post("/api/portfolios", json={"base_currency": "EUR", "name": "main"})
        assert _upload(client, "main", _closed_ledger()).status_code == 200

        portfolio = client.get("/api/portfolios/main").json()

        assert portfolio["positions"] == []
        assert [c["symbol"] for c in portfolio["closed_positions"]] == ["AAPL"]
        closed = portfolio["closed_positions"][0]
        # realized native = 500 USD at fake rate 1.0 -> 500; return % = 50
        assert Decimal(closed["realized_pnl_base"]) == Decimal("500")
        assert Decimal(closed["realized_return_pct"]) == Decimal("50")
        assert closed["hold_period_days"] == 152
        assert Decimal(portfolio["total_realized_pnl"]) == Decimal("500")
        # nothing open: total_profit == realized (unrealized 0, dividends 0)
        assert Decimal(portfolio["total_profit"]) == Decimal("500")

    def test_position_carries_lifetime_fields(self, client):
        client.post("/api/portfolios", json={"base_currency": "EUR", "name": "main"})
        _upload(client, "main", _ledger())

        portfolio = client.get("/api/portfolios/main").json()
        position = portfolio["positions"][0]
        assert "lifetime_pnl_base" in position
        assert "lifetime_return_pct" in position

    def test_transaction_history_filtered_by_symbol(self, client):
        client.post("/api/portfolios", json={"base_currency": "EUR", "name": "main"})
        _upload(client, "main", _closed_ledger())  # AAPL buy + sell

        rows = client.get("/api/portfolios/main/transactions", params={"symbol": "AAPL"}).json()

        assert [r["type"] for r in rows] == ["buy", "sell"]  # sorted by date
        assert all(r["symbol"] == "AAPL" for r in rows)

    def test_transaction_history_missing_portfolio_404(self, client):
        assert client.get("/api/portfolios/ghost/transactions").status_code == 404

    def test_reimport_dedupes(self, client):
        client.post("/api/portfolios", json={"base_currency": "EUR", "name": "main"})
        _upload(client, "main", _ledger())

        second = _upload(client, "main", _ledger())

        assert second.json()["inserted"] == 0
        assert second.json()["duplicates"] == 1

    def test_import_into_missing_portfolio_404(self, client):
        assert _upload(client, "ghost", _ledger()).status_code == 404

    def test_unrecognized_format_422(self, client):
        client.post("/api/portfolios", json={"base_currency": "EUR", "name": "main"})

        result = _upload(client, "main", "not a recognized export")

        assert result.status_code == 422

    def test_import_different_broker_conflicts(self, client):
        client.post("/api/portfolios", json={"base_currency": "EUR", "name": "main"})
        assert _upload(client, "main", _ledger(broker="TEST")).status_code == 200

        clash = _upload(client, "main", _ledger(symbol="MSFT", raw_id="t2", broker="OTHER"))

        assert clash.status_code == 409


def _manual_body(**overrides):
    body = {
        "date": "2024-02-01",
        "type": "buy",
        "symbol": "AAPL",
        "currency": "USD",
        "quantity": "3",
        "price": "50",
        "fee": "0.5",
    }
    body.update(overrides)
    return body


class TestManualTransactionsApi:

    def test_add_manual_transaction_then_appears_with_id(self, client):
        client.post("/api/portfolios", json={"base_currency": "EUR", "name": "main"})

        added = client.post("/api/portfolios/main/transactions/manual", json=_manual_body())
        assert added.status_code == 201
        transaction_id = added.json()["id"]

        rows = client.get("/api/portfolios/main/transactions").json()
        assert [r["id"] for r in rows] == [transaction_id]
        assert rows[0]["broker"] is None

    def test_add_manual_into_missing_portfolio_404(self, client):
        assert (
            client.post(
                "/api/portfolios/ghost/transactions/manual", json=_manual_body()
            ).status_code
            == 404
        )

    def test_add_manual_invalid_type_422(self, client):
        client.post("/api/portfolios", json={"base_currency": "EUR", "name": "main"})
        bad = client.post(
            "/api/portfolios/main/transactions/manual", json=_manual_body(type="nonsense")
        )
        assert bad.status_code == 422

    def test_edit_transaction_updates_fields(self, client):
        client.post("/api/portfolios", json={"base_currency": "EUR", "name": "main"})
        transaction_id = client.post(
            "/api/portfolios/main/transactions/manual", json=_manual_body()
        ).json()["id"]

        edited = client.patch(
            f"/api/portfolios/main/transactions/{transaction_id}",
            json=_manual_body(symbol="MSFT", quantity="7"),
        )
        assert edited.status_code == 204

        rows = client.get("/api/portfolios/main/transactions").json()
        assert rows[0]["symbol"] == "MSFT"
        assert rows[0]["quantity"] == "7"

    def test_edit_missing_transaction_404(self, client):
        client.post("/api/portfolios", json={"base_currency": "EUR", "name": "main"})
        assert (
            client.patch("/api/portfolios/main/transactions/nope", json=_manual_body()).status_code
            == 404
        )

    def test_delete_transaction(self, client):
        client.post("/api/portfolios", json={"base_currency": "EUR", "name": "main"})
        transaction_id = client.post(
            "/api/portfolios/main/transactions/manual", json=_manual_body()
        ).json()["id"]

        deleted = client.delete(f"/api/portfolios/main/transactions/{transaction_id}")
        assert deleted.status_code == 204
        assert client.get("/api/portfolios/main/transactions").json() == []

    def test_delete_missing_transaction_404(self, client):
        client.post("/api/portfolios", json={"base_currency": "EUR", "name": "main"})
        assert client.delete("/api/portfolios/main/transactions/nope").status_code == 404

    def test_manual_then_import_adopts_broker(self, client):
        # A manual-only portfolio is broker-less, so a first import is accepted.
        client.post("/api/portfolios", json={"base_currency": "EUR", "name": "main"})
        client.post("/api/portfolios/main/transactions/manual", json=_manual_body())

        imported = _upload(client, "main", _ledger(symbol="GOOG", raw_id="z1", broker="TEST"))
        assert imported.status_code == 200
        assert imported.json()["inserted"] == 1
