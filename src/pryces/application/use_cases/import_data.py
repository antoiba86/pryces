from __future__ import annotations

from dataclasses import dataclass

from ...domain.portfolio.transactions import (
    Transaction,
    TransactionValidationError,
    normalize_transactions,
)
from ...domain.stocks import Currency
from ..dtos import ImportDataResultDTO
from ..exceptions import InvalidExportDocument
from ..interfaces import PortfolioRepository
from ..serialization import (
    EXPORT_FORMAT,
    EXPORT_VERSION,
    manual_asset_from_dict,
    transaction_from_dict,
)


@dataclass(frozen=True)
class ImportDataRequest:
    document: dict
    user_id: int = 1


class ImportData:
    """Restores an export document by merging it into the stored data.

    Missing portfolios are created; existing ones are merged. The merge is
    idempotent: broker rows dedup via the repository's (broker, raw_id) key,
    and rows without a raw_id (manual entries) are pre-deduplicated here by
    content equality against the portfolio's existing transactions. Manual
    assets are replaced when the entry carries a `manual_assets` key.

    This deliberately bypasses `ImportTransactions`: a restored portfolio was
    already valid (single-broker, symbols resolved), so neither the broker
    rule nor symbol resolution applies. A bad envelope aborts everything;
    bad entries and bad rows are skipped with warnings so a partial import
    can be fixed and safely re-run.
    """

    def __init__(self, repository: PortfolioRepository) -> None:
        self._repository = repository

    def handle(self, request: ImportDataRequest) -> ImportDataResultDTO:
        entries = _validate_envelope(request.document)

        created = merged = skipped = 0
        transactions_added = transactions_skipped = manual_assets_replaced = 0
        warnings: list[str] = []
        seen_names: set[str] = set()

        for position, entry in enumerate(entries, start=1):
            parsed_entry = self._validate_entry(position, entry, seen_names, warnings)
            if parsed_entry is None:
                skipped += 1
                continue
            name, base_currency = parsed_entry
            seen_names.add(name)

            summary = self._repository.find_summary_by_name(name, request.user_id)
            if summary is None:
                self._repository.create(
                    base_currency=base_currency, name=name, user_id=request.user_id
                )
                existing: list[Transaction] = []
                created += 1
            else:
                if summary.base_currency != base_currency:
                    warnings.append(
                        f"Skipped portfolio {name!r}: base currency {base_currency} does not"
                        f" match the existing portfolio's {summary.base_currency}"
                    )
                    skipped += 1
                    continue
                existing = self._repository.get_transactions(name, request.user_id)
                merged += 1

            transactions = self._parse_transactions(name, entry, warnings)
            to_insert, pre_deduped = _dedup_rows_without_raw_id(transactions, existing)
            inserted = self._repository.add_transactions(name, to_insert, request.user_id)
            transactions_added += inserted
            transactions_skipped += pre_deduped + (len(to_insert) - inserted)

            if self._replace_manual_assets(name, entry, request.user_id, warnings):
                manual_assets_replaced += 1

        return ImportDataResultDTO(
            portfolios_created=created,
            portfolios_merged=merged,
            portfolios_skipped=skipped,
            transactions_added=transactions_added,
            transactions_skipped=transactions_skipped,
            manual_assets_replaced=manual_assets_replaced,
            warnings=tuple(warnings),
        )

    def _validate_entry(
        self,
        position: int,
        entry,
        seen_names: set[str],
        warnings: list[str],
    ) -> tuple[str, str] | None:
        if not isinstance(entry, dict):
            warnings.append(f"Skipped portfolio entry {position}: not an object")
            return None
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            warnings.append(f"Skipped portfolio entry {position}: missing name")
            return None
        if name in seen_names:
            warnings.append(f"Skipped duplicate portfolio entry {position} for {name!r}")
            return None
        base_currency = entry.get("base_currency")
        try:
            Currency(base_currency)
        except ValueError:
            warnings.append(f"Skipped portfolio {name!r}: invalid base currency {base_currency!r}")
            return None
        if not isinstance(entry.get("transactions", []), list):
            warnings.append(f"Skipped portfolio {name!r}: 'transactions' must be a list")
            return None
        return name, base_currency

    def _parse_transactions(self, name: str, entry: dict, warnings: list[str]) -> list[Transaction]:
        transactions: list[Transaction] = []
        for index, row in enumerate(entry.get("transactions", []), start=1):
            try:
                transaction = transaction_from_dict(row)
                normalize_transactions([transaction])
            except (ValueError, TransactionValidationError) as error:
                warnings.append(f"Portfolio {name!r}: skipped transaction {index}: {error}")
                continue
            transactions.append(transaction)
        return transactions

    def _replace_manual_assets(
        self,
        name: str,
        entry: dict,
        user_id: int,
        warnings: list[str],
    ) -> bool:
        if "manual_assets" not in entry:
            return False
        rows = entry["manual_assets"]
        if not isinstance(rows, list):
            warnings.append(f"Portfolio {name!r}: 'manual_assets' must be a list — kept existing")
            return False
        # Replacement is destructive, so it's all-or-nothing: one bad row keeps
        # the portfolio's existing assets untouched.
        try:
            assets = [manual_asset_from_dict(row) for row in rows]
        except ValueError as error:
            warnings.append(
                f"Portfolio {name!r}: invalid manual asset ({error}) — kept existing assets"
            )
            return False
        self._repository.set_manual_assets(name, assets, user_id)
        return True


def _validate_envelope(document) -> list:
    if not isinstance(document, dict):
        raise InvalidExportDocument("content is not a JSON object")
    if document.get("format") != EXPORT_FORMAT:
        raise InvalidExportDocument(f"not a {EXPORT_FORMAT} document")
    if document.get("version") != EXPORT_VERSION:
        raise InvalidExportDocument(f"unsupported version {document.get('version')!r}")
    portfolios = document.get("portfolios")
    if not isinstance(portfolios, list):
        raise InvalidExportDocument("'portfolios' must be a list")
    return portfolios


def _dedup_rows_without_raw_id(
    incoming: list[Transaction],
    existing: list[Transaction],
) -> tuple[list[Transaction], int]:
    """Drops raw_id-less rows that content-equal an existing or earlier row.

    The repository's (broker, raw_id) dedup can't see them, so without this a
    re-imported backup would duplicate every manual transaction.
    """
    existing_rows = set(existing)
    batch_rows: set[Transaction] = set()
    to_insert: list[Transaction] = []
    deduped = 0
    for transaction in incoming:
        if transaction.raw_id is None:
            if transaction in existing_rows or transaction in batch_rows:
                deduped += 1
                continue
            batch_rows.add(transaction)
        to_insert.append(transaction)
    return to_insert, deduped
