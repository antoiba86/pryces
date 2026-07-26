import json
from pathlib import Path

from ....application.dtos import ImportDataResultDTO
from ....application.exceptions import InvalidExportDocument
from ....application.use_cases.import_data import ImportData, ImportDataRequest
from ..utils import validate_file_path
from .base import Command, CommandMetadata, CommandResult, InputPrompt


def _validate_confirm(value: str) -> str | None:
    if value.strip().lower() in ("yes", "no"):
        return None
    return "Enter 'yes' to import or 'no' to cancel."


class ImportDataCommand(Command):
    def __init__(self, import_data: ImportData) -> None:
        self._import_data = import_data

    def get_metadata(self) -> CommandMetadata:
        return CommandMetadata(
            id="import_data",
            name="Import Data",
            description="Restore portfolio data from a JSON export file (merge with dedup)",
            show_progress=False,
        )

    def get_input_prompts(self) -> list[InputPrompt]:
        return [
            InputPrompt(
                key="file_path",
                prompt="Path to the export file: ",
                validator=validate_file_path,
            ),
            InputPrompt(
                key="confirm",
                prompt="Type 'yes' to import: ",
                validator=_validate_confirm,
            ),
        ]

    def execute(self, **kwargs) -> CommandResult:
        if kwargs.get("confirm", "").strip().lower() != "yes":
            return CommandResult("Import cancelled.")

        path = Path(kwargs.get("file_path").strip())
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            return CommandResult(f"Could not read {path}: {error}", success=False)

        try:
            result = self._import_data.handle(ImportDataRequest(document=document))
        except InvalidExportDocument as error:
            return CommandResult(str(error), success=False)

        return CommandResult(self._format_result(result))

    @staticmethod
    def _format_result(result: ImportDataResultDTO) -> str:
        lines = [
            "Import finished:",
            f"  portfolios created: {result.portfolios_created}",
            f"  portfolios merged: {result.portfolios_merged}",
            f"  portfolios skipped: {result.portfolios_skipped}",
            f"  transactions added: {result.transactions_added}",
            f"  duplicates skipped: {result.transactions_skipped}",
            f"  manual assets replaced: {result.manual_assets_replaced}",
        ]
        for warning in result.warnings:
            lines.append(f"  ⚠ {warning}")
        return "\n".join(lines)
