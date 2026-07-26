import json
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from pryces.domain.portfolio.transactions import Transaction, TransactionType
from pryces.domain.stocks import Currency
from pryces.infrastructure.repositories import JsonPortfolioRepository
from pryces.presentation.api.dependencies import get_portfolio_repository
from pryces.presentation.api.main import create_app


@pytest.fixture
def repository(tmp_path):
    return JsonPortfolioRepository(data_dir=tmp_path)


@pytest.fixture
def client(repository):
    app = create_app()
    app.dependency_overrides[get_portfolio_repository] = lambda: repository
    return TestClient(app)


def _buy(raw_id="order-1"):
    return Transaction(
        date=date(2026, 1, 15),
        type=TransactionType.BUY,
        symbol="AAPL",
        currency=Currency.USD,
        quantity=Decimal("10"),
        price=Decimal("150.25"),
        fee=Decimal("2.50"),
        broker="degiro",
        raw_id=raw_id,
    )


def _upload(client, document):
    return client.post(
        "/data/import",
        files={"file": ("backup.json", json.dumps(document), "application/json")},
    )


class TestExportEndpoint:
    def test_exports_all_portfolios_as_attachment(self, client, repository):
        repository.create(base_currency="EUR", name="Main")
        repository.add_transactions("Main", [_buy()])

        response = client.get("/data/export")

        assert response.status_code == 200
        disposition = response.headers["content-disposition"]
        assert disposition.startswith('attachment; filename="pryces_export_')
        document = json.loads(response.content)
        assert document["format"] == "pryces-export"
        assert document["version"] == 1
        assert [entry["name"] for entry in document["portfolios"]] == ["Main"]
        assert document["portfolios"][0]["transactions"][0]["price"] == "150.25"

    def test_exports_a_single_portfolio(self, client, repository):
        repository.create(base_currency="EUR", name="Main")
        repository.create(base_currency="USD", name="US")

        response = client.get("/data/export", params={"portfolio": "US"})

        assert response.status_code == 200
        assert "US" in response.headers["content-disposition"]
        document = json.loads(response.content)
        assert [entry["name"] for entry in document["portfolios"]] == ["US"]

    def test_unknown_portfolio_returns_404(self, client):
        assert client.get("/data/export", params={"portfolio": "Nope"}).status_code == 404


class TestImportEndpoint:
    def test_imports_a_document(self, client, repository):
        document = {
            "format": "pryces-export",
            "version": 1,
            "exported_at": "x",
            "portfolios": [
                {
                    "name": "Main",
                    "base_currency": "EUR",
                    "transactions": [
                        {
                            "date": "2026-01-15",
                            "type": "buy",
                            "symbol": "AAPL",
                            "currency": "USD",
                            "quantity": "10",
                            "price": "150.25",
                        }
                    ],
                    "manual_assets": [],
                }
            ],
        }

        response = _upload(client, document)

        assert response.status_code == 200
        body = response.json()
        assert body["portfolios_created"] == 1
        assert body["transactions_added"] == 1
        assert body["warnings"] == []
        assert len(repository.get_transactions("Main")) == 1

    def test_bad_version_returns_422(self, client):
        response = _upload(client, {"format": "pryces-export", "version": 99, "portfolios": []})

        assert response.status_code == 422

    def test_non_json_file_returns_400(self, client):
        response = client.post(
            "/data/import", files={"file": ("backup.json", "{not json", "application/json")}
        )

        assert response.status_code == 400

    def test_export_then_reimport_is_idempotent(self, client, repository):
        repository.create(base_currency="EUR", name="Main")
        repository.add_transactions("Main", [_buy()])
        exported = json.loads(client.get("/data/export").content)

        response = _upload(client, exported)

        body = response.json()
        assert body["portfolios_merged"] == 1
        assert body["transactions_added"] == 0
        assert body["transactions_skipped"] == 1
        assert len(repository.get_transactions("Main")) == 1
