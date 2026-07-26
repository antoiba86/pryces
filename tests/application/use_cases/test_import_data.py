from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from pryces.application.exceptions import InvalidExportDocument
from pryces.application.use_cases.export_data import ExportData, ExportDataRequest
from pryces.application.use_cases.import_data import ImportData, ImportDataRequest
from pryces.domain.portfolio.portfolio import ManualAsset
from pryces.domain.portfolio.transactions import Transaction, TransactionType
from pryces.domain.stocks import Currency
from pryces.infrastructure.repositories import JsonPortfolioRepository


def _row(**overrides):
    row = {
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
    row.update(overrides)
    return row


def _manual_row(**overrides):
    row = {
        "date": "2026-02-01",
        "type": "buy",
        "symbol": "MSFT",
        "currency": "USD",
        "quantity": "1",
        "price": "400",
    }
    row.update(overrides)
    return row


def _document(*entries):
    return {
        "format": "pryces-export",
        "version": 1,
        "exported_at": "x",
        "portfolios": list(entries),
    }


def _entry(name="Main", base_currency="EUR", transactions=None, **extra):
    entry = {
        "name": name,
        "base_currency": base_currency,
        "transactions": transactions if transactions is not None else [],
    }
    entry.update(extra)
    return entry


@pytest.fixture
def repository(tmp_path):
    return JsonPortfolioRepository(data_dir=tmp_path)


@pytest.fixture
def use_case(repository):
    return ImportData(repository)


class TestEnvelopeValidation:
    @pytest.mark.parametrize(
        "document",
        [
            "not an object",
            {},
            {"format": "other", "version": 1, "portfolios": []},
            {"format": "pryces-export", "version": 99, "portfolios": []},
            {"format": "pryces-export", "version": 1, "portfolios": "nope"},
            {"format": "pryces-export", "version": 1},
        ],
    )
    def test_bad_envelope_aborts_everything(self, use_case, repository, document):
        with pytest.raises(InvalidExportDocument):
            use_case.handle(ImportDataRequest(document=document))

        assert repository.list_portfolios() == []


class TestImportData:
    def test_creates_missing_portfolio_with_data(self, use_case, repository):
        document = _document(
            _entry(
                transactions=[_row()],
                manual_assets=[{"name": "Savings", "asset_type": "CASH", "value_base": "1000"}],
            )
        )

        result = use_case.handle(ImportDataRequest(document=document))

        assert result.portfolios_created == 1
        assert result.transactions_added == 1
        assert result.manual_assets_replaced == 1
        assert result.warnings == ()
        summary = repository.find_summary_by_name("Main")
        assert summary is not None and summary.base_currency == "EUR"
        assert len(repository.get_transactions("Main")) == 1
        assert repository.get_manual_assets("Main") == [
            ManualAsset(name="Savings", asset_type="CASH", value_base=Decimal("1000"))
        ]

    def test_merges_into_existing_portfolio_with_dedup(self, use_case, repository):
        repository.create(base_currency="EUR", name="Main")
        repository.add_transactions("Main", [_transaction("order-1")])

        document = _document(_entry(transactions=[_row(), _row(raw_id="order-2")]))
        result = use_case.handle(ImportDataRequest(document=document))

        assert result.portfolios_merged == 1
        assert result.transactions_added == 1  # order-1 deduped by (broker, raw_id)
        assert result.transactions_skipped == 1
        assert len(repository.get_transactions("Main")) == 2

    def test_reimport_of_full_backup_is_idempotent(self, use_case, repository):
        # Includes a manual (no raw_id) transaction — the case the repository's
        # own dedup cannot handle.
        document = _document(_entry(transactions=[_row(), _manual_row()]))

        first = use_case.handle(ImportDataRequest(document=document))
        second = use_case.handle(ImportDataRequest(document=document))

        assert first.transactions_added == 2
        assert second.transactions_added == 0
        assert second.transactions_skipped == 2
        assert len(repository.get_transactions("Main")) == 2

    def test_dedups_identical_manual_rows_within_the_batch(self, use_case, repository):
        document = _document(_entry(transactions=[_manual_row(), _manual_row()]))

        result = use_case.handle(ImportDataRequest(document=document))

        assert result.transactions_added == 1
        assert result.transactions_skipped == 1

    def test_skips_existing_portfolio_with_different_base_currency(self, use_case, repository):
        repository.create(base_currency="USD", name="Main")

        result = use_case.handle(
            ImportDataRequest(document=_document(_entry(transactions=[_row()])))
        )

        assert result.portfolios_skipped == 1
        assert result.transactions_added == 0
        assert "base currency" in result.warnings[0]
        assert repository.get_transactions("Main") == []

    def test_skips_malformed_transaction_rows_but_keeps_good_ones(self, use_case, repository):
        document = _document(
            _entry(
                transactions=[
                    _row(),
                    _row(raw_id="order-2", date="bad"),
                    _row(raw_id="order-3", quantity="-1"),
                ]
            )
        )

        result = use_case.handle(ImportDataRequest(document=document))

        assert result.transactions_added == 1
        assert len(result.warnings) == 2
        assert "skipped transaction 2" in result.warnings[0]
        assert "skipped transaction 3" in result.warnings[1]

    def test_skips_invalid_entries_but_processes_the_rest(self, use_case, repository):
        document = _document(
            "not an entry",
            _entry(name="  "),
            _entry(name="BadCcy", base_currency="XXX"),
            _entry(name="BadTx", transactions="nope"),
            _entry(name="Good"),
        )

        result = use_case.handle(ImportDataRequest(document=document))

        assert result.portfolios_skipped == 4
        assert result.portfolios_created == 1
        assert len(result.warnings) == 4
        assert repository.find_summary_by_name("Good") is not None

    def test_duplicate_names_in_document_first_wins(self, use_case, repository):
        document = _document(
            _entry(transactions=[_row()]),
            _entry(transactions=[_row(raw_id="order-2")]),
        )

        result = use_case.handle(ImportDataRequest(document=document))

        assert result.portfolios_created == 1
        assert result.portfolios_skipped == 1
        assert len(repository.get_transactions("Main")) == 1
        assert "duplicate" in result.warnings[0]

    def test_absent_manual_assets_key_keeps_existing_assets(self, use_case, repository):
        repository.create(base_currency="EUR", name="Main")
        existing = [ManualAsset(name="Savings", asset_type="CASH", value_base=Decimal("1"))]
        repository.set_manual_assets("Main", existing)

        result = use_case.handle(ImportDataRequest(document=_document(_entry())))

        assert result.manual_assets_replaced == 0
        assert repository.get_manual_assets("Main") == existing

    def test_empty_manual_assets_list_clears_existing_assets(self, use_case, repository):
        repository.create(base_currency="EUR", name="Main")
        repository.set_manual_assets(
            "Main", [ManualAsset(name="Savings", asset_type="CASH", value_base=Decimal("1"))]
        )

        result = use_case.handle(ImportDataRequest(document=_document(_entry(manual_assets=[]))))

        assert result.manual_assets_replaced == 1
        assert repository.get_manual_assets("Main") == []

    def test_one_bad_manual_asset_keeps_existing_assets(self, use_case, repository):
        repository.create(base_currency="EUR", name="Main")
        existing = [ManualAsset(name="Savings", asset_type="CASH", value_base=Decimal("1"))]
        repository.set_manual_assets("Main", existing)

        document = _document(
            _entry(
                manual_assets=[
                    {"name": "OK", "asset_type": "CASH", "value_base": "5"},
                    {"name": "Bad", "asset_type": "CASH", "value_base": "lots"},
                ]
            )
        )
        result = use_case.handle(ImportDataRequest(document=document))

        assert result.manual_assets_replaced == 0
        assert repository.get_manual_assets("Main") == existing
        assert "kept existing assets" in result.warnings[0]


class TestRoundTrip:
    def test_export_import_export_round_trips(self, tmp_path):
        # Pins the app-serializer contract against the repository's storage
        # format: a backup restored into a fresh data dir exports identically.
        now = datetime(2026, 7, 12, tzinfo=timezone.utc)
        source = JsonPortfolioRepository(data_dir=tmp_path / "source")
        source.create(base_currency="EUR", name="Main")
        source.create(base_currency="USD", name="US")
        source.add_transactions(
            "Main",
            [
                _transaction("order-1"),
                Transaction(
                    date=date(2026, 3, 1),
                    type=TransactionType.DIVIDEND,
                    symbol="AAPL",
                    currency=Currency.USD,
                    amount=Decimal("12.30"),
                    broker="degiro",
                    raw_id="div-1",
                ),
                Transaction(
                    date=date(2026, 4, 1),
                    type=TransactionType.BUY,
                    symbol="MSFT",
                    currency=Currency.USD,
                    quantity=Decimal("1"),
                    price=Decimal("400"),
                ),
            ],
        )
        source.set_manual_assets(
            "US", [ManualAsset(name="Savings", asset_type="CASH", value_base=Decimal("9.99"))]
        )
        exported = ExportData(source, clock=lambda: now).handle(ExportDataRequest())

        target = JsonPortfolioRepository(data_dir=tmp_path / "target")
        result = ImportData(target).handle(ImportDataRequest(document=exported))
        re_exported = ExportData(target, clock=lambda: now).handle(ExportDataRequest())

        assert result.warnings == ()
        assert result.portfolios_created == 2
        assert result.transactions_added == 3
        assert re_exported == exported


def _transaction(raw_id):
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
