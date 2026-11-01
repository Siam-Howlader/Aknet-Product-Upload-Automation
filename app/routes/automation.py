import hashlib
import logging
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.automation.errors import AutomationError, LoginFailedError
from app.automation.workflow import OpenCartAutomationWorkflow
from app.config import settings
from app.dependencies import get_db
from app.services.job_service import ProductJobService
from app.services.bulk_upload import (
    BulkFileError,
    BulkProductQueue,
    encode_event,
    parse_bulk_file,
    process_bulk_queue,
)
from app.services.schemas import UploadProductRequest, UploadResponse
from app.services.catalog_index import (
    create_index_run, get_index_run, launch_index_run,
    serialize_index_run,
)
from app.services.csv_update import (
    create_job as create_csv_update_job,
    get_job as get_csv_update_job,
    launch_job as launch_csv_update_job,
    serialize_job as serialize_csv_update_job,
)

router = APIRouter()
logger = logging.getLogger(__name__)
active_bulk_batches: set[UUID] = set()


@router.post("/catalog-index/start")
async def start_catalog_index(background_tasks: BackgroundTasks) -> dict:
    run = create_index_run()
    if run["status"] == "queued":
        background_tasks.add_task(launch_index_run, UUID(run["run_id"]))
    return serialize_index_run(run)


@router.get("/catalog-index/status")
async def catalog_index_status() -> dict:
    return serialize_index_run(get_index_run())


@router.post("/csv-update/start")
async def start_csv_update(file: UploadFile, background_tasks: BackgroundTasks) -> dict:
    filename = Path(file.filename or "").name
    if Path(filename).suffix.casefold() != ".csv":
        raise HTTPException(status_code=400, detail="Only CSV files are supported.")
    content = await file.read()
    try:
        job = await create_csv_update_job(content, filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    background_tasks.add_task(launch_csv_update_job, job, content)
    return serialize_csv_update_job(job)


@router.get("/csv-update/{job_id}")
async def csv_update_status(job_id: UUID) -> dict:
    try:
        return serialize_csv_update_job(get_csv_update_job(job_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/csv-update/{job_id}/download")
async def download_csv_update(job_id: UUID) -> FileResponse:
    try:
        job = get_csv_update_job(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not job.output_path or job.status != "completed" or not job.output_path.is_file():
        raise HTTPException(status_code=409, detail="The updated CSV is not ready yet.")
    return FileResponse(
        job.output_path,
        media_type="text/csv",
        filename=job.output_path.name,
    )


def _bulk_csv_path(batch_id: UUID) -> Path:
    return settings.sqlite_file.parent / "bulk_uploads" / f"{batch_id}.csv"


def _bulk_file_path(batch_id: UUID, extension: str) -> Path:
    if extension == ".csv":
        return _bulk_csv_path(batch_id)
    return settings.sqlite_file.parent / "bulk_uploads" / f"{batch_id}{extension}"


def _bulk_existing_path(batch_id: UUID) -> Path | None:
    for extension in (".csv", ".xlsx"):
        path = _bulk_file_path(batch_id, extension)
        if path.is_file():
            return path
    return None


def _bulk_batch_id(content: bytes, extension: str = ".csv") -> UUID:
    digest = hashlib.sha256(extension.encode("ascii") + b"\0" + content).hexdigest()
    return uuid5(NAMESPACE_URL, digest)


def _bulk_response(
    queue: BulkProductQueue,
    batch_id: UUID,
    active_key: UUID | None = None,
) -> StreamingResponse:
    key = active_key or batch_id
    if key in active_bulk_batches:
        raise HTTPException(status_code=409, detail="This bulk upload is already running.")
    active_bulk_batches.add(key)

    async def events():
        try:
            async for event in process_bulk_queue(queue, batch_id):
                yield encode_event(event)
        except Exception as exc:
            logger.exception("Bulk queue %s could not be processed", batch_id)
            yield encode_event({
                "type": "batch_error",
                "batch_id": str(batch_id),
                "error": str(exc) or exc.__class__.__name__,
            })
        finally:
            active_bulk_batches.discard(key)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/upload", response_model=UploadResponse)
async def upload_product_to_opencart(payload: UploadProductRequest, db: Session = Depends(get_db)) -> UploadResponse:
    service = ProductJobService(db)

    job_id = payload.job_id
    if job_id:
        service.mark_uploading(job_id)

    workflow = OpenCartAutomationWorkflow()
    try:
        message, current_url = await workflow.run(payload)
    except LoginFailedError as exc:
        if job_id:
            service.mark_failed(job_id, str(exc))
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except AutomationError as exc:
        logger.warning("Automation validation failed: %s", str(exc))
        if job_id:
            service.mark_failed(job_id, str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        if job_id:
            service.mark_failed(job_id, "Unexpected automation error")
        logger.exception("Unexpected automation error")
        raise HTTPException(
            status_code=500,
            detail="Automation failed unexpectedly. Check server logs for details.",
        ) from exc

    if job_id:
        if "saved successfully" in message.lower():
            service.mark_saved(job_id)
            status = "SAVED"
        else:
            service.mark_filled(job_id)
            status = "FILLED"
    else:
        status = "FILLED"

    return UploadResponse(job_id=job_id or 0, status=status, message=message, current_url=current_url)


@router.post("/bulk-upload")
async def upload_csv_for_bulk_upload(file: UploadFile) -> StreamingResponse:
    content = await file.read()
    extension = Path(file.filename or "").suffix.casefold()
    if extension not in {".csv", ".xlsx"}:
        raise HTTPException(status_code=400, detail="Only .csv and .xlsx files are supported.")
    active_key = _bulk_batch_id(content, extension)
    if active_key in active_bulk_batches:
        raise HTTPException(status_code=409, detail="This bulk upload is already running.")

    batch_id = uuid4()
    path = _bulk_file_path(batch_id, extension)
    try:
        queue = parse_bulk_file(content, path)
    except BulkFileError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return _bulk_response(queue, batch_id, active_key=active_key)


@router.post("/bulk-upload/{batch_id}/resume")
async def resume_bulk_upload(batch_id: UUID) -> StreamingResponse:
    path = _bulk_existing_path(batch_id)
    if path is None:
        raise HTTPException(status_code=404, detail="Saved bulk CSV queue was not found.")
    try:
        queue = parse_bulk_file(path.read_bytes(), path)
    except BulkFileError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _bulk_response(queue, batch_id)


@router.get("/bulk-upload/{batch_id}/file")
@router.get("/bulk-upload/{batch_id}/csv")
async def download_bulk_upload_file(batch_id: UUID) -> FileResponse:
    path = _bulk_existing_path(batch_id)
    if path is None:
        raise HTTPException(status_code=404, detail="Saved bulk CSV queue was not found.")
    return FileResponse(
        path,
        media_type=(
            "text/csv" if path.suffix.casefold() == ".csv"
            else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        filename=f"bulk-upload-{batch_id}{path.suffix.casefold()}",
    )
