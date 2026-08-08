from datetime import date
from decimal import Decimal

import pytest

from pryces.application.exceptions import (
    PortfolioBrokerMismatch,
    UnrecognizedImportFormat,
)
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


class _FailingParseImporter:
    """Matches on can_parse but rejects the body — a header the importer claims
    but rows it cannot read. `detail` mimics an importer that knows exactly why."""

    def __init__(self, broker_id, detail=None):
        self._broker_id = broker_id
        self._detail = detail

    @property
    def broker_id(self):
        return self._broker_id

    def can_parse(self, content):
        return True

    def parse(self, content):
        raise UnrecognizedImportFormat(self._broker_id, self._detail)


class _MapResolver:
    def __init__(self, mapping):
        self._mapping = mapping

    def resolve(self, instrument):
        return self._mapping.get(instrument.symbol)


class _RecordingRepository:
    def __init__(self, inserted=0, existing=None):
        self.inserted = inserted
        self.existing = existing or []
        self.received = None

    def get_transactions(self, portfolio_name, user_id=1):
        return self.existing

    def add_transactions(self, portfolio_name, transactions, user_id=1):
        self.received = (portfolio_name, transactions, user_id)
        return self.inserted


def _transaction(symbol, raw_id="r1", broker="DEGIRO"):
    return Transaction(
        date=date(2024, 1, 10),
        type=TransactionType.BUY,
        symbol=symbol,
        currency=Currency.USD,
        quantity=Decimal("5"),
        price=Decimal("100"),
        broker=broker,
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

        dto = use_case.handle(ImportTransactionsRequest("main", b"csv"))

        persisted = repository.received[1]
        assert persisted[0].symbol == "IONQ"
        assert dto.broker == "degiro"
        assert dto.parsed == 1
        assert dto.inserted == 1
        assert dto.unresolved_symbols == ()

    def test_skips_rows_whose_instrument_did_not_resolve(self):
        # Stored under its raw product name a row cannot be priced, so it is
        # excluded from positions and totals anyway — keeping it would only
        # hide broken data in the ledger.
        result = ImportResult(
            transactions=(_transaction("ES0105618005"),),
            instruments=(Instrument(symbol="ES0105618005", isin="ES0105618005"),),
        )
        repository = _RecordingRepository(inserted=0)
        use_case = _use_case(_StubImporter("degiro", result), _MapResolver({}), repository)

        dto = use_case.handle(ImportTransactionsRequest("main", b"csv"))

        assert repository.received[1] == []
        assert dto.parsed == 1
        assert dto.inserted == 0
        assert dto.skipped_unresolved == 1
        assert dto.unresolved_symbols == ("ES0105618005",)
        assert any("ES0105618005" in warning for warning in dto.warnings)

    def test_resolved_rows_still_import_alongside_skipped_ones(self):
        result = ImportResult(
            transactions=(_transaction("ES0105618005"), _transaction("US0378331005")),
            instruments=(
                Instrument(symbol="ES0105618005", isin="ES0105618005"),
                Instrument(symbol="US0378331005", isin="US0378331005"),
            ),
        )
        repository = _RecordingRepository(inserted=1)
        use_case = _use_case(
            _StubImporter("degiro", result), _MapResolver({"US0378331005": "AAPL"}), repository
        )

        dto = use_case.handle(ImportTransactionsRequest("main", b"csv"))

        assert [tx.symbol for tx in repository.received[1]] == ["AAPL"]
        assert dto.parsed == 2
        assert dto.inserted == 1
        assert dto.skipped_unresolved == 1

    def test_skipped_rows_are_not_counted_as_duplicates(self):
        # `duplicates` is derived; without subtracting the skipped rows it would
        # report them as "already imported", which is the opposite of the truth.
        result = ImportResult(
            transactions=(_transaction("ES0105618005"),),
            instruments=(Instrument(symbol="ES0105618005"),),
        )
        use_case = _use_case(
            _StubImporter("degiro", result), _MapResolver({}), _RecordingRepository(inserted=0)
        )

        dto = use_case.handle(ImportTransactionsRequest("main", b"csv"))

        assert dto.duplicates == 0

    def test_broker_rule_still_applies_when_every_row_is_skipped(self):
        # The mismatch check runs on everything parsed, so a file that resolves
        # to nothing cannot slip into a portfolio belonging to another broker.
        result = ImportResult(
            transactions=(_transaction("ES0105618005", broker="DEGIRO"),),
            instruments=(Instrument(symbol="ES0105618005"),),
        )
        repository = _RecordingRepository(inserted=0, existing=[_transaction("A", broker="Horos")])
        use_case = _use_case(_StubImporter("degiro", result), _MapResolver({}), repository)

        with pytest.raises(PortfolioBrokerMismatch):
            use_case.handle(ImportTransactionsRequest("main", b"csv"))

    def test_reports_duplicates_via_inserted_count(self):
        result = ImportResult(transactions=(_transaction("A"), _transaction("A", raw_id="r2")))
        repository = _RecordingRepository(inserted=1)
        use_case = _use_case(_StubImporter("json", result), _MapResolver({"A": "A"}), repository)

        dto = use_case.handle(ImportTransactionsRequest("main", b"csv"))

        assert dto.parsed == 2
        assert dto.inserted == 1
        assert dto.duplicates == 1

    def test_passes_importer_warnings_through(self):
        warning = ImportWarning("invalid_row", WarningLevel.WARNING, "bad row", (3,))
        result = ImportResult(transactions=(), warnings=(warning,))
        use_case = _use_case(
            _StubImporter("degiro", result), _MapResolver({}), _RecordingRepository()
        )

        dto = use_case.handle(ImportTransactionsRequest("main", b"csv"))

        assert "bad row" in dto.warnings

    def test_derives_passthrough_instruments_when_none_emitted(self):
        result = ImportResult(transactions=(_transaction("AAPL"),))
        repository = _RecordingRepository(inserted=1)
        resolver = _MapResolver({"AAPL": "AAPL"})
        use_case = _use_case(_StubImporter("json", result), resolver, repository)

        dto = use_case.handle(ImportTransactionsRequest("main", b"csv"))

        assert repository.received[1][0].symbol == "AAPL"
        assert dto.unresolved_symbols == ()

    def test_honors_explicit_broker_override(self):
        degiro = _StubImporter("degiro", ImportResult(transactions=()), parseable=False)
        registry = ImporterRegistry([degiro], _StubLoggerFactory())
        use_case = ImportTransactions(registry, _MapResolver({}), _RecordingRepository())

        dto = use_case.handle(ImportTransactionsRequest("main", b"csv", broker="degiro"))

        assert dto.broker == "degiro"

    def test_raises_when_no_importer_matches(self):
        importer = _StubImporter("degiro", ImportResult(transactions=()), parseable=False)
        use_case = _use_case(importer, _MapResolver({}), _RecordingRepository())

        with pytest.raises(UnrecognizedImportFormat):
            use_case.handle(ImportTransactionsRequest("main", b"csv"))

    def test_detection_failure_reports_what_was_tried_and_seen(self):
        # Without this the user only sees "not a valid auto import", which says
        # nothing about why a previously working export stopped importing.
        importer = _StubImporter("degiro", ImportResult(transactions=()), parseable=False)
        use_case = _use_case(importer, _MapResolver({}), _RecordingRepository())
        content = "Tipo de operación;Producto\r\n".encode("cp1252")

        with pytest.raises(UnrecognizedImportFormat) as raised:
            use_case.handle(ImportTransactionsRequest("main", content))

        message = str(raised.value)
        assert "Tried: degiro" in message
        assert "Tipo de operación;Producto" in message

    def test_parse_failure_after_detection_also_reports_the_content(self):
        # can_parse matched but parse choked — the header is still the fact
        # that explains it.
        importer = _FailingParseImporter("horos")
        use_case = _use_case(importer, _MapResolver({}), _RecordingRepository())

        with pytest.raises(UnrecognizedImportFormat) as raised:
            use_case.handle(ImportTransactionsRequest("main", b"Fecha;ISIN\r\n"))

        assert "Fecha;ISIN" in str(raised.value)

    def test_an_importer_that_explains_itself_keeps_its_own_message(self):
        # A header preview says nothing about "this backup holds 5 portfolios";
        # only the importer knows that, so its detail must survive.
        reason = "This backup holds 5 portfolios. Restore it from Import backup instead."
        use_case = _use_case(
            _FailingParseImporter("json", reason), _MapResolver({}), _RecordingRepository()
        )

        with pytest.raises(UnrecognizedImportFormat) as raised:
            use_case.handle(ImportTransactionsRequest("main", b'{"format": "pryces-export"}'))

        assert reason in str(raised.value)
        assert "first line" not in str(raised.value)

    def test_empty_portfolio_adopts_the_imported_broker(self):
        result = ImportResult(transactions=(_transaction("AAPL", broker="DEGIRO"),))
        repository = _RecordingRepository(inserted=1, existing=[])
        use_case = _use_case(
            _StubImporter("degiro", result), _MapResolver({"AAPL": "AAPL"}), repository
        )

        dto = use_case.handle(ImportTransactionsRequest("main", b"csv"))

        assert dto.inserted == 1

    def test_same_broker_reimport_is_allowed(self):
        result = ImportResult(transactions=(_transaction("AAPL", broker="DEGIRO"),))
        repository = _RecordingRepository(
            inserted=0, existing=[_transaction("MSFT", broker="DEGIRO")]
        )
        use_case = _use_case(
            _StubImporter("degiro", result), _MapResolver({"AAPL": "AAPL"}), repository
        )

        dto = use_case.handle(ImportTransactionsRequest("main", b"csv"))

        assert dto.broker == "degiro"

    def test_manual_only_portfolio_accepts_first_import(self):
        # Manual entries carry broker=None and never lock the portfolio.
        result = ImportResult(transactions=(_transaction("AAPL", broker="DEGIRO"),))
        repository = _RecordingRepository(
            inserted=1, existing=[_transaction("MSFT", broker=None, raw_id="manual-1")]
        )
        use_case = _use_case(
            _StubImporter("degiro", result), _MapResolver({"AAPL": "AAPL"}), repository
        )

        dto = use_case.handle(ImportTransactionsRequest("main", b"csv"))

        assert dto.inserted == 1

    def test_different_broker_raises_mismatch(self):
        result = ImportResult(transactions=(_transaction("AAPL", broker="IBKR"),))
        repository = _RecordingRepository(existing=[_transaction("MSFT", broker="DEGIRO")])
        use_case = _use_case(
            _StubImporter("ibkr", result), _MapResolver({"AAPL": "AAPL"}), repository
        )

        with pytest.raises(PortfolioBrokerMismatch):
            use_case.handle(ImportTransactionsRequest("main", b"csv"))
