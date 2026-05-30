from unittest.mock import Mock

from pryces.application.dtos import ImportResultDTO
from pryces.application.exceptions import UnrecognizedImportFormat
from pryces.application.use_cases.import_transactions import ImportTransactions
from pryces.application.use_cases.list_portfolios import ListPortfolios
from pryces.domain.portfolio.portfolio import PortfolioSummary
from pryces.presentation.console.commands.import_transactions import ImportTransactionsCommand

_SUMMARIES = [PortfolioSummary(name="main", base_currency="EUR", transaction_count=0)]


def _command(summaries=_SUMMARIES, dto=None):
    list_use_case = Mock(spec=ListPortfolios)
    list_use_case.handle.return_value = summaries
    import_use_case = Mock(spec=ImportTransactions)
    import_use_case.handle.return_value = dto or ImportResultDTO(
        broker="degiro", parsed=5, inserted=5
    )
    command = ImportTransactionsCommand(list_use_case, import_use_case, ["degiro", "json", "ibkr"])
    return command, import_use_case


class TestImportTransactionsCommand:

    def test_metadata_id(self):
        command, _ = _command()
        assert command.get_metadata().id == "import_transactions"

    def test_no_prompts_when_empty(self):
        command, _ = _command(summaries=[])
        assert command.get_input_prompts() == []

    def test_four_prompts_when_portfolios_exist(self):
        command, _ = _command()

        prompts = command.get_input_prompts()

        assert [p.key for p in prompts] == [
            "portfolio_selection",
            "file_path",
            "broker",
            "confirm",
        ]

    def test_broker_validator_accepts_blank_and_known(self):
        command, _ = _command()
        command.get_input_prompts()
        validator = next(p.validator for p in command.get_input_prompts() if p.key == "broker")

        assert validator("") is None
        assert validator("degiro") is None
        assert validator("unknown") is not None

    def test_cancel_when_not_confirmed(self, tmp_path):
        path = tmp_path / "x.csv"
        path.write_text("data")
        command, import_use_case = _command()
        command.get_input_prompts()

        result = command.execute(
            portfolio_selection="1", file_path=str(path), broker="", confirm="no"
        )

        assert "cancel" in result.message.lower()
        import_use_case.handle.assert_not_called()

    def test_imports_and_summarizes(self, tmp_path):
        path = tmp_path / "x.csv"
        path.write_text("data")
        command, import_use_case = _command(
            dto=ImportResultDTO(
                broker="degiro",
                parsed=5,
                inserted=4,
                unresolved_symbols=("ES0105618005",),
                warnings=("bad row",),
            )
        )
        command.get_input_prompts()

        result = command.execute(
            portfolio_selection="1", file_path=str(path), broker="degiro", confirm="yes"
        )

        request = import_use_case.handle.call_args.args[0]
        assert request.portfolio_name == "main"
        assert request.broker == "degiro"
        assert request.content == "data"
        assert "inserted: 4" in result.message
        assert "duplicates skipped: 1" in result.message
        assert "ES0105618005" in result.message
        assert "bad row" in result.message

    def test_blank_broker_becomes_none(self, tmp_path):
        path = tmp_path / "x.csv"
        path.write_text("data")
        command, import_use_case = _command()
        command.get_input_prompts()

        command.execute(portfolio_selection="1", file_path=str(path), broker="", confirm="yes")

        assert import_use_case.handle.call_args.args[0].broker is None

    def test_reports_unrecognized_format(self, tmp_path):
        path = tmp_path / "x.csv"
        path.write_text("data")
        command, import_use_case = _command()
        import_use_case.handle.side_effect = UnrecognizedImportFormat("degiro")
        command.get_input_prompts()

        result = command.execute(
            portfolio_selection="1", file_path=str(path), broker="degiro", confirm="yes"
        )

        assert result.success is False
