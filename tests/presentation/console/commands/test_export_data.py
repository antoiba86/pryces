import json
from unittest.mock import Mock

from pryces.application.use_cases.export_data import ExportData
from pryces.application.use_cases.list_portfolios import ListPortfolios
from pryces.domain.portfolio.portfolio import PortfolioSummary
from pryces.presentation.console.commands.export_data import ExportDataCommand

_SUMMARIES = [
    PortfolioSummary(name="main", base_currency="EUR", transaction_count=1),
    PortfolioSummary(name="us", base_currency="USD", transaction_count=0),
]

_DOCUMENT = {
    "format": "pryces-export",
    "version": 1,
    "exported_at": "2026-07-12T10:00:00+00:00",
    "portfolios": [
        {
            "name": "main",
            "base_currency": "EUR",
            "transactions": [{"symbol": "AAPL"}],
            "manual_assets": [],
        },
    ],
}


def _command(summaries=_SUMMARIES, document=_DOCUMENT):
    list_use_case = Mock(spec=ListPortfolios)
    list_use_case.handle.return_value = summaries
    export_use_case = Mock(spec=ExportData)
    export_use_case.handle.return_value = document
    return ExportDataCommand(list_use_case, export_use_case), export_use_case


class TestExportDataCommand:

    def test_metadata_id(self):
        command, _ = _command()
        assert command.get_metadata().id == "export_data"

    def test_no_prompts_when_empty(self):
        command, _ = _command(summaries=[])
        assert command.get_input_prompts() == []

    def test_prompts_offer_all_portfolios_option_and_default_filename(self):
        command, _ = _command()

        prompts = command.get_input_prompts()

        assert [p.key for p in prompts] == ["scope_selection", "destination"]
        assert prompts[0].preamble.startswith("  0. All portfolios")
        assert prompts[1].default.startswith("pryces_export_")
        assert prompts[1].default.endswith(".json")

    def test_scope_validator_accepts_zero_through_count(self):
        command, _ = _command()
        validator = command.get_input_prompts()[0].validator

        assert validator("0") is None
        assert validator("2") is None
        assert validator("3") is not None
        assert validator("x") is not None

    def test_destination_validator_rejects_existing_file(self, tmp_path):
        command, _ = _command()
        existing = tmp_path / "backup.json"
        existing.write_text("{}")
        validator = command.get_input_prompts()[1].validator

        assert validator(str(existing)) is not None
        assert validator(str(tmp_path / "new.json")) is None
        assert validator(str(tmp_path / "missing-dir" / "new.json")) is not None

    def test_exports_all_portfolios_to_the_destination(self, tmp_path):
        command, export_use_case = _command()
        command.get_input_prompts()
        destination = tmp_path / "backup.json"

        result = command.execute(scope_selection="0", destination=str(destination))

        assert export_use_case.handle.call_args.args[0].portfolio_name is None
        assert json.loads(destination.read_text(encoding="utf-8")) == _DOCUMENT
        assert result.success is True
        assert "1 portfolio(s) with 1 transaction(s)" in result.message

    def test_exports_the_selected_portfolio(self, tmp_path):
        command, export_use_case = _command()
        command.get_input_prompts()

        command.execute(scope_selection="2", destination=str(tmp_path / "us.json"))

        assert export_use_case.handle.call_args.args[0].portfolio_name == "us"

    def test_reports_write_failure(self, tmp_path):
        command, _ = _command()
        command.get_input_prompts()

        result = command.execute(
            scope_selection="0", destination=str(tmp_path / "nope" / "backup.json")
        )

        assert result.success is False

    def test_no_portfolios_fails_gracefully(self):
        command, _ = _command(summaries=[])
        command.get_input_prompts()

        result = command.execute()

        assert result.success is False
