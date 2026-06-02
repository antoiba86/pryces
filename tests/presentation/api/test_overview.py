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


def _ledger(symbol, raw_id):
    return json.dumps(
        {
            "base_currency": "EUR",
            "transactions": [
                {
                    "date": "2024-01-10",
                    "type": "buy",
                    "symbol": symbol,
                    "currency": "USD",
                    "quantity": "10",
                    "price": "100.00",
                    "fee": "0",
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
    app.dependency_overrides[get_historical_price_provider] = lambda: _FakeHistoricalPrices()
    app.dependency_overrides[get_symbol_resolver] = lambda: _FakeResolver()
    return TestClient(app)


class TestOverviewApi:
    def test_empty_overview(self, client):
        body = client.get("/overview").json()
        assert body["portfolio"]["positions"] == []
        assert body["breakdown"] == []

    def test_combines_portfolios(self, client):
        client.post("/portfolios", json={"base_currency": "EUR", "name": "degiro"})
        client.post("/portfolios", json={"base_currency": "EUR", "name": "ibkr"})
        client.post(
            "/portfolios/degiro/transactions",
            files={"file": ("l.json", _ledger("AAPL", "a1"), "application/json")},
        )
        client.post(
            "/portfolios/ibkr/transactions",
            files={"file": ("l.json", _ledger("MSFT", "b1"), "application/json")},
        )

        body = client.get("/overview").json()

        symbols = {p["symbol"] for p in body["portfolio"]["positions"]}
        assert symbols == {"AAPL", "MSFT"}
        # 10*100 + 10*100 = 2000 (fake price 100, fx 1)
        assert Decimal(body["portfolio"]["total_value"]) == Decimal("2000")
        assert {b["name"] for b in body["breakdown"]} == {"degiro", "ibkr"}

    def test_overview_transactions_across_portfolios(self, client):
        client.post("/portfolios", json={"base_currency": "EUR", "name": "degiro"})
        client.post("/portfolios", json={"base_currency": "EUR", "name": "ibkr"})
        client.post(
            "/portfolios/degiro/transactions",
            files={"file": ("l.json", _ledger("AAPL", "a1"), "application/json")},
        )
        client.post(
            "/portfolios/ibkr/transactions",
            files={"file": ("l.json", _ledger("AAPL", "b1"), "application/json")},
        )

        rows = client.get("/overview/transactions", params={"symbol": "AAPL"}).json()

        assert len(rows) == 2
        assert {r["portfolio"] for r in rows} == {"degiro", "ibkr"}
        assert all(r["symbol"] == "AAPL" for r in rows)
