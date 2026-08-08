from __future__ import annotations

from dataclasses import dataclass

from ..exceptions import SymbolMappingNotFound
from ..interfaces import StockProvider, SymbolMapStore


@dataclass(frozen=True)
class SymbolMapEntryDTO:
    """One mapping, plus what the ticker turned out to be.

    `verified` is None when no check was performed, True when the ticker quotes,
    False when it does not. A False is reported, never enforced: Yahoo rate-limits
    and goes down, and refusing to save then would lock the user out of the only
    fix for an unresolvable instrument.
    """

    key: str
    ticker: str
    verified: bool | None = None
    name: str | None = None
    currency: str | None = None


@dataclass(frozen=True)
class SetSymbolMappingRequest:
    key: str
    ticker: str
    verify: bool = True


class GetSymbolMap:
    """Lists every mapping, sorted by key so the UI order is stable."""

    def __init__(self, store: SymbolMapStore) -> None:
        self._store = store

    def handle(self) -> list[SymbolMapEntryDTO]:
        mapping = self._store.all()
        return [SymbolMapEntryDTO(key=key, ticker=mapping[key]) for key in sorted(mapping)]


class SetSymbolMapping:
    """Adds or replaces one mapping, verifying the ticker when possible.

    Verification is what makes this usable: the point of a mapping is that the
    ticker prices, and a typo is otherwise only discovered on the next import.
    """

    def __init__(self, store: SymbolMapStore, stock_provider: StockProvider | None = None) -> None:
        self._store = store
        self._stock_provider = stock_provider

    def handle(self, request: SetSymbolMappingRequest) -> SymbolMapEntryDTO:
        key = request.key.strip()
        ticker = request.ticker.strip()
        if not key:
            raise ValueError("key must not be empty")
        if not ticker:
            raise ValueError("ticker must not be empty")

        verified: bool | None = None
        name: str | None = None
        currency: str | None = None
        if request.verify and self._stock_provider is not None:
            stock = self._quote(ticker)
            verified = stock is not None
            if stock is not None:
                name = stock.name
                currency = stock.currency.value if stock.currency is not None else None

        self._store.put(key, ticker)
        return SymbolMapEntryDTO(
            key=key.upper(), ticker=ticker, verified=verified, name=name, currency=currency
        )

    def _quote(self, ticker: str):
        try:
            stocks = self._stock_provider.get_stocks([ticker])
        except Exception:
            # An unreachable or throttled Yahoo means "unknown", not "invalid".
            return None
        return stocks[0] if stocks else None


class DeleteSymbolMapping:
    def __init__(self, store: SymbolMapStore) -> None:
        self._store = store

    def handle(self, key: str) -> None:
        if not self._store.delete(key):
            raise SymbolMappingNotFound(key)
