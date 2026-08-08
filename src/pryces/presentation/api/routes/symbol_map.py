from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from ....application.exceptions import SymbolMappingNotFound
from ....application.use_cases.manage_symbol_map import (
    DeleteSymbolMapping,
    GetSymbolMap,
    SetSymbolMapping,
    SetSymbolMappingRequest,
)
from ..dependencies import get_delete_symbol_mapping, get_get_symbol_map, get_set_symbol_mapping
from ..schemas import SymbolMappingBody, SymbolMappingResponse

router = APIRouter(prefix="/symbol-map", tags=["symbol-map"])


@router.get("", response_model=list[SymbolMappingResponse])
def list_symbol_map(
    use_case: GetSymbolMap = Depends(get_get_symbol_map),
) -> list[SymbolMappingResponse]:
    return [SymbolMappingResponse.from_dto(entry) for entry in use_case.handle()]


@router.put("/{key:path}", response_model=SymbolMappingResponse)
def set_symbol_mapping(
    key: str,
    body: SymbolMappingBody,
    use_case: SetSymbolMapping = Depends(get_set_symbol_mapping),
) -> SymbolMappingResponse:
    # `key:path` because the key is a raw broker product name — "HOROS VALUE
    # INTERNACIONAL, FI" and friends contain characters a plain path segment
    # would reject.
    try:
        entry = use_case.handle(SetSymbolMappingRequest(key=key, ticker=body.ticker))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    return SymbolMappingResponse.from_dto(entry)


@router.delete("/{key:path}", status_code=status.HTTP_204_NO_CONTENT)
def delete_symbol_mapping(
    key: str,
    use_case: DeleteSymbolMapping = Depends(get_delete_symbol_mapping),
) -> None:
    try:
        use_case.handle(key)
    except SymbolMappingNotFound as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
