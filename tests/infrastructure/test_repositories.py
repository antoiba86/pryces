import json
from datetime import date
from decimal import Decimal

import pytest

from pryces.application.exceptions import PortfolioAlreadyExists, PortfolioNotFound
from pryces.domain.portfolio.portfolio import ManualAsset
from pryces.domain.portfolio.transactions import Transaction, TransactionType
from pryces.domain.stocks import Currency
from pryces.infrastructure.repositories import (
    DATA_DIR_ENV_VAR,
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


@pytest.fixture
def repo(tmp_path):
    return JsonPortfolioRepository(data_dir=tmp_path)


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
        assert str(result).startswith(str(__import__("pathlib").Path.home()))
        assert result.name == "custom-dir"


class TestJsonPortfolioCreateAndList:
    def test_create_returns_summary(self, repo):
        summary = repo.create("main", "EUR")
        assert summary.name == "main"
        assert summary.base_currency == "EUR"
        assert summary.transaction_count == 0

    def test_create_persists_file(self, repo, tmp_path):
        repo.create("main", "EUR")
        path = tmp_path / "portfolios" / "main.json"
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["name"] == "main"
        assert data["base_currency"] == "EUR"
        assert data["transactions"] == []
        assert data["manual_assets"] == []

    def test_list_is_empty_initially(self, repo):
        assert repo.list_portfolios() == []

    def test_list_returns_summaries_sorted_by_filename(self, repo):
        repo.create("zeta", "EUR")
        repo.create("alpha", "USD")
        names = [p.name for p in repo.list_portfolios()]
        assert names == ["alpha", "zeta"]

    def test_create_duplicate_raises(self, repo):
        repo.create("main", "EUR")
        with pytest.raises(PortfolioAlreadyExists):
            repo.create("main", "USD")

    def test_find_summary_missing_returns_none(self, repo):
        assert repo.find_summary_by_name("missing") is None

    def test_find_summary_includes_transaction_count(self, repo):
        repo.create("main", "EUR")
        repo.add_transactions("main", [_buy(raw_id="a"), _buy(raw_id="b")])
        assert repo.find_summary_by_name("main").transaction_count == 2


class TestJsonPortfolioDelete:
    def test_delete_removes_file(self, repo, tmp_path):
        repo.create("main", "EUR")
        repo.delete("main")
        assert not (tmp_path / "portfolios" / "main.json").exists()

    def test_delete_unknown_raises(self, repo):
        with pytest.raises(PortfolioNotFound):
            repo.delete("missing")


class TestJsonAddTransactions:
    def test_returns_inserted_count(self, repo):
        repo.create("main", "EUR")
        count = repo.add_transactions(
            "main", [_buy(raw_id="a"), _buy(raw_id="b"), _buy(raw_id="c")]
        )
        assert count == 3

    def test_dedup_skips_known_raw_ids(self, repo):
        repo.create("main", "EUR")
        repo.add_transactions("main", [_buy(raw_id="a"), _buy(raw_id="b")])
        again = repo.add_transactions("main", [_buy(raw_id="a"), _buy(raw_id="c")])
        assert again == 1
        assert len(repo.get_transactions("main")) == 3

    def test_no_dedup_when_raw_id_missing(self, repo):
        repo.create("main", "EUR")
        repo.add_transactions("main", [_buy(raw_id=None)])
        again = repo.add_transactions("main", [_buy(raw_id=None)])
        assert again == 1
        assert len(repo.get_transactions("main")) == 2

    def test_same_raw_id_isolated_per_portfolio(self, repo):
        repo.create("main", "EUR")
        repo.create("side", "EUR")
        repo.add_transactions("main", [_buy(raw_id="x")])
        count = repo.add_transactions("side", [_buy(raw_id="x")])
        assert count == 1

    def test_add_to_missing_portfolio_raises(self, repo):
        with pytest.raises(PortfolioNotFound):
            repo.add_transactions("missing", [_buy(raw_id="a")])

    def test_round_trips_all_fields_for_a_trade(self, repo):
        repo.create("main", "EUR")
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
        repo.create("main", "EUR")
        repo.add_transactions("main", [_dividend(amount="2.4")])
        txn = repo.get_transactions("main")[0]
        assert txn.type == TransactionType.DIVIDEND
        assert txn.amount == Decimal("2.4")
        assert txn.quantity is None
        assert txn.price is None

    def test_returns_zero_when_all_are_duplicates(self, repo):
        repo.create("main", "EUR")
        repo.add_transactions("main", [_buy(raw_id="a")])
        assert repo.add_transactions("main", [_buy(raw_id="a")]) == 0


class TestDecimalPrecision:
    def test_preserves_high_precision_quantity(self, repo):
        repo.create("main", "EUR")
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
        repo.create("main", "EUR")
        repo.add_transactions("main", [_buy(price="100.00", raw_id="x")])
        txn = repo.get_transactions("main")[0]
        # As a string round-trip — exact text preserved.
        assert str(txn.price) == "100.00"


class TestJsonManualAssets:
    def test_set_and_get_roundtrip(self, repo):
        repo.create("main", "EUR")
        assets = [
            ManualAsset(name="Home", asset_type="real_estate", value_base=Decimal("250000")),
            ManualAsset(name="Pension", asset_type="pension", value_base=Decimal("30000.50")),
        ]
        repo.set_manual_assets("main", assets)
        assert repo.get_manual_assets("main") == assets

    def test_set_replaces_previous(self, repo):
        repo.create("main", "EUR")
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
        repo.create("main", "EUR")
        assert repo.get_manual_assets("main") == []


class TestAtomicWrite:
    def test_no_tmp_file_left_behind(self, repo, tmp_path):
        repo.create("main", "EUR")
        repo.add_transactions("main", [_buy(raw_id="a")])
        leftover = list((tmp_path / "portfolios").glob("*.tmp"))
        assert leftover == []


class TestMultiUserIsolation:
    def test_user_1_default_directory(self, repo, tmp_path):
        repo.create("main", "EUR", user_id=1)
        assert (tmp_path / "portfolios" / "main.json").exists()

    def test_other_users_get_their_own_subtree(self, repo, tmp_path):
        repo.create("main", "EUR", user_id=2)
        assert (tmp_path / "users" / "2" / "portfolios" / "main.json").exists()

    def test_same_name_isolated_across_users(self, repo):
        repo.create("main", "EUR", user_id=1)
        # Should not collide.
        repo.create("main", "USD", user_id=2)
        assert [p.name for p in repo.list_portfolios(user_id=1)] == ["main"]
        assert repo.find_summary_by_name("main", user_id=1).base_currency == "EUR"
        assert repo.find_summary_by_name("main", user_id=2).base_currency == "USD"
