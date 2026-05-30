from datetime import date
from decimal import Decimal

import pytest

from pryces.application.exceptions import UnrecognizedImportFormat
from pryces.application.importers import ImporterRegistry
from pryces.application.use_cases.import_transactions import (
    ImportTransactions,
    ImportTransactionsRequest,
)
from pryces.domain.portfolio.transactions import (
    ImportResult,
    ImportWarning,
    Instrument,
    Transaction,
    TransactionType,
    WarningLevel,
)
from pryces.domain.stocks import Currency


class _StubLogger:
    def debug(self, message): ...

    def info(self, message): ...

    def warning(self, message): ...

    def error(self, message): ...


class _StubLoggerFactory:
    def get_logger(self, name):
        return _StubLogger()


class _StubImporter:
    def __init__(self, broker_id, result, parseable=True):
        self._broker_id = broker_id
        self._result = result
        self._parseable = parseable

    @property
    def broker_id(self):
        return self._broker_id

    def can_parse(self, content):
        return self._parseable

    def parse(self, content):
        return self._result


class _MapResolver:
    def __init__(self, mapping):
        self._mapping = mapping

    def resolve(self, instrument):
        return self._mapping.get(instrument.symbol)


class _RecordingRepository:
    def __init__(self, inserted=0):
        self.inserted = inserted
        self.received = None

    def add_transactions(self, portfolio_name, transactions, user_id=1):
        self.received = (portfolio_name, transactions, user_id)
        return self.inserted


def _transaction(symbol, raw_id="r1"):
    return Transaction(
        date=date(2024, 1, 10),
        type=TransactionType.BUY,
        symbol=symbol,
        currency=Currency.USD,
        quantity=Decimal("5"),
        price=Decimal("100"),
        broker="DEGIRO",
        raw_id=raw_id,
    )


def _use_case(importer, resolver, repository):
    registry = ImporterRegistry([importer], _StubLoggerFactory())
    return ImportTransactions(registry, resolver, repository)


class TestImportTransactions:

    def test_resolves_symbols_before_persisting(self):
        result = ImportResult(
            transactions=(_transaction("US46222L1089"),),
            instruments=(Instrument(symbol="US46222L1089", isin="US46222L1089"),),
        )
        repository = _RecordingRepository(inserted=1)
        use_case = _use_case(
            _StubImporter("degiro", result),
            _MapResolver({"US46222L1089": "IONQ"}),
            repository,
        )

        dto = use_case.handle(ImportTransactionsRequest("main", "csv"))

        persisted = repository.received[1]
        assert persisted[0].symbol == "IONQ"
        assert dto.broker == "degiro"
        assert dto.parsed == 1
        assert dto.inserted == 1
        assert dto.unresolved_symbols == ()

    def test_keeps_symbol_and_warns_when_unresolved(self):
        result = ImportResult(
            transactions=(_transaction("ES0105618005"),),
            instruments=(Instrument(symbol="ES0105618005", isin="ES0105618005"),),
        )
        repository = _RecordingRepository(inserted=1)
        use_case = _use_case(_StubImporter("degiro", result), _MapResolver({}), repository)

        dto = use_case.handle(ImportTransactionsRequest("main", "csv"))

        assert repository.received[1][0].symbol == "ES0105618005"
        assert dto.unresolved_symbols == ("ES0105618005",)
        assert any("ES0105618005" in warning for warning in dto.warnings)

    def test_reports_duplicates_via_inserted_count(self):
        result = ImportResult(transactions=(_transaction("A"), _transaction("A", raw_id="r2")))
        repository = _RecordingRepository(inserted=1)
        use_case = _use_case(_StubImporter("json", result), _MapResolver({"A": "A"}), repository)

        dto = use_case.handle(ImportTransactionsRequest("main", "csv"))

        assert dto.parsed == 2
        assert dto.inserted == 1
        assert dto.duplicates == 1

    def test_passes_importer_warnings_through(self):
        warning = ImportWarning("invalid_row", WarningLevel.WARNING, "bad row", (3,))
        result = ImportResult(transactions=(), warnings=(warning,))
        use_case = _use_case(
            _StubImporter("degiro", result), _MapResolver({}), _RecordingRepository()
        )

        dto = use_case.handle(ImportTransactionsRequest("main", "csv"))

        assert "bad row" in dto.warnings

    def test_derives_passthrough_instruments_when_none_emitted(self):
        result = ImportResult(transactions=(_transaction("AAPL"),))
        repository = _RecordingRepository(inserted=1)
        resolver = _MapResolver({"AAPL": "AAPL"})
        use_case = _use_case(_StubImporter("json", result), resolver, repository)

        dto = use_case.handle(ImportTransactionsRequest("main", "csv"))

        assert repository.received[1][0].symbol == "AAPL"
        assert dto.unresolved_symbols == ()

    def test_honors_explicit_broker_override(self):
        degiro = _StubImporter("degiro", ImportResult(transactions=()), parseable=False)
        registry = ImporterRegistry([degiro], _StubLoggerFactory())
        use_case = ImportTransactions(registry, _MapResolver({}), _RecordingRepository())

        dto = use_case.handle(ImportTransactionsRequest("main", "csv", broker="degiro"))

        assert dto.broker == "degiro"

    def test_raises_when_no_importer_matches(self):
        importer = _StubImporter("degiro", ImportResult(transactions=()), parseable=False)
        use_case = _use_case(importer, _MapResolver({}), _RecordingRepository())

        with pytest.raises(UnrecognizedImportFormat):
            use_case.handle(ImportTransactionsRequest("main", "csv"))
