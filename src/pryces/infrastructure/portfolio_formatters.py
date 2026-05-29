from __future__ import annotations

from decimal import Decimal

from pryces.domain.portfolio.formatters import PortfolioFormatter
from pryces.domain.portfolio.portfolio import ManualAsset, Portfolio, Position

_TELEGRAM_MAX_LENGTH = 4096


class TelegramPortfolioFormatter(PortfolioFormatter):
    def format(self, portfolio: Portfolio) -> list[str]:
        sections: list[str] = [self._header(portfolio)]

        positions_section = self._positions_section(portfolio)
        if positions_section is not None:
            sections.append(positions_section)

        manual_section = self._manual_assets_section(portfolio)
        if manual_section is not None:
            sections.append(manual_section)

        sections.append(self._totals_section(portfolio))

        return self._pack(sections)

    def _header(self, portfolio: Portfolio) -> str:
        return (
            f"📊 Portfolio ({portfolio.base_currency})\n"
            f"Total value: {self._money(portfolio.total_value)} {portfolio.base_currency}"
        )

    def _positions_section(self, portfolio: Portfolio) -> str | None:
        if not portfolio.positions:
            return None

        lines = ["📈 Holdings"]
        for position in portfolio.unified_positions:
            lines.append(self._position_line(position, portfolio))
        return "\n".join(lines)

    def _position_line(self, position: Position, portfolio: Portfolio) -> str:
        allocation = portfolio.allocation_for(position)
        return_pct = position.total_return_pct
        return (
            f"• {position.symbol} — "
            f"{self._quantity(position.quantity)} @ {self._money(position.price)} "
            f"{position.currency.value} | "
            f"{self._money(position.value_base)} {portfolio.base_currency} "
            f"({self._percent(allocation)}, {self._signed_percent(return_pct)})"
        )

    def _manual_assets_section(self, portfolio: Portfolio) -> str | None:
        if not portfolio.manual_assets:
            return None

        lines = ["🏠 Manual assets"]
        for asset in portfolio.manual_assets:
            lines.append(self._manual_asset_line(asset, portfolio))
        return "\n".join(lines)

    def _manual_asset_line(self, asset: ManualAsset, portfolio: Portfolio) -> str:
        allocation = portfolio.manual_allocation(asset)
        return (
            f"• {asset.name} ({asset.asset_type}) — "
            f"{self._money(asset.value_base)} {portfolio.base_currency} "
            f"({self._percent(allocation)})"
        )

    def _totals_section(self, portfolio: Portfolio) -> str:
        base = portfolio.base_currency
        lines = [
            "📊 Totals",
            f"Positions: {self._money(portfolio.positions_value)} {base}",
            f"Manual: {self._money(portfolio.manual_value)} {base}",
            f"Total: {self._money(portfolio.total_value)} {base}",
        ]
        if portfolio.positions:
            lines.append(
                f"Unrealized P&L: {self._signed_money(portfolio.total_unrealized_pnl)} {base}"
            )
            lines.append(f"Total return: {self._signed_percent(portfolio.total_return_pct)}")
        if portfolio.xirr_pct is not None:
            lines.append(f"XIRR: {self._signed_percent(portfolio.xirr_pct)}")
        if portfolio.twr_pct is not None:
            lines.append(f"TWR: {self._signed_percent(portfolio.twr_pct)}")
        return "\n".join(lines)

    def _pack(self, sections: list[str]) -> list[str]:
        messages: list[str] = []
        current = ""
        for section in sections:
            for chunk in self._split_section(section):
                if not current:
                    current = chunk
                    continue
                candidate = f"{current}\n\n{chunk}"
                if len(candidate) <= _TELEGRAM_MAX_LENGTH:
                    current = candidate
                else:
                    messages.append(current)
                    current = chunk
        if current:
            messages.append(current)
        return messages

    @staticmethod
    def _split_section(section: str) -> list[str]:
        if len(section) <= _TELEGRAM_MAX_LENGTH:
            return [section]
        lines = section.split("\n")
        chunks: list[str] = []
        current = ""
        for line in lines:
            candidate = f"{current}\n{line}" if current else line
            if len(candidate) <= _TELEGRAM_MAX_LENGTH:
                current = candidate
            else:
                if current:
                    chunks.append(current)
                current = line
        if current:
            chunks.append(current)
        return chunks

    @staticmethod
    def _money(value: Decimal) -> str:
        return f"{value:,.2f}"

    @staticmethod
    def _signed_money(value: Decimal) -> str:
        sign = "+" if value >= 0 else ""
        return f"{sign}{value:,.2f}"

    @staticmethod
    def _quantity(value: Decimal) -> str:
        normalized = value.normalize()
        text = format(normalized, "f")
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return text or "0"

    @staticmethod
    def _percent(value: Decimal) -> str:
        return f"{value:.2f}%"

    @staticmethod
    def _signed_percent(value: Decimal) -> str:
        sign = "+" if value >= 0 else ""
        return f"{sign}{value:.2f}%"
