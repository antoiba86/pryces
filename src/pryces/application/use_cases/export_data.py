from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from ..exceptions import PortfolioNotFound
from ..interfaces import PortfolioRepository
from ..serialization import build_export_document, manual_asset_to_dict, transaction_to_dict


@dataclass(frozen=True)
class ExportDataRequest:
    portfolio_name: str | None = None
    user_id: int = 1


class ExportData:
    """Builds the versioned export document for a user's portfolio data.

    Exports every portfolio (name, base currency, transactions, manual
    assets), or a single one when `portfolio_name` is given — same document
    shape either way, so one importer handles both.
    """

    def __init__(
        self,
        repository: PortfolioRepository,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._clock = clock if clock is not None else _utc_now

    def handle(self, request: ExportDataRequest) -> dict:
        if request.portfolio_name is not None:
            summary = self._repository.find_summary_by_name(request.portfolio_name, request.user_id)
            if summary is None:
                raise PortfolioNotFound(request.portfolio_name)
            summaries = [summary]
        else:
            summaries = self._repository.list_portfolios(request.user_id)

        entries = [
            self._entry(summary.name, summary.base_currency, request.user_id)
            for summary in summaries
        ]
        return build_export_document(entries, exported_at=self._clock().isoformat())

    def _entry(self, name: str, base_currency: str, user_id: int) -> dict:
        transactions = self._repository.get_transactions(name, user_id)
        manual_assets = self._repository.get_manual_assets(name, user_id)
        return {
            "name": name,
            "base_currency": base_currency,
            "transactions": [transaction_to_dict(transaction) for transaction in transactions],
            "manual_assets": [manual_asset_to_dict(asset) for asset in manual_assets],
        }


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
