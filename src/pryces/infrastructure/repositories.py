from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from datetime import date, datetime, timezone
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
INDEX_FILENAME = "index.json"
INDEX_VERSION = 1


_logger = logging.getLogger(__name__)


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
    """JSON-backed portfolio storage with a separate name → filename index.

    Layout (for user_id=1; other users get users/{id}/ prefix):
        {data_dir}/portfolios/index.json
        {data_dir}/portfolios/portfolio_<YYYYMMDDTHHMMSSffffffZ>.json

    The portfolio file content is just {base_currency, transactions,
    manual_assets} — no name field. The display name lives entirely in
    the index, which means renames touch only one file and external
    references to the portfolio file survive any rename.

    All writes are atomic via tmp-file + os.replace so a crash mid-write
    never corrupts an existing file.
    """

    def __init__(
        self,
        data_dir: Path | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._data_dir = data_dir if data_dir is not None else resolve_data_dir()
        self._clock = clock if clock is not None else _utc_now

    def list_portfolios(self, user_id: int = 1) -> list[PortfolioSummary]:
        index = self._load_index(user_id)
        summaries: list[PortfolioSummary] = []
        for name in sorted(index["portfolios"].keys()):
            filename = index["portfolios"][name]
            path = self._portfolios_dir(user_id) / filename
            if not path.exists():
                _logger.warning(
                    "Index entry %r points to missing file %s — skipping",
                    name,
                    filename,
                )
                continue
            data = self._read_json(path)
            summaries.append(
                PortfolioSummary(
                    name=name,
                    base_currency=data["base_currency"],
                    transaction_count=len(data.get("transactions", [])),
                )
            )
        return summaries

    def find_summary_by_name(self, name: str, user_id: int = 1) -> PortfolioSummary | None:
        try:
            data, _filename = self._load_portfolio(name, user_id)
        except PortfolioNotFound:
            return None
        return PortfolioSummary(
            name=name,
            base_currency=data["base_currency"],
            transaction_count=len(data.get("transactions", [])),
        )

    def create(
        self,
        base_currency: str,
        name: str | None = None,
        user_id: int = 1,
    ) -> PortfolioSummary:
        directory = self._portfolios_dir(user_id)
        directory.mkdir(parents=True, exist_ok=True)
        index = self._load_index(user_id)

        resolved_name = self._resolve_create_name(name, index)
        if resolved_name in index["portfolios"]:
            raise PortfolioAlreadyExists(resolved_name)

        now = self._clock()
        filename = _build_filename(now)
        file_path = directory / filename
        # Defense in depth: even at microsecond precision, refuse to overwrite
        # an existing file (covers manually-placed files and clock skew).
        if file_path.exists():
            raise PortfolioAlreadyExists(resolved_name)

        self._write_json(
            file_path,
            {
                "base_currency": base_currency,
                "transactions": [],
                "manual_assets": [],
            },
        )
        index["portfolios"][resolved_name] = filename
        self._write_index(user_id, index)
        return PortfolioSummary(
            name=resolved_name, base_currency=base_currency, transaction_count=0
        )

    def rename(self, old_name: str, new_name: str, user_id: int = 1) -> None:
        if old_name == new_name:
            return
        index = self._load_index(user_id)
        if old_name not in index["portfolios"]:
            raise PortfolioNotFound(old_name)
        if new_name in index["portfolios"]:
            raise PortfolioAlreadyExists(new_name)
        filename = index["portfolios"].pop(old_name)
        index["portfolios"][new_name] = filename
        self._write_index(user_id, index)

    def delete(self, name: str, user_id: int = 1) -> None:
        index = self._load_index(user_id)
        if name not in index["portfolios"]:
            raise PortfolioNotFound(name)
        filename = index["portfolios"].pop(name)
        file_path = self._portfolios_dir(user_id) / filename
        if file_path.exists():
            file_path.unlink()
        self._write_index(user_id, index)

    def add_transactions(
        self,
        portfolio_name: str,
        transactions: list[Transaction],
        user_id: int = 1,
    ) -> int:
        data, path = self._load_portfolio(portfolio_name, user_id)
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
            self._write_json(path, data)
        return added

    def get_transactions(self, portfolio_name: str, user_id: int = 1) -> list[Transaction]:
        data, _ = self._load_portfolio(portfolio_name, user_id)
        return [_dict_to_transaction(row) for row in data["transactions"]]

    def set_manual_assets(
        self,
        portfolio_name: str,
        manual_assets: list[ManualAsset],
        user_id: int = 1,
    ) -> None:
        data, path = self._load_portfolio(portfolio_name, user_id)
        data["manual_assets"] = [_manual_asset_to_dict(asset) for asset in manual_assets]
        self._write_json(path, data)

    def get_manual_assets(self, portfolio_name: str, user_id: int = 1) -> list[ManualAsset]:
        data, _ = self._load_portfolio(portfolio_name, user_id)
        return [_dict_to_manual_asset(row) for row in data.get("manual_assets", [])]

    def _resolve_create_name(self, name: str | None, index: dict) -> str:
        if name is not None:
            return name
        existing = set(index["portfolios"].keys())
        base = self._clock().strftime("portfolio_%Y-%m-%d_%H-%M-%S")
        if base not in existing:
            return base
        counter = 2
        while f"{base}_{counter}" in existing:
            counter += 1
        return f"{base}_{counter}"

    def _portfolios_dir(self, user_id: int) -> Path:
        if user_id == 1:
            return self._data_dir / PORTFOLIOS_SUBDIR
        return self._data_dir / "users" / str(user_id) / PORTFOLIOS_SUBDIR

    def _index_path(self, user_id: int) -> Path:
        return self._portfolios_dir(user_id) / INDEX_FILENAME

    def _load_index(self, user_id: int) -> dict:
        path = self._index_path(user_id)
        if not path.exists():
            return {"version": INDEX_VERSION, "portfolios": {}}
        index = self._read_json(path)
        # Defensive: tolerate older or partially-written files by filling in
        # the expected shape. We never silently drop unknown top-level keys
        # so a future migration can add fields without losing data.
        index.setdefault("version", INDEX_VERSION)
        index.setdefault("portfolios", {})
        return index

    def _write_index(self, user_id: int, index: dict) -> None:
        self._write_json(self._index_path(user_id), index)

    def _load_portfolio(self, name: str, user_id: int) -> tuple[dict, Path]:
        index = self._load_index(user_id)
        filename = index["portfolios"].get(name)
        if filename is None:
            raise PortfolioNotFound(name)
        path = self._portfolios_dir(user_id) / filename
        if not path.exists():
            raise PortfolioNotFound(name)
        return self._read_json(path), path

    @staticmethod
    def _read_json(path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _write_json(path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _build_filename(now: datetime) -> str:
    return now.strftime("portfolio_%Y%m%dT%H%M%S%fZ.json")


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
