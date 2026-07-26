from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from pryces.application.exceptions import PortfolioNotFound
from pryces.application.use_cases.export_data import ExportData, ExportDataRequest
from pryces.domain.portfolio.portfolio import ManualAsset
from pryces.domain.portfolio.transactions import Transaction, TransactionType
from pryces.domain.stocks import Currency
from pryces.infrastructure.repositories import JsonPortfolioRepository

_NOW = datetime(2026, 7, 12, 10, 0, 0, tzinfo=timezone.utc)


def _buy(symbol="AAPL", raw_id="order-1", broker="degiro"):
    return Transaction(
        date=date(2026, 1, 15),
        type=TransactionType.BUY,
        symbol=symbol,
        currency=Currency.USD,
        quantity=Decimal("10"),
        price=Decimal("150.25"),
        fee=Decimal("2.50"),
        broker=broker,
        raw_id=raw_id,
    )


@pytest.fixture
def repository(tmp_path):
    return JsonPortfolioRepository(data_dir=tmp_path)


@pytest.fixture
def use_case(repository):
    return ExportData(repository, clock=lambda: _NOW)


class TestExportData:
    def test_empty_repository_exports_empty_document(self, use_case):
        document = use_case.handle(ExportDataRequest())

        assert document["format"] == "pryces-export"
        assert document["version"] == 1
        assert document["exported_at"] == _NOW.isoformat()
        assert document["portfolios"] == []

    def test_exports_all_portfolios_with_their_data(self, repository, use_case):
        repository.create(base_currency="EUR", name="Main")
        repository.create(base_currency="USD", name="US")
        repository.add_transactions("Main", [_buy()])
        repository.set_manual_assets(
            "Main", [ManualAsset(name="Savings", asset_type="CASH", value_base=Decimal("1000"))]
        )

        document = use_case.handle(ExportDataRequest())

        assert [entry["name"] for entry in document["portfolios"]] == ["Main", "US"]
        main = document["portfolios"][0]
        assert main["base_currency"] == "EUR"
        assert main["transactions"] == [
            {
                "date": "2026-01-15",
                "type": "buy",
                "symbol": "AAPL",
                "currency": "USD",
                "fee": "2.50",
                "quantity": "10",
                "price": "150.25",
                "broker": "degiro",
                "raw_id": "order-1",
            }
        ]
        assert main["manual_assets"] == [
            {"name": "Savings", "asset_type": "CASH", "value_base": "1000"}
        ]
        assert document["portfolios"][1] == {
            "name": "US",
            "base_currency": "USD",
            "transactions": [],
            "manual_assets": [],
        }

    def test_rows_carry_no_storage_id(self, repository, use_case):
        repository.create(base_currency="EUR", name="Main")
        repository.add_transactions("Main", [_buy()])

        document = use_case.handle(ExportDataRequest())

        assert "id" not in document["portfolios"][0]["transactions"][0]

    def test_exports_a_single_portfolio(self, repository, use_case):
        repository.create(base_currency="EUR", name="Main")
        repository.create(base_currency="USD", name="US")

        document = use_case.handle(ExportDataRequest(portfolio_name="US"))

        assert [entry["name"] for entry in document["portfolios"]] == ["US"]

    def test_unknown_portfolio_raises(self, use_case):
        with pytest.raises(PortfolioNotFound):
            use_case.handle(ExportDataRequest(portfolio_name="Nope"))

    def test_document_is_json_serializable(self, repository, use_case):
        import json

        repository.create(base_currency="EUR", name="Main")
        repository.add_transactions("Main", [_buy()])

        document = use_case.handle(ExportDataRequest())

        assert json.loads(json.dumps(document)) == document
