from collections import Counter
from dataclasses import dataclass
from decimal import Decimal

from ...domain.portfolio.portfolio import Overview, Portfolio, PortfolioBreakdown
from ...domain.portfolio.transactions import Transaction
from ...domain.stocks import Currency
from ..interfaces import PortfolioRepository
from .get_portfolio import GetPortfolio

_DEFAULT_BASE = Currency.EUR


@dataclass(frozen=True)
class GetOverviewRequest:
    user_id: int = 1


class GetOverview:
    """Rolls every portfolio up into one unified net-worth view.

    Each portfolio is built once in the unified base currency (so its totals are
    directly summable); positions are merged across portfolios by symbol, and a
    single XIRR/TWR is computed over the union of all transactions. Delegates the
    actual portfolio construction + return math to GetPortfolio.
    """

    def __init__(self, repository: PortfolioRepository, portfolio_builder: GetPortfolio) -> None:
        self._repository = repository
        self._builder = portfolio_builder

    def handle(self, request: GetOverviewRequest) -> Overview:
        summaries = self._repository.list_portfolios(user_id=request.user_id)
        if not summaries:
            return Overview(portfolio=Portfolio(base_currency=_DEFAULT_BASE.value))

        base = self._pick_base_currency([s.base_currency for s in summaries])

        portfolios: list[Portfolio] = []
        breakdown: list[PortfolioBreakdown] = []
        union_transactions: list[Transaction] = []
        for summary in summaries:
            transactions = self._repository.get_transactions(summary.name, user_id=request.user_id)
            manual_assets = self._repository.get_manual_assets(
                summary.name, user_id=request.user_id
            )
            portfolio = self._builder.build(transactions, manual_assets, base)
            portfolios.append(portfolio)
            union_transactions.extend(transactions)
            breakdown.append(
                PortfolioBreakdown(
                    name=summary.name,
                    base_currency=summary.base_currency,
                    total_value=portfolio.total_value,
                    total_profit=portfolio.total_profit,
                    total_return_pct=portfolio.total_return_pct,
                )
            )

        all_positions = tuple(p for portfolio in portfolios for p in portfolio.positions)
        all_closed = tuple(c for portfolio in portfolios for c in portfolio.closed_positions)
        all_manual = tuple(m for portfolio in portfolios for m in portfolio.manual_assets)
        # Collapse the same symbol held across portfolios into one row.
        merged_positions = Portfolio(
            base_currency=base.value, positions=all_positions
        ).unified_positions

        terminal_value = sum((p.value_base for p in merged_positions), Decimal("0"))
        xirr_pct, twr_pct = self._builder.compute_returns(union_transactions, base, terminal_value)

        combined = Portfolio(
            base_currency=base.value,
            positions=merged_positions,
            manual_assets=all_manual,
            closed_positions=all_closed,
            xirr_pct=xirr_pct,
            twr_pct=twr_pct,
        )
        return Overview(portfolio=combined, breakdown=tuple(breakdown))

    @staticmethod
    def _pick_base_currency(currencies: list[str]) -> Currency:
        # Most common base across the user's portfolios; ties/unknowns fall back
        # to EUR. The overview converts every portfolio into this one currency.
        for code, _count in Counter(currencies).most_common():
            try:
                return Currency(code)
            except ValueError:
                continue
        return _DEFAULT_BASE
