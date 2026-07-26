import json
from unittest.mock import Mock

from pryces.application.dtos import ImportDataResultDTO
from pryces.application.exceptions import InvalidExportDocument
from pryces.application.use_cases.import_data import ImportData
from pryces.presentation.console.commands.import_data import ImportDataCommand

_RESULT = ImportDataResultDTO(
    portfolios_created=1,
    portfolios_merged=1,
    portfolios_skipped=0,
    transactions_added=5,
    transactions_skipped=2,
    manual_assets_replaced=1,
    warnings=("bad row",),
)


def _command(result=_RESULT):
    import_use_case = Mock(spec=ImportData)
    import_use_case.handle.return_value = result
    return ImportDataCommand(import_use_case), import_use_case


def _export_file(tmp_path, document=None):
    path = tmp_path / "backup.json"
    path.write_text(json.dumps(document if document is not None else {"format": "pryces-export"}))
    return path


class TestImportDataCommand:

    def test_metadata_id(self):
        command, _ = _command()
        assert command.get_metadata().id == "import_data"

    def test_prompts(self):
        command, _ = _command()
        assert [p.key for p in command.get_input_prompts()] == ["file_path", "confirm"]

    def test_cancel_when_not_confirmed(self, tmp_path):
        command, import_use_case = _command()

        result = command.execute(file_path=str(_export_file(tmp_path)), confirm="no")

        assert "cancel" in result.message.lower()
        import_use_case.handle.assert_not_called()

    def test_imports_and_summarizes(self, tmp_path):
        command, import_use_case = _command()
        document = {"format": "pryces-export", "version": 1, "portfolios": []}

        result = command.execute(file_path=str(_export_file(tmp_path, document)), confirm="yes")

        assert import_use_case.handle.call_args.args[0].document == document
        assert "portfolios created: 1" in result.message
        assert "transactions added: 5" in result.message
        assert "duplicates skipped: 2" in result.message
        assert "⚠ bad row" in result.message

    def test_reports_invalid_json(self, tmp_path):
        command, import_use_case = _command()
        path = tmp_path / "broken.json"
        path.write_text("{not json")

        result = command.execute(file_path=str(path), confirm="yes")

        assert result.success is False
        import_use_case.handle.assert_not_called()

    def test_reports_invalid_export_document(self, tmp_path):
        command, import_use_case = _command()
        import_use_case.handle.side_effect = InvalidExportDocument("unsupported version 99")

        result = command.execute(file_path=str(_export_file(tmp_path)), confirm="yes")

        assert result.success is False
        assert "unsupported version" in result.message
