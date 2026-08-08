from pryces.domain.portfolio.transactions import ImportResult
from pryces.application.importers import ImporterRegistry


class _StubLogger:
    def debug(self, message): ...

    def info(self, message): ...

    def warning(self, message): ...

    def error(self, message): ...


class _StubLoggerFactory:
    def get_logger(self, name):
        return _StubLogger()


class _StubImporter:
    def __init__(self, broker_id, parseable):
        self._broker_id = broker_id
        self._parseable = parseable

    @property
    def broker_id(self):
        return self._broker_id

    def can_parse(self, content):
        return self._parseable

    def parse(self, content):
        return ImportResult(transactions=())


class _RaisingImporter:
    def __init__(self, broker_id):
        self._broker_id = broker_id

    @property
    def broker_id(self):
        return self._broker_id

    def can_parse(self, content):
        raise ValueError("boom")

    def parse(self, content):
        return ImportResult(transactions=())


def _registry(importers):
    return ImporterRegistry(importers, _StubLoggerFactory())


class TestImporterRegistry:

    def test_auto_detect_returns_first_matching_importer(self):
        first = _StubImporter("degiro", parseable=True)
        second = _StubImporter("json", parseable=True)
        registry = _registry([first, second])

        assert registry.auto_detect(b"anything") is first

    def test_auto_detect_skips_non_matching_importers(self):
        degiro = _StubImporter("degiro", parseable=False)
        json_importer = _StubImporter("json", parseable=True)
        registry = _registry([degiro, json_importer])

        assert registry.auto_detect(b"anything") is json_importer

    def test_auto_detect_returns_none_when_nothing_matches(self):
        registry = _registry([_StubImporter("degiro", parseable=False)])

        assert registry.auto_detect(b"anything") is None

    def test_auto_detect_skips_importer_whose_can_parse_raises(self):
        # A bad upload must not 500 the import — a raising can_parse is treated
        # as "not this importer" and detection continues.
        boom = _RaisingImporter("ibkr")
        good = _StubImporter("renta4", parseable=True)
        registry = _registry([boom, good])

        assert registry.auto_detect(b"anything") is good

    def test_get_resolves_by_broker_id(self):
        json_importer = _StubImporter("json", parseable=False)
        registry = _registry([_StubImporter("degiro", parseable=False), json_importer])

        assert registry.get("json") is json_importer

    def test_get_returns_none_for_unknown_broker_id(self):
        registry = _registry([_StubImporter("json", parseable=True)])

        assert registry.get("degiro") is None

    def test_importers_property_returns_a_copy(self):
        registry = _registry([_StubImporter("json", parseable=True)])

        registry.importers.clear()

        assert len(registry.importers) == 1


class TestDiagnose:
    """A failed detection has to say what was tried and what the file looked
    like — brokers change their export format without notice."""

    def test_names_every_importer_that_was_tried(self):
        registry = _registry(
            [_StubImporter("horos", parseable=False), _StubImporter("renta4", parseable=False)]
        )

        assert "Tried: horos, renta4" in registry.diagnose(b"a;b\n")

    def test_reports_the_header_line_and_encoding(self):
        registry = _registry([_StubImporter("horos", parseable=False)])

        diagnosis = registry.diagnose("Tipo de operación;Producto\r\n".encode("cp1252"))

        assert "cp1252" in diagnosis
        assert "Tipo de operación;Producto" in diagnosis

    def test_handles_an_empty_registry(self):
        assert "Tried: none" in _registry([]).diagnose(b"a;b\n")
