import json
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from pryces.application.exceptions import PortfolioAlreadyExists, PortfolioNotFound
from pryces.domain.portfolio.portfolio import ManualAsset
from pryces.domain.portfolio.transactions import Transaction, TransactionType
from pryces.domain.stocks import Currency
from pryces.infrastructure.repositories import (
    DATA_DIR_ENV_VAR,
    INDEX_FILENAME,
    InMemoryStockRepository,
    JsonPortfolioRepository,
    resolve_data_dir,
)
from tests.fixtures.factories import create_stock


class TestInMemoryStockRepository:
    def test_get_returns_none_when_symbol_not_saved(self):
        repo = InMemoryStockRepository()

        assert repo.get("AAPL") is None

    def test_save_batch_and_get_returns_saved_stock(self):
        repo = InMemoryStockRepository()
        stock = create_stock("AAPL")

        repo.save_batch([stock])

        assert repo.get("AAPL") is stock

    def test_save_batch_stores_multiple_stocks(self):
        repo = InMemoryStockRepository()
        aapl = create_stock("AAPL")
        msft = create_stock("MSFT")

        repo.save_batch([aapl, msft])

        assert repo.get("AAPL") is aapl
        assert repo.get("MSFT") is msft

    def test_save_batch_overwrites_existing_stock(self):
        repo = InMemoryStockRepository()
        original = create_stock("AAPL")
        updated = create_stock("AAPL")

        repo.save_batch([original])
        repo.save_batch([updated])

        assert repo.get("AAPL") is updated

    def test_get_returns_none_for_unknown_symbol_after_saves(self):
        repo = InMemoryStockRepository()
        repo.save_batch([create_stock("AAPL")])

        assert repo.get("MSFT") is None


class _StepClock:
    """A controllable clock for tests. Each call advances by 1 microsecond."""

    def __init__(self, start: datetime | None = None) -> None:
        self.current = start or datetime(2026, 5, 28, 14, 20, 35, 123_456, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        now = self.current
        self.current = self.current.replace(microsecond=self.current.microsecond + 1)
        return now


@pytest.fixture
def clock():
    return _StepClock()


@pytest.fixture
def repo(tmp_path, clock):
    return JsonPortfolioRepository(data_dir=tmp_path, clock=clock)


def _buy(symbol="AAPL", quantity="5", price="100", broker="IBKR", raw_id=None) -> Transaction:
    return Transaction(
        date=date(2024, 1, 10),
        type=TransactionType.BUY,
        symbol=symbol,
        currency=Currency.USD,
        quantity=Decimal(quantity),
        price=Decimal(price),
        fee=Decimal("1"),
        broker=broker,
        raw_id=raw_id,
    )


def _dividend(amount="2.40") -> Transaction:
    return Transaction(
        date=date(2024, 3, 1),
        type=TransactionType.DIVIDEND,
        symbol="AAPL",
        currency=Currency.USD,
        amount=Decimal(amount),
        broker="IBKR",
    )


class TestResolveDataDir:
    def test_default_is_home_pryces(self, monkeypatch):
        monkeypatch.delenv(DATA_DIR_ENV_VAR, raising=False)
        result = resolve_data_dir()
        assert result.name == ".pryces"

    def test_env_var_override(self, monkeypatch, tmp_path):
        monkeypatch.setenv(DATA_DIR_ENV_VAR, str(tmp_path))
        assert resolve_data_dir() == tmp_path

    def test_env_var_expands_user(self, monkeypatch):
        monkeypatch.setenv(DATA_DIR_ENV_VAR, "~/custom-dir")
        result = resolve_data_dir()
        from pathlib import Path

        assert str(result).startswith(str(Path.home()))
        assert result.name == "custom-dir"


class TestCreateWithExplicitName:
    def test_returns_summary(self, repo):
        summary = repo.create("EUR", name="main")
        assert summary.name == "main"
        assert summary.base_currency == "EUR"
        assert summary.transaction_count == 0

    def test_creates_index_and_portfolio_file(self, repo, tmp_path):
        repo.create("EUR", name="main")
        portfolios_dir = tmp_path / "portfolios"
        index = json.loads((portfolios_dir / INDEX_FILENAME).read_text())
        assert index["version"] == 1
        filename = index["portfolios"]["main"]
        assert filename.startswith("portfolio_") and filename.endswith(".json")
        assert (portfolios_dir / filename).exists()

    def test_portfolio_file_has_no_name_field(self, repo, tmp_path):
        repo.create("EUR", name="main")
        index = json.loads((tmp_path / "portfolios" / INDEX_FILENAME).read_text())
        filename = index["portfolios"]["main"]
        data = json.loads((tmp_path / "portfolios" / filename).read_text())
        assert "name" not in data
        assert data["base_currency"] == "EUR"

    def test_duplicate_name_raises(self, repo):
        repo.create("EUR", name="main")
        with pytest.raises(PortfolioAlreadyExists):
            repo.create("USD", name="main")

    def test_existing_filename_on_disk_blocks_create(self, tmp_path, clock):
        # Pre-create a file matching the filename the clock will produce.
        portfolios_dir = tmp_path / "portfolios"
        portfolios_dir.mkdir(parents=True)
        fixed_now = clock.current
        from pryces.infrastructure.repositories import _build_filename

        squatter = portfolios_dir / _build_filename(fixed_now)
        squatter.write_text("{}")
        repo = JsonPortfolioRepository(data_dir=tmp_path, clock=lambda: fixed_now)
        with pytest.raises(PortfolioAlreadyExists):
            repo.create("EUR", name="main")


class TestCreateWithDefaultName:
    def test_default_name_uses_clock_timestamp(self, repo, clock):
        # The clock is anchored to 2026-05-28 14:20:35 — default name should
        # match that second.
        summary = repo.create("EUR")
        assert summary.name == "portfolio_2026-05-28_14-20-35"

    def test_default_name_collision_auto_bumps(self, tmp_path):
        same_second = datetime(2026, 5, 28, 14, 20, 35, 100, tzinfo=timezone.utc)
        # Clock returns the same second every time (but advancing micros so
        # filenames don't collide on disk).
        micros = iter(range(1000))

        def clock() -> datetime:
            return same_second.replace(microsecond=next(micros))

        repo = JsonPortfolioRepository(data_dir=tmp_path, clock=clock)
        first = repo.create("EUR")
        second = repo.create("EUR")
        third = repo.create("EUR")
        assert first.name == "portfolio_2026-05-28_14-20-35"
        assert second.name == "portfolio_2026-05-28_14-20-35_2"
        assert third.name == "portfolio_2026-05-28_14-20-35_3"


class TestListPortfolios:
    def test_empty_returns_empty_list(self, repo):
        assert repo.list_portfolios() == []

    def test_returns_summaries_sorted_by_name(self, repo):
        repo.create("EUR", name="zeta")
        repo.create("USD", name="alpha")
        names = [p.name for p in repo.list_portfolios()]
        assert names == ["alpha", "zeta"]

    def test_skips_stale_index_entries(self, repo, tmp_path, caplog):
        repo.create("EUR", name="main")
        # Simulate someone deleting the portfolio file out from under the index.
        portfolios_dir = tmp_path / "portfolios"
        for path in portfolios_dir.glob("portfolio_*.json"):
            path.unlink()
        with caplog.at_level("WARNING"):
            summaries = repo.list_portfolios()
        assert summaries == []
        assert any("missing file" in record.message for record in caplog.records)

    def test_ignores_orphan_files(self, repo, tmp_path):
        repo.create("EUR", name="main")
        # Drop in an extra portfolio file with no index entry.
        orphan = tmp_path / "portfolios" / "portfolio_20990101T000000000000Z.json"
        orphan.write_text(
            json.dumps({"base_currency": "JPY", "transactions": [], "manual_assets": []})
        )
        names = [p.name for p in repo.list_portfolios()]
        assert names == ["main"]


class TestFindSummary:
    def test_returns_none_when_missing(self, repo):
        assert repo.find_summary_by_name("missing") is None

    def test_includes_transaction_count(self, repo):
        repo.create("EUR", name="main")
        repo.add_transactions("main", [_buy(raw_id="a"), _buy(raw_id="b")])
        assert repo.find_summary_by_name("main").transaction_count == 2


class TestRename:
    def test_updates_index_only(self, repo, tmp_path):
        repo.create("EUR", name="main")
        portfolios_dir = tmp_path / "portfolios"
        original_filename = json.loads((portfolios_dir / INDEX_FILENAME).read_text())["portfolios"][
            "main"
        ]

        repo.rename("main", "primary")

        index = json.loads((portfolios_dir / INDEX_FILENAME).read_text())
        assert "main" not in index["portfolios"]
        assert index["portfolios"]["primary"] == original_filename
        # Same file is still there.
        assert (portfolios_dir / original_filename).exists()

    def test_rename_to_existing_raises(self, repo):
        repo.create("EUR", name="main")
        repo.create("USD", name="other")
        with pytest.raises(PortfolioAlreadyExists):
            repo.rename("main", "other")

    def test_rename_missing_raises(self, repo):
        with pytest.raises(PortfolioNotFound):
            repo.rename("missing", "new")

    def test_same_name_is_noop(self, repo):
        repo.create("EUR", name="main")
        repo.rename("main", "main")  # must not raise
        assert repo.find_summary_by_name("main") is not None

    def test_transactions_survive_rename(self, repo):
        repo.create("EUR", name="main")
        repo.add_transactions("main", [_buy(raw_id="a")])
        repo.rename("main", "primary")
        assert len(repo.get_transactions("primary")) == 1


class TestDelete:
    def test_removes_index_entry_and_file(self, repo, tmp_path):
        repo.create("EUR", name="main")
        portfolios_dir = tmp_path / "portfolios"
        filename = json.loads((portfolios_dir / INDEX_FILENAME).read_text())["portfolios"]["main"]
        repo.delete("main")
        index = json.loads((portfolios_dir / INDEX_FILENAME).read_text())
        assert "main" not in index["portfolios"]
        assert not (portfolios_dir / filename).exists()

    def test_delete_missing_raises(self, repo):
        with pytest.raises(PortfolioNotFound):
            repo.delete("missing")

    def test_delete_tolerates_already_missing_file(self, repo, tmp_path):
        repo.create("EUR", name="main")
        # Pre-emptive manual cleanup of the file.
        portfolios_dir = tmp_path / "portfolios"
        for path in portfolios_dir.glob("portfolio_*.json"):
            path.unlink()
        # Should not raise — index entry still cleaned up.
        repo.delete("main")
        assert repo.find_summary_by_name("main") is None


class TestAddTransactions:
    def test_returns_inserted_count(self, repo):
        repo.create("EUR", name="main")
        count = repo.add_transactions(
            "main", [_buy(raw_id="a"), _buy(raw_id="b"), _buy(raw_id="c")]
        )
        assert count == 3

    def test_dedup_skips_known_raw_ids(self, repo):
        repo.create("EUR", name="main")
        repo.add_transactions("main", [_buy(raw_id="a"), _buy(raw_id="b")])
        again = repo.add_transactions("main", [_buy(raw_id="a"), _buy(raw_id="c")])
        assert again == 1
        assert len(repo.get_transactions("main")) == 3

    def test_no_dedup_when_raw_id_missing(self, repo):
        repo.create("EUR", name="main")
        repo.add_transactions("main", [_buy(raw_id=None)])
        again = repo.add_transactions("main", [_buy(raw_id=None)])
        assert again == 1
        assert len(repo.get_transactions("main")) == 2

    def test_same_raw_id_isolated_per_portfolio(self, repo):
        repo.create("EUR", name="main")
        repo.create("EUR", name="side")
        repo.add_transactions("main", [_buy(raw_id="x")])
        count = repo.add_transactions("side", [_buy(raw_id="x")])
        assert count == 1

    def test_add_to_missing_portfolio_raises(self, repo):
        with pytest.raises(PortfolioNotFound):
            repo.add_transactions("missing", [_buy(raw_id="a")])

    def test_round_trips_all_fields_for_a_trade(self, repo):
        repo.create("EUR", name="main")
        repo.add_transactions("main", [_buy(raw_id="a")])
        txn = repo.get_transactions("main")[0]
        assert txn.type == TransactionType.BUY
        assert txn.symbol == "AAPL"
        assert txn.quantity == Decimal("5")
        assert txn.price == Decimal("100")
        assert txn.currency == Currency.USD
        assert txn.fee == Decimal("1")
        assert txn.broker == "IBKR"
        assert txn.raw_id == "a"

    def test_round_trips_dividend(self, repo):
        repo.create("EUR", name="main")
        repo.add_transactions("main", [_dividend(amount="2.4")])
        txn = repo.get_transactions("main")[0]
        assert txn.type == TransactionType.DIVIDEND
        assert txn.amount == Decimal("2.4")
        assert txn.quantity is None
        assert txn.price is None

    def test_returns_zero_when_all_are_duplicates(self, repo):
        repo.create("EUR", name="main")
        repo.add_transactions("main", [_buy(raw_id="a")])
        assert repo.add_transactions("main", [_buy(raw_id="a")]) == 0


class TestDecimalPrecision:
    def test_preserves_high_precision_quantity(self, repo):
        repo.create("EUR", name="main")
        repo.add_transactions(
            "main",
            [
                Transaction(
                    date=date(2024, 1, 10),
                    type=TransactionType.BUY,
                    symbol="BTC-USD",
                    currency=Currency.USD,
                    quantity=Decimal("0.12345678"),
                    price=Decimal("43210.99"),
                    fee=Decimal("0.50"),
                    raw_id="x",
                )
            ],
        )
        txn = repo.get_transactions("main")[0]
        assert txn.quantity == Decimal("0.12345678")
        assert txn.price == Decimal("43210.99")

    def test_preserves_trailing_zeros(self, repo):
        repo.create("EUR", name="main")
        repo.add_transactions("main", [_buy(price="100.00", raw_id="x")])
        txn = repo.get_transactions("main")[0]
        assert str(txn.price) == "100.00"


class TestManualAssets:
    def test_set_and_get_roundtrip(self, repo):
        repo.create("EUR", name="main")
        assets = [
            ManualAsset(name="Home", asset_type="real_estate", value_base=Decimal("250000")),
            ManualAsset(name="Pension", asset_type="pension", value_base=Decimal("30000.50")),
        ]
        repo.set_manual_assets("main", assets)
        assert repo.get_manual_assets("main") == assets

    def test_set_replaces_previous(self, repo):
        repo.create("EUR", name="main")
        repo.set_manual_assets(
            "main",
            [ManualAsset(name="Home", asset_type="real_estate", value_base=Decimal("250000"))],
        )
        repo.set_manual_assets(
            "main",
            [ManualAsset(name="Pension", asset_type="pension", value_base=Decimal("30000"))],
        )
        assets = repo.get_manual_assets("main")
        assert len(assets) == 1
        assert assets[0].name == "Pension"

    def test_set_on_missing_portfolio_raises(self, repo):
        with pytest.raises(PortfolioNotFound):
            repo.set_manual_assets("missing", [])

    def test_get_returns_empty_when_no_assets(self, repo):
        repo.create("EUR", name="main")
        assert repo.get_manual_assets("main") == []


class TestAtomicWrite:
    def test_no_tmp_files_left_behind(self, repo, tmp_path):
        repo.create("EUR", name="main")
        repo.add_transactions("main", [_buy(raw_id="a")])
        repo.rename("main", "primary")
        repo.delete("primary")
        portfolios_dir = tmp_path / "portfolios"
        if portfolios_dir.exists():
            leftover = list(portfolios_dir.glob("*.tmp"))
            assert leftover == []


class TestMultiUserIsolation:
    def test_user_1_uses_default_directory(self, repo, tmp_path):
        repo.create("EUR", name="main", user_id=1)
        assert (tmp_path / "portfolios" / INDEX_FILENAME).exists()

    def test_other_users_get_their_own_subtree(self, repo, tmp_path):
        repo.create("EUR", name="main", user_id=2)
        assert (tmp_path / "users" / "2" / "portfolios" / INDEX_FILENAME).exists()

    def test_same_name_allowed_across_users(self, repo):
        repo.create("EUR", name="main", user_id=1)
        repo.create("USD", name="main", user_id=2)
        assert repo.find_summary_by_name("main", user_id=1).base_currency == "EUR"
        assert repo.find_summary_by_name("main", user_id=2).base_currency == "USD"
