import asyncio
import csv
import io
import json
import logging
import os
import re
import tempfile
from collections.abc import AsyncIterator, Callable
from copy import copy
from pathlib import Path
from typing import Any
from uuid import UUID

from openpyxl import load_workbook
from openpyxl.styles import PatternFill

from app.ai.generator import AIContentGenerator
from app.ai.models import ProductContentRequest
from app.automation.workflow import OpenCartAutomationWorkflow
from app.config import settings
from app.database.db import SessionLocal
from app.services.job_service import ProductJobService
from app.services.schemas import UploadProductRequest

logger = logging.getLogger(__name__)

CSV_COLUMNS = (
    "Serial Number",
    "Upload Status",
    "Product Name",
    "SEO URL",
    "Model",
    "Price",
    "Quantity",
    "Manufacturer",
    "Categories",
    "Filters",
    "product tags",
    "product description",
    "meta tag description",
)


class BulkFileError(ValueError):
    pass


BulkCsvError = BulkFileError


class BulkProductQueue:
    def __init__(
        self,
        path: Path,
        headers: list[str],
        rows: list[list[str]],
        row_numbers: list[int],
    ) -> None:
        self.path = path
        self.headers = headers
        self.rows = rows
        self.row_numbers = row_numbers

    def _validate_rows(self) -> None:
        status_column = self.headers.index("Upload Status")
        for row_number, row in zip(self.row_numbers, self.rows):
            status = row[status_column].strip().casefold()
            if status not in {"pending", "succeed"}:
                raise BulkFileError(
                    f"Row {row_number} Upload Status must be 'pending' or 'succeed'."
                )

    def status_at(self, row_index: int) -> str:
        return self.rows[row_index][self.headers.index("Upload Status")].strip().casefold()

    def pending_indexes(self) -> list[int]:
        return [
            index for index in range(len(self.rows))
            if self.status_at(index) == "pending"
        ]

    def counts(self) -> tuple[int, int]:
        statuses = [self.status_at(index) for index in range(len(self.rows))]
        return statuses.count("succeed"), statuses.count("pending")

    def display_rows(self) -> list[dict[str, str | int]]:
        serial_column = self.headers.index("Serial Number")
        name_column = self.headers.index("Product Name")
        return [
            {
                "row_number": self.row_numbers[index],
                "serial_number": row[serial_column],
                "product_name": row[name_column],
                "upload_status": self.status_at(index),
            }
            for index, row in enumerate(self.rows)
        ]

    def update_status(self, row_index: int, status: str) -> None:
        raise NotImplementedError


class BulkCsvQueue(BulkProductQueue):
    def __init__(
        self,
        path: Path,
        headers: list[str],
        rows: list[list[str]],
        row_numbers: list[int],
        dialect: type[csv.Dialect],
        has_bom: bool,
    ) -> None:
        super().__init__(path, headers, rows, row_numbers)
        self.dialect = dialect
        self.has_bom = has_bom

    @classmethod
    def from_bytes(cls, content: bytes, path: Path) -> "BulkCsvQueue":
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise BulkCsvError("CSV file must use UTF-8 encoding.") from exc
        if not text.strip():
            raise BulkCsvError("CSV file is empty.")

        try:
            detected_dialect = csv.Sniffer().sniff(text[:4096])
            dialect = type(
                "DetectedCsvDialect",
                (detected_dialect,),
                {"doublequote": True},
            )
        except csv.Error:
            dialect = csv.excel

        try:
            reader = csv.reader(io.StringIO(text, newline=""), dialect)
            headers = next(reader)
            if len(headers) != len(set(headers)) or not set(CSV_COLUMNS).issubset(headers):
                missing = [column for column in CSV_COLUMNS if column not in headers]
                details = []
                if missing:
                    details.append(f"missing columns: {', '.join(missing)}")
                if not details:
                    details.append("column names must not be duplicated")
                raise BulkCsvError(f"Invalid CSV columns ({'; '.join(details)}).")

            rows: list[list[str]] = []
            row_numbers: list[int] = []
            for row_number, row in enumerate(reader, start=2):
                if not row or not any(value.strip() for value in row):
                    continue
                rows.append(row)
                row_numbers.append(row_number)
        except csv.Error as exc:
            raise BulkCsvError(f"Could not parse CSV: {exc}") from exc

        for row_number, row in zip(row_numbers, rows):
            if len(row) != len(headers):
                raise BulkCsvError(
                    f"CSV row {row_number} has {len(row)} fields; expected {len(headers)}."
                )

        queue = cls(
            path=path,
            headers=headers,
            rows=rows,
            row_numbers=row_numbers,
            dialect=dialect,
            has_bom=content.startswith(b"\xef\xbb\xbf"),
        )
        queue._validate_rows()
        return queue

    def update_status(self, row_index: int, status: str) -> None:
        if status not in {"pending", "succeed"}:
            raise ValueError(f"Unsupported upload status: {status}")
        self.rows[row_index][self.headers.index("Upload Status")] = status
        self._write_atomically()

    def _write_atomically(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8-sig" if self.has_bom else "utf-8",
                newline="",
                dir=self.path.parent,
                delete=False,
            ) as output:
                temporary_path = Path(output.name)
                writer = csv.writer(
                    output,
                    self.dialect,
                    escapechar=self.dialect.escapechar or "\\",
                )
                writer.writerow(self.headers)
                writer.writerows(self.rows)
            os.replace(temporary_path, self.path)
        finally:
            if temporary_path and temporary_path.exists():
                temporary_path.unlink()


class BulkXlsxQueue(BulkProductQueue):
    def __init__(
        self,
        path: Path,
        workbook: Any,
        worksheet: Any,
        headers: list[str],
        rows: list[list[str]],
        row_numbers: list[int],
    ) -> None:
        super().__init__(path, headers, rows, row_numbers)
        self.workbook = workbook
        self.worksheet = worksheet

    @classmethod
    def from_bytes(cls, content: bytes, path: Path) -> "BulkXlsxQueue":
        try:
            workbook = load_workbook(io.BytesIO(content))
        except Exception as exc:
            raise BulkFileError(f"Could not read XLSX workbook: {exc}") from exc

        worksheet = None
        headers: list[str] = []
        for candidate in workbook.worksheets:
            candidate_headers = [
                str(cell.value).strip() if cell.value is not None else ""
                for cell in candidate[1]
            ]
            if (
                len(candidate_headers) == len(set(candidate_headers))
                and set(CSV_COLUMNS).issubset(candidate_headers)
            ):
                worksheet = candidate
                headers = candidate_headers
                break
        if worksheet is None:
            first_sheet = workbook.worksheets[0] if workbook.worksheets else None
            active_headers = [
                str(cell.value).strip() if cell.value is not None else ""
                for cell in first_sheet[1]
            ] if first_sheet is not None else []
            missing = [column for column in CSV_COLUMNS if column not in active_headers]
            details = (
                f"missing columns: {', '.join(missing)}"
                if missing else "column names must not be duplicated"
            )
            raise BulkFileError(f"Invalid XLSX columns ({details}).")

        rows: list[list[str]] = []
        row_numbers: list[int] = []
        for row_number in range(2, worksheet.max_row + 1):
            values = [
                _cell_value(worksheet.cell(row_number, column).value)
                for column in range(1, len(headers) + 1)
            ]
            if not any(value.strip() for value in values):
                continue
            rows.append(values)
            row_numbers.append(row_number)

        queue = cls(path, workbook, worksheet, headers, rows, row_numbers)
        queue._validate_rows()
        return queue

    def update_status(self, row_index: int, status: str) -> None:
        if status not in {"pending", "succeed"}:
            raise ValueError(f"Unsupported upload status: {status}")
        self.rows[row_index][self.headers.index("Upload Status")] = status

        status_cell = self.worksheet.cell(
            self.row_numbers[row_index],
            self.headers.index("Upload Status") + 1,
        )
        status_cell.value = status
        font = copy(status_cell.font)
        if status == "succeed":
            status_cell.fill = PatternFill(
                fill_type="solid", fgColor="FFC6EFCE")
            font.color = "FF006100"
        else:
            status_cell.fill = PatternFill(
                fill_type="solid", fgColor="FFFFC7CE")
            font.color = "FF9C0006"
        status_cell.font = font
        self._write_atomically()

    def _write_atomically(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                suffix=self.path.suffix,
                dir=self.path.parent,
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
            self.workbook.save(temporary_path)
            os.replace(temporary_path, self.path)
        finally:
            if temporary_path and temporary_path.exists():
                temporary_path.unlink()


def _cell_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _clean_product_tags(value: str) -> str:
    parts = []
    seen: set[str] = set()
    for raw in re.split(r"[,;\n|]+", str(value or "")):
        tag = re.sub(r"^\s*(?:product\s+)?tags?\s*:\s*", "", raw.strip(), flags=re.IGNORECASE)
        if tag and tag.casefold() not in seen:
            seen.add(tag.casefold())
            parts.append(tag)
    return ", ".join(parts)


def parse_bulk_file(content: bytes, path: Path) -> BulkProductQueue:
    if path.suffix.casefold() == ".csv":
        return BulkCsvQueue.from_bytes(content, path)
    if path.suffix.casefold() == ".xlsx":
        return BulkXlsxQueue.from_bytes(content, path)
    raise BulkFileError("Only .csv and .xlsx files are supported.")


def _row_payload(row: list[str], headers: list[str], content: Any) -> UploadProductRequest:
    values = dict(zip(headers, row))
    return UploadProductRequest.model_validate({
        **content.model_dump(),
        "product_name": values["Product Name"].strip(),
        "seo_url": values["SEO URL"].strip(),
        "model": values["Model"].strip(),
        "price": values["Price"].strip() or "0",
        "quantity": values["Quantity"].strip() or str(settings.product_quantity),
        "manufacturer": values["Manufacturer"].strip(),
        "categories": values["Categories"].strip(),
        "filters": values["Filters"].strip(),
        "product_tags": _clean_product_tags(values["product tags"]),
        "description": values["product description"].strip(),
        "meta_description": values["meta tag description"].strip(),
        "images": values.get("images", "").strip(),
    })


async def process_bulk_queue(
    queue: BulkProductQueue,
    batch_id: UUID,
    generator_factory: Callable[[], Any] = AIContentGenerator,
    workflow_factory: Callable[[], Any] = OpenCartAutomationWorkflow,
    session_factory: Callable[[], Any] = SessionLocal,
) -> AsyncIterator[dict[str, Any]]:
    successful, pending = queue.counts()
    pending_indexes = queue.pending_indexes()
    yield {
        "type": "started",
        "batch_id": str(batch_id),
        "file_extension": queue.path.suffix.casefold(),
        "rows": queue.display_rows(),
        "total": len(pending_indexes),
        "completed": 0,
        "successful": successful,
        "pending": pending,
    }

    for completed, row_index in enumerate(pending_indexes, start=1):
        row = queue.rows[row_index]
        values = dict(zip(queue.headers, row))
        product_name = values["Product Name"].strip()
        yield {
            "type": "product_started",
            "row_number": queue.row_numbers[row_index],
            "serial_number": values["Serial Number"],
            "product_name": product_name,
            "completed": completed - 1,
            "total": len(pending_indexes),
        }

        succeeded = False
        error_message = ""
        try:
            if not product_name:
                raise ValueError(
                    "Product Name is blank; the row remains pending.")
            request = ProductContentRequest(
                product_name=product_name,
                price=values["Price"].strip() or "0",
            )
            generator = generator_factory()
            content = await asyncio.to_thread(generator.generate, request)
            payload = _row_payload(row, queue.headers, content)

            with session_factory() as db:
                service = ProductJobService(db)
                job = service.create_generated_job(payload)
                service.mark_uploading(job.id)
                payload.job_id = job.id
                try:
                    message, current_url = await workflow_factory().run(payload)
                except Exception as exc:
                    service.mark_failed(job.id, str(exc))
                    raise

                if "saved successfully" in message.casefold():
                    service.mark_saved(job.id)
                    succeeded = True
                else:
                    service.mark_filled(job.id)
                    error_message = (
                        "Product fields were filled, but the product was not saved. "
                        "Check DRY_RUN and AUTO_SAVE before marking it complete."
                    )
        except Exception as exc:
            error_message = str(exc) or exc.__class__.__name__
            logger.exception(
                "Bulk upload failed for row %s, product %r",
                queue.row_numbers[row_index],
                product_name,
            )

        queue.update_status(row_index, "succeed" if succeeded else "pending")
        successful, pending = queue.counts()
        yield {
            "type": "product_finished",
            "row_number": queue.row_numbers[row_index],
            "serial_number": values["Serial Number"],
            "product_name": product_name,
            "upload_status": "succeed" if succeeded else "pending",
            "successful": successful,
            "pending": pending,
            "completed": completed,
            "total": len(pending_indexes),
            "error": error_message,
            "message": message if succeeded else error_message,
            "current_url": current_url if succeeded else "",
        }

    successful, pending = queue.counts()
    yield {
        "type": "completed",
        "batch_id": str(batch_id),
        "successful": successful,
        "pending": pending,
        "completed": len(pending_indexes),
        "total": len(pending_indexes),
    }


def encode_event(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
