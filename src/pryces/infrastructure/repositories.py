from __future__ import annotations

import json
import os
from datetime import date
from decimal import Decimal
from pathlib import Path

from ..application.exceptions import PortfolioAlreadyExists, PortfolioNotFound
from ..application.interfaces import PortfolioRepository, StockRepository
from ..domain.portfolio.portfolio import ManualAsset, PortfolioSummary
from ..domain.portfolio.transactions import Transaction, TransactionType
from ..domain.stocks import Currency, Stock

DEFAULT_DATA_DIR = Path.home() / ".pryces"
DATA_DIR_ENV_VAR = "PRYCES_DATA_DIR"
PORTFOLIOS_SUBDIR = "portfolios"


def resolve_data_dir() -> Path:
    override = os.environ.get(DATA_DIR_ENV_VAR)
    return Path(override).expanduser() if override else DEFAULT_DATA_DIR


class InMemoryStockRepository(StockRepository):
    def __init__(self) -> None:
        self._store: dict[str, Stock] = {}

    def save_batch(self, stocks: list[Stock]) -> None:
        for stock in stocks:
            self._store[stock.symbol] = stock

    def get(self, symbol: str) -> Stock | None:
        return self._store.get(symbol)


class JsonPortfolioRepository(PortfolioRepository):
    """One JSON file per portfolio at {data_dir}/portfolios/{name}.json.

    Decimals are stored as JSON strings to preserve precision. Writes are
    atomic via tmp-file + os.replace so a crash mid-write never leaves a
    half-written file.

    User scoping: each user_id gets its own subdirectory
    ({data_dir}/portfolios/) for user_id=1, and ({data_dir}/users/{id}/
    portfolios/) for any other id — additive so today's files keep working
    when auth lands later.
    """

    def __init__(self, data_dir: Path | None = None) -> None:
        self._data_dir = data_dir if data_dir is not None else resolve_data_dir()

    def list_portfolios(self, user_id: int = 1) -> list[PortfolioSummary]:
        directory = self._portfolios_dir(user_id)
        if not directory.exists():
            return []
        summaries: list[PortfolioSummary] = []
        for path in sorted(directory.glob("*.json")):
            data = self._read(path)
            summaries.append(
                PortfolioSummary(
                    name=data["name"],
                    base_currency=data["base_currency"],
                    transaction_count=len(data.get("transactions", [])),
                )
            )
        return summaries

    def find_summary_by_name(self, name: str, user_id: int = 1) -> PortfolioSummary | None:
        path = self._path_for(name, user_id)
        if not path.exists():
            return None
        data = self._read(path)
        return PortfolioSummary(
            name=data["name"],
            base_currency=data["base_currency"],
            transaction_count=len(data.get("transactions", [])),
        )

    def create(self, name: str, base_currency: str, user_id: int = 1) -> PortfolioSummary:
        path = self._path_for(name, user_id)
        if path.exists():
            raise PortfolioAlreadyExists(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._write(
            path,
            {
                "name": name,
                "base_currency": base_currency,
                "transactions": [],
                "manual_assets": [],
            },
        )
        return PortfolioSummary(name=name, base_currency=base_currency, transaction_count=0)

    def delete(self, name: str, user_id: int = 1) -> None:
        path = self._path_for(name, user_id)
        if not path.exists():
            raise PortfolioNotFound(name)
        path.unlink()

    def add_transactions(
        self,
        portfolio_name: str,
        transactions: list[Transaction],
        user_id: int = 1,
    ) -> int:
        data = self._require_portfolio(portfolio_name, user_id)
        existing_keys = {
            (row.get("broker"), row.get("raw_id"))
            for row in data["transactions"]
            if row.get("raw_id") is not None
        }
        added = 0
        for transaction in transactions:
            key = (transaction.broker, transaction.raw_id)
            if transaction.raw_id is not None and key in existing_keys:
                continue
            data["transactions"].append(_transaction_to_dict(transaction))
            if transaction.raw_id is not None:
                existing_keys.add(key)
            added += 1
        if added:
            self._write(self._path_for(portfolio_name, user_id), data)
        return added

    def get_transactions(self, portfolio_name: str, user_id: int = 1) -> list[Transaction]:
        data = self._require_portfolio(portfolio_name, user_id)
        return [_dict_to_transaction(row) for row in data["transactions"]]

    def set_manual_assets(
        self,
        portfolio_name: str,
        manual_assets: list[ManualAsset],
        user_id: int = 1,
    ) -> None:
        data = self._require_portfolio(portfolio_name, user_id)
        data["manual_assets"] = [_manual_asset_to_dict(asset) for asset in manual_assets]
        self._write(self._path_for(portfolio_name, user_id), data)

    def get_manual_assets(self, portfolio_name: str, user_id: int = 1) -> list[ManualAsset]:
        data = self._require_portfolio(portfolio_name, user_id)
        return [_dict_to_manual_asset(row) for row in data.get("manual_assets", [])]

    def _portfolios_dir(self, user_id: int) -> Path:
        if user_id == 1:
            return self._data_dir / PORTFOLIOS_SUBDIR
        return self._data_dir / "users" / str(user_id) / PORTFOLIOS_SUBDIR

    def _path_for(self, name: str, user_id: int) -> Path:
        return self._portfolios_dir(user_id) / f"{name}.json"

    def _require_portfolio(self, name: str, user_id: int) -> dict:
        path = self._path_for(name, user_id)
        if not path.exists():
            raise PortfolioNotFound(name)
        return self._read(path)

    @staticmethod
    def _read(path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _write(path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)


def _transaction_to_dict(transaction: Transaction) -> dict:
    row: dict = {
        "date": transaction.date.isoformat(),
        "type": transaction.type.value,
        "symbol": transaction.symbol,
        "currency": transaction.currency.value,
        "fee": str(transaction.fee),
    }
    if transaction.quantity is not None:
        row["quantity"] = str(transaction.quantity)
    if transaction.price is not None:
        row["price"] = str(transaction.price)
    if transaction.amount is not None:
        row["amount"] = str(transaction.amount)
    if transaction.broker is not None:
        row["broker"] = transaction.broker
    if transaction.raw_id is not None:
        row["raw_id"] = transaction.raw_id
    return row


def _dict_to_transaction(row: dict) -> Transaction:
    return Transaction(
        date=date.fromisoformat(row["date"]),
        type=TransactionType(row["type"]),
        symbol=row["symbol"],
        currency=Currency(row["currency"]),
        quantity=_to_decimal(row.get("quantity")),
        price=_to_decimal(row.get("price")),
        amount=_to_decimal(row.get("amount")),
        fee=_to_decimal_default_zero(row.get("fee")),
        broker=row.get("broker"),
        raw_id=row.get("raw_id"),
    )


def _manual_asset_to_dict(asset: ManualAsset) -> dict:
    return {
        "name": asset.name,
        "asset_type": asset.asset_type,
        "value_base": str(asset.value_base),
    }


def _dict_to_manual_asset(row: dict) -> ManualAsset:
    return ManualAsset(
        name=row["name"],
        asset_type=row["asset_type"],
        value_base=Decimal(row["value_base"]),
    )


def _to_decimal(value) -> Decimal | None:
    return Decimal(value) if value is not None else None


def _to_decimal_default_zero(value) -> Decimal:
    return Decimal(value) if value is not None else Decimal("0")
