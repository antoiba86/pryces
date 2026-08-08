from __future__ import annotations

from dataclasses import dataclass, replace

from ...domain.portfolio.transactions import Instrument, Transaction, distinct_brokers
from ..dtos import ImportResultDTO
from ..exceptions import PortfolioBrokerMismatch, UnrecognizedImportFormat
from ..importers import ImporterRegistry
from ..interfaces import PortfolioRepository, SymbolResolver
from ..text import describe_content


@dataclass(frozen=True)
class ImportTransactionsRequest:
    portfolio_name: str
    content: bytes
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
            raise UnrecognizedImportFormat(
                request.broker or "auto", self._registry.diagnose(request.content)
            )

        try:
            result = importer.parse(request.content)
        except UnrecognizedImportFormat as error:
            # The importer matched on `can_parse` but choked on the body. Keep
            # its own explanation when it has one — it knows why far better than
            # a header preview does — and fall back to describing the file only
            # when it raised bare.
            raise UnrecognizedImportFormat(
                error.broker_id, error.detail or describe_content(request.content)
            ) from error
        mapping, unresolved = self._resolve(result.instruments, result.transactions)
        transactions = [
            replace(tx, symbol=mapping.get(tx.symbol, tx.symbol)) for tx in result.transactions
        ]

        # Single-broker rule: a portfolio holds one broker. An import is allowed
        # only into an empty/manual-only portfolio (which then adopts the file's
        # broker) or one already on that same broker. Compare on the broker label
        # the transactions carry (manual entries carry None and are ignored).
        existing = distinct_brokers(
            self._repository.get_transactions(request.portfolio_name, request.user_id)
        )
        # Checked against everything parsed, not just what will be stored: a file
        # whose instruments all fail to resolve must still be refused by a
        # portfolio belonging to another broker.
        incoming = distinct_brokers(transactions)
        if len(existing | incoming) > 1:
            raise PortfolioBrokerMismatch(", ".join(sorted(existing)), ", ".join(sorted(incoming)))

        # Rows whose instrument never resolved are skipped rather than stored
        # under the raw product name. Such a row cannot be priced, so it is left
        # out of positions and totals anyway — storing it just hides broken data
        # in the ledger. Skipping loses nothing: `raw_id` comes from the file's
        # contents, never from resolution, so re-importing the same file after
        # adding a symbol mapping inserts exactly these rows and dedupes the rest.
        unresolved_set = set(unresolved)
        storable = [tx for tx in transactions if tx.symbol not in unresolved_set]
        skipped = len(transactions) - len(storable)

        inserted = self._repository.add_transactions(
            request.portfolio_name, storable, request.user_id
        )

        warnings = tuple(warning.message for warning in result.warnings)
        warnings += tuple(
            f"Unresolved symbol, rows not imported: {symbol}" for symbol in unresolved
        )
        return ImportResultDTO(
            broker=importer.broker_id,
            parsed=len(transactions),
            inserted=inserted,
            skipped_unresolved=skipped,
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
