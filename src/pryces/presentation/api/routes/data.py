from __future__ import annotations

import json
from datetime import date

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status

from ....application.exceptions import (
    InvalidExportDocument,
    PortfolioNotFound,
    SampleFormatUnavailable,
)
from ....application.use_cases.export_data import ExportData, ExportDataRequest
from ....application.use_cases.export_sample import ExportSample, ExportSampleRequest
from ....application.use_cases.import_data import ImportData, ImportDataRequest
from ..dependencies import (
    current_user_id,
    get_export_data,
    get_export_sample,
    get_import_data,
)
from ..schemas import ImportDataResultResponse

router = APIRouter(prefix="/data", tags=["data"])


@router.get("/export")
def export_data(
    portfolio: str | None = Query(default=None),
    export_use_case: ExportData = Depends(get_export_data),
    user_id: int = Depends(current_user_id),
) -> Response:
    try:
        document = export_use_case.handle(
            ExportDataRequest(portfolio_name=portfolio, user_id=user_id)
        )
    except PortfolioNotFound as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
    # Plain Response (not JSONResponse) so the body is the document exactly as
    # serialized here; every Decimal is already a string in the document.
    return Response(
        content=json.dumps(document, indent=2, ensure_ascii=False),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{_filename(portfolio)}"'},
    )


@router.get("/sample")
def export_sample(
    portfolio: str = Query(...),
    sample_use_case: ExportSample = Depends(get_export_sample),
    user_id: int = Depends(current_user_id),
) -> Response:
    """An anonymised, re-importable example file in the portfolio's broker format."""
    try:
        document = sample_use_case.handle(
            ExportSampleRequest(portfolio_name=portfolio, user_id=user_id)
        )
    except PortfolioNotFound as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
    except SampleFormatUnavailable as error:
        raise HTTPException(status_code=422, detail=str(error))
    return Response(
        content=document.content,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{document.filename}"'},
    )


@router.post("/import", response_model=ImportDataResultResponse)
async def import_data(
    file: UploadFile = File(...),
    import_use_case: ImportData = Depends(get_import_data),
    user_id: int = Depends(current_user_id),
) -> ImportDataResultResponse:
    content = await file.read()
    try:
        document = json.loads(content)
    except json.JSONDecodeError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"File is not valid JSON: {error}"
        )
    try:
        result = import_use_case.handle(ImportDataRequest(document=document, user_id=user_id))
    except InvalidExportDocument as error:
        raise HTTPException(status_code=422, detail=str(error))
    return ImportDataResultResponse.from_dto(result)


def _filename(portfolio: str | None) -> str:
    stamp = date.today().strftime("%Y%m%d")
    if portfolio is None:
        return f"pryces_export_{stamp}.json"
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in portfolio)
    return f"pryces_export_{safe}_{stamp}.json"
