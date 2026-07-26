from datetime import date
from decimal import Decimal

import pytest

from pryces.application.serialization import (
    EXPORT_FORMAT,
    EXPORT_VERSION,
    build_export_document,
    manual_asset_from_dict,
    manual_asset_to_dict,
    transaction_from_dict,
    transaction_to_dict,
)
from pryces.domain.portfolio.portfolio import ManualAsset
from pryces.domain.portfolio.transactions import Transaction, TransactionType
from pryces.domain.stocks import Currency


def _buy(**overrides):
    fields = dict(
        date=date(2026, 1, 15),
        type=TransactionType.BUY,
        symbol="AAPL",
        currency=Currency.USD,
        quantity=Decimal("10"),
        price=Decimal("150.25"),
        fee=Decimal("2.50"),
        broker="degiro",
        raw_id="order-1",
    )
    fields.update(overrides)
    return Transaction(**fields)


class TestBuildExportDocument:
    def test_wraps_entries_in_versioned_envelope(self):
        document = build_export_document([{"name": "Main"}], exported_at="2026-07-12T10:00:00")

        assert document["format"] == EXPORT_FORMAT
        assert document["version"] == EXPORT_VERSION
        assert document["exported_at"] == "2026-07-12T10:00:00"
        assert document["portfolios"] == [{"name": "Main"}]


class TestTransactionSerialization:
    def test_round_trips_a_full_trade(self):
        transaction = _buy()

        assert transaction_from_dict(transaction_to_dict(transaction)) == transaction

    def test_round_trips_a_minimal_dividend(self):
        transaction = Transaction(
            date=date(2026, 2, 1),
            type=TransactionType.DIVIDEND,
            symbol="AAPL",
            currency=Currency.USD,
            amount=Decimal("12.30"),
        )

        assert transaction_from_dict(transaction_to_dict(transaction)) == transaction

    def test_omits_absent_optional_fields(self):
        row = transaction_to_dict(_buy(broker=None, raw_id=None))

        assert "broker" not in row
        assert "raw_id" not in row
        assert "amount" not in row
        assert row["fee"] == "2.50"  # fee is always present

    def test_serializes_decimals_and_dates_as_strings(self):
        row = transaction_to_dict(_buy())

        assert row["date"] == "2026-01-15"
        assert row["quantity"] == "10"
        assert row["price"] == "150.25"
        assert row["type"] == "buy"
        assert row["currency"] == "USD"

    def test_missing_fee_defaults_to_zero(self):
        row = transaction_to_dict(_buy())
        del row["fee"]

        assert transaction_from_dict(row).fee == Decimal("0")

    def test_ignores_storage_internal_id(self):
        row = transaction_to_dict(_buy())
        row["id"] = "deadbeef"

        assert transaction_from_dict(row) == _buy()

    @pytest.mark.parametrize(
        "mutation",
        [
            {"date": "not-a-date"},
            {"type": "SPLIT"},
            {"currency": "XXX"},
            {"quantity": "ten"},
            {"symbol": "  "},
        ],
    )
    def test_raises_value_error_on_bad_field(self, mutation):
        row = transaction_to_dict(_buy())
        row.update(mutation)

        with pytest.raises(ValueError):
            transaction_from_dict(row)

    @pytest.mark.parametrize("missing", ["date", "type", "symbol", "currency"])
    def test_raises_value_error_on_missing_required_field(self, missing):
        row = transaction_to_dict(_buy())
        del row[missing]

        with pytest.raises(ValueError):
            transaction_from_dict(row)

    def test_raises_value_error_on_non_object_row(self):
        with pytest.raises(ValueError):
            transaction_from_dict("not a row")


class TestManualAssetSerialization:
    def test_round_trips(self):
        asset = ManualAsset(name="Savings", asset_type="CASH", value_base=Decimal("1000.00"))

        assert manual_asset_from_dict(manual_asset_to_dict(asset)) == asset

    def test_serializes_value_as_string(self):
        row = manual_asset_to_dict(
            ManualAsset(name="Savings", asset_type="CASH", value_base=Decimal("1000.00"))
        )

        assert row == {"name": "Savings", "asset_type": "CASH", "value_base": "1000.00"}

    @pytest.mark.parametrize(
        "row",
        [
            {"asset_type": "CASH", "value_base": "1"},
            {"name": "Savings", "value_base": "1"},
            {"name": "Savings", "asset_type": "CASH"},
            {"name": "Savings", "asset_type": "CASH", "value_base": "lots"},
            {"name": " ", "asset_type": "CASH", "value_base": "1"},
            "not a row",
        ],
    )
    def test_raises_value_error_on_bad_row(self, row):
        with pytest.raises(ValueError):
            manual_asset_from_dict(row)
