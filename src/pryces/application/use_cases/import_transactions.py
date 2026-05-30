from __future__ import annotations

from dataclasses import dataclass, replace

from ...domain.portfolio.transactions import Instrument, Transaction
from ..dtos import ImportResultDTO
from ..exceptions import UnrecognizedImportFormat
from ..importers import ImporterRegistry
from ..interfaces import PortfolioRepository, SymbolResolver


@dataclass(frozen=True)
class ImportTransactionsRequest:
    portfolio_name: str
    content: str
    broker: str | None = None
    user_id: int = 1


class ImportTransactions:
    """Parses a broker export, resolves Yahoo tickers, and persists the result.

    Picks the importer (explicit broker override, else auto-detect), parses the
    content, resolves each instrument's symbol to a Yahoo ticker via the
    SymbolResolver (instruments that don't resolve keep their original symbol
    and are reported as warnings), then delegates persistence — and broker +
    raw_id deduplication — to the repository.
    """

    def __init__(
        self,
        registry: ImporterRegistry,
        resolver: SymbolResolver,
        repository: PortfolioRepository,
    ) -> None:
        self._registry = registry
        self._resolver = resolver
        self._repository = repository

    def handle(self, request: ImportTransactionsRequest) -> ImportResultDTO:
        importer = (
            self._registry.get(request.broker)
            if request.broker
            else self._registry.auto_detect(request.content)
        )
        if importer is None:
            raise UnrecognizedImportFormat(request.broker or "auto")

        result = importer.parse(request.content)
        mapping, unresolved = self._resolve(result.instruments, result.transactions)
        transactions = [
            replace(tx, symbol=mapping.get(tx.symbol, tx.symbol)) for tx in result.transactions
        ]
        inserted = self._repository.add_transactions(
            request.portfolio_name, transactions, request.user_id
        )

        warnings = tuple(warning.message for warning in result.warnings)
        warnings += tuple(f"Unresolved symbol: {symbol}" for symbol in unresolved)
        return ImportResultDTO(
            broker=importer.broker_id,
            parsed=len(transactions),
            inserted=inserted,
            unresolved_symbols=tuple(unresolved),
            warnings=warnings,
        )

    def _resolve(
        self,
        instruments: tuple[Instrument, ...],
        transactions: tuple[Transaction, ...],
    ) -> tuple[dict[str, str], list[str]]:
        # Importers that don't emit instruments (e.g. the JSON ledger) carry
        # ready-to-use tickers on the transactions themselves; build pass-through
        # instruments from the distinct symbols so resolution is uniform.
        if not instruments:
            instruments = tuple(
                Instrument(symbol=symbol)
                for symbol in dict.fromkeys(tx.symbol for tx in transactions)
            )

        mapping: dict[str, str] = {}
        unresolved: list[str] = []
        for instrument in instruments:
            ticker = self._resolver.resolve(instrument)
            if ticker is None:
                unresolved.append(instrument.symbol)
            elif ticker != instrument.symbol:
                mapping[instrument.symbol] = ticker
        return mapping, unresolved
