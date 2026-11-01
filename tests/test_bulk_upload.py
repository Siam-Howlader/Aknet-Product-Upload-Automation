import asyncio
import csv
import io
import json
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.ai.models import ProductContent
from app.database.db import Base
from app.routes import automation as automation_routes
from app.services.job_service import ProductJobService
from app.services.bulk_upload import (
    CSV_COLUMNS,
    BulkCsvError,
    BulkCsvQueue,
    BulkXlsxQueue,
    _clean_product_tags,
    parse_bulk_file,
    process_bulk_queue,
)
from app.services.schemas import UploadProductRequest


def test_bulk_upload_tags_are_plain_comma_separated_values() -> None:
    assert _clean_product_tags("Tags: Mouse, Wireless; Product Tags: USB") == (
        "Mouse, Wireless, USB"
    )


def _csv_bytes(rows: list[dict[str, str]], *, bom: bool = False) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=CSV_COLUMNS)
    writer.writeheader()
    writer.writerows(rows)
    data = output.getvalue().encode("utf-8")
    return (b"\xef\xbb\xbf" + data) if bom else data


def _csv_bytes_with_headers(
    headers: list[str], rows: list[dict[str, str]],
) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=headers)
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def _xlsx_bytes(rows: list[dict[str, str]], extra_columns: tuple[str, ...] = ()) -> bytes:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Product Queue"
    headers = [*CSV_COLUMNS, *extra_columns]
    worksheet.append(headers)
    for row in rows:
        worksheet.append([row.get(column, f"preserve-{column}") for column in headers])
    notes = workbook.create_sheet("Notes")
    notes["A1"] = "Keep this worksheet"
    workbook.active = workbook.sheetnames.index("Notes")

    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def _row(serial: str, status: str, name: str) -> dict[str, str]:
    return {
        "Serial Number": serial,
        "Upload Status": status,
        "Product Name": name,
        "SEO URL": f"product-{serial}",
        "Model": f"Model-{serial}",
        "Price": "12.50",
        "Quantity": "7",
        "Manufacturer": "Example Manufacturer",
        "Categories": "Hardware, Accessories",
        "Filters": "Wireless, Compact",
        "product tags": f"{name}, Example product",
        "product description": (
            f"{name} provides dependable everyday performance "
            "with useful features for home and business customers."
        ),
        "meta tag description": (
            f"Buy {name} in Bangladesh for dependable everyday performance, "
            "useful features, and service from AKNET Innovations Ltd."
        ),
    }


def _generated_content(product_name: str) -> ProductContent:
    return ProductContent(
        product_name=product_name,
        description=(
            f"<p>{product_name} provides dependable everyday performance "
            "with useful features for home and business customers.</p>"
        ),
        meta_title=f"{product_name} Price in Bangladesh",
        meta_description=(
            f"Buy {product_name} in Bangladesh for dependable everyday "
            "performance, useful features, and service from AKNET Innovations Ltd."
        ),
        meta_keywords=f"{product_name}, product price in Bangladesh",
        product_tags=f"{product_name}, Example product",
    )


class FakeGenerator:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    def generate(self, request) -> ProductContent:
        self.calls.append(request.product_name)
        return _generated_content(request.product_name)


class FakeWorkflow:
    def __init__(
        self,
        calls: list[str],
        queue_path: Path,
        outcomes: dict[str, list[str]],
        payloads: list,
        expected_before: dict[str, tuple[int, str]],
    ) -> None:
        self.calls = calls
        self.queue_path = queue_path
        self.outcomes = outcomes
        self.payloads = payloads
        self.expected_before = expected_before

    async def run(self, payload) -> tuple[str, str]:
        self.calls.append(payload.product_name)
        self.payloads.append(payload)
        current_queue = parse_bulk_file(
            self.queue_path.read_bytes(), self.queue_path)
        expected = self.expected_before.get(payload.product_name)
        if expected:
            row_index, status = expected
            assert current_queue.status_at(row_index) == status

        outcomes = self.outcomes.get(payload.product_name, [])
        if outcomes and outcomes.pop(0) == "fail":
            raise RuntimeError(f"Failed {payload.product_name}")
        return "Product saved successfully.", "https://opencart.test/admin/"


def _session_factory(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'tests.db'}")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)


def _run_queue(
    queue: BulkCsvQueue,
    *,
    generator_calls,
    workflow_calls,
    payloads,
    outcomes,
    sessions,
    expected_before=None,
):
    async def collect():
        return [
            event async for event in process_bulk_queue(
                queue,
                uuid4(),
                generator_factory=lambda: FakeGenerator(generator_calls),
                workflow_factory=lambda: FakeWorkflow(
                    workflow_calls, queue.path, outcomes, payloads,
                    expected_before or {}),
                session_factory=sessions,
            )
        ]

    return asyncio.run(collect())


def test_csv_parser_accepts_expected_columns_and_preserves_other_fields(tmp_path: Path) -> None:
    path = tmp_path / "queue.csv"
    content = _csv_bytes([_row("1", "pending", "Product A")], bom=True)
    queue = BulkCsvQueue.from_bytes(content, path)
    path.write_bytes(content)

    queue.update_status(0, "succeed")

    with path.open(encoding="utf-8-sig", newline="") as source:
        saved = next(csv.DictReader(source))
    assert saved["Upload Status"] == "succeed"
    assert saved["Categories"] == "Hardware, Accessories"
    assert saved["Model"] == "Model-1"
    assert saved["Quantity"] == "7"
    assert path.read_bytes().startswith(b"\xef\xbb\xbf")


def test_csv_parser_handles_escaped_quotes_in_fields(tmp_path: Path) -> None:
    row = _row("1", "pending", "Product A")
    row["product description"] = 'Cooler with a 2.4" display, dual-mode ARGB lighting.'
    content = _csv_bytes([row])

    queue = BulkCsvQueue.from_bytes(content, tmp_path / "quoted.csv")

    assert queue.rows[0][queue.headers.index("product description")] == (
        row["product description"]
    )


def test_csv_parser_skips_blank_rows_and_preserves_source_row_numbers(
    tmp_path: Path,
) -> None:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=CSV_COLUMNS)
    writer.writeheader()
    writer.writerow(_row("1", "pending", "Product A"))
    writer.writerow({})
    writer.writerow(_row("2", "pending", "Product B"))

    queue = BulkCsvQueue.from_bytes(
        output.getvalue().encode("utf-8"),
        tmp_path / "blank-row.csv",
    )

    assert [row["product_name"] for row in queue.display_rows()] == [
        "Product A",
        "Product B",
    ]
    assert [row["row_number"] for row in queue.display_rows()] == [2, 4]


def test_csv_parser_rejects_missing_columns_and_preserves_extra_columns(
    tmp_path: Path,
) -> None:
    rows = [_row("1", "pending", "Product A")]
    missing = dict(rows[0])
    del missing["Filters"]
    with pytest.raises(BulkCsvError, match="missing columns"):
        missing_headers = [column for column in CSV_COLUMNS if column != "Filters"]
        missing_csv = _csv_bytes_with_headers(missing_headers, [missing])
        BulkCsvQueue.from_bytes(missing_csv, tmp_path / "missing.csv")

    extra = _csv_bytes_with_headers(
        [*CSV_COLUMNS, "Other"],
        [{**rows[0], "Other": "value"}],
    )
    extra_path = tmp_path / "extra.csv"
    extra_queue = BulkCsvQueue.from_bytes(extra, extra_path)
    extra_path.write_bytes(extra)
    extra_queue.update_status(0, "succeed")
    with extra_path.open(encoding="utf-8", newline="") as source:
        assert next(csv.DictReader(source))["Other"] == "value"


def test_xlsx_parser_updates_only_status_cell_and_preserves_workbook(
    tmp_path: Path,
) -> None:
    path = tmp_path / "queue.xlsx"
    source = _xlsx_bytes(
        [_row("1", "pending", "Product A")],
        extra_columns=("Supplier Note",),
    )
    path.write_bytes(source)

    queue = BulkXlsxQueue.from_bytes(source, path)
    queue.update_status(0, "succeed")
    saved = load_workbook(path)

    assert saved.sheetnames == ["Product Queue", "Notes"]
    assert saved.active.title == "Notes"
    worksheet = saved["Product Queue"]
    assert worksheet["A2"].value == "1"
    assert worksheet["C2"].value == "Product A"
    assert worksheet["N2"].value == "preserve-Supplier Note"
    assert worksheet["B2"].value == "succeed"
    assert worksheet["B2"].fill.fgColor.rgb == "FFC6EFCE"
    assert worksheet["B2"].font.color.rgb == "FF006100"
    assert saved["Notes"]["A1"].value == "Keep this worksheet"
    saved.close()

    reloaded = parse_bulk_file(path.read_bytes(), path)
    assert reloaded.status_at(0) == "succeed"
    reloaded.update_status(0, "pending")
    pending_book = load_workbook(path)
    assert pending_book["Product Queue"]["B2"].value == "pending"
    assert pending_book["Product Queue"]["B2"].fill.fgColor.rgb == "FFFFC7CE"
    assert pending_book["Product Queue"]["B2"].font.color.rgb == "FF9C0006"
    pending_book.close()


def test_xlsx_parser_rejects_missing_required_columns(tmp_path: Path) -> None:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.append([column for column in CSV_COLUMNS if column != "Filters"])
    output = io.BytesIO()
    workbook.save(output)
    with pytest.raises(BulkCsvError, match="missing columns"):
        BulkXlsxQueue.from_bytes(output.getvalue(), tmp_path / "invalid.xlsx")


def test_xlsx_parser_finds_required_sheet_when_workbook_has_no_active_sheet(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _xlsx_bytes([_row("1", "pending", "Product A")])
    original_loader = load_workbook

    def load_without_active_sheet(*args, **kwargs):
        workbook = original_loader(*args, **kwargs)
        workbook._active = None
        return workbook

    monkeypatch.setattr(
        "app.services.bulk_upload.load_workbook",
        load_without_active_sheet,
    )

    queue = BulkXlsxQueue.from_bytes(source, tmp_path / "queue.xlsx")

    assert queue.worksheet.title == "Product Queue"
    assert queue.status_at(0) == "pending"


def test_only_pending_rows_upload_and_success_is_persisted_after_each_attempt(
    tmp_path: Path,
) -> None:
    path = tmp_path / "queue.csv"
    rows = [
        _row("1", "succeed", "Product A"),
        _row("2", "pending", "Product B"),
        _row("3", "pending", "Product C"),
    ]
    content = _csv_bytes(rows)
    path.write_bytes(content)
    queue = BulkCsvQueue.from_bytes(content, path)
    generator_calls: list[str] = []
    workflow_calls: list[str] = []
    payloads: list = []

    events = _run_queue(
        queue,
        generator_calls=generator_calls,
        workflow_calls=workflow_calls,
        payloads=payloads,
        outcomes={},
        sessions=_session_factory(tmp_path),
        expected_before={"Product C": (1, "succeed")},
    )

    assert generator_calls == ["Product B", "Product C"]
    assert workflow_calls == generator_calls
    assert [payload.model for payload in payloads] == ["Model-2", "Model-3"]
    assert [payload.seo_url for payload in payloads] == ["product-2", "product-3"]
    assert all(payload.product_tags == f"{payload.product_name}, Example product" for payload in payloads)
    assert all("dependable everyday performance" in payload.description for payload in payloads)
    assert all("Buy " in payload.meta_description for payload in payloads)
    assert all(payload.price == 12.5 and payload.quantity == 7 for payload in payloads)
    assert all(payload.manufacturer == "Example Manufacturer" for payload in payloads)
    assert all(payload.categories == "Hardware, Accessories" for payload in payloads)
    assert all(payload.filters == "Wireless, Compact" for payload in payloads)
    assert [queue.status_at(index) for index in range(3)] == [
        "succeed", "succeed", "succeed",
    ]
    assert [event["type"] for event in events].count("product_finished") == 2


def test_bulk_pending_row_uploads_without_duplicate_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "queue.csv"
    content = _csv_bytes([_row("1", "pending", "Previously Uploaded Product")])
    path.write_bytes(content)
    queue = BulkCsvQueue.from_bytes(content, path)
    workflow_calls: list[str] = []

    def reject_duplicate_check(*args, **kwargs):
        raise AssertionError("Bulk uploads must follow the CSV status only.")

    monkeypatch.setattr(
        ProductJobService,
        "ensure_not_duplicate_saved",
        reject_duplicate_check,
    )

    events = _run_queue(
        queue,
        generator_calls=[],
        workflow_calls=workflow_calls,
        payloads=[],
        outcomes={},
        sessions=_session_factory(tmp_path),
    )

    finished = [event for event in events if event["type"] == "product_finished"]
    assert workflow_calls == ["Previously Uploaded Product"]
    assert finished[0]["upload_status"] == "succeed"
    assert queue.status_at(0) == "succeed"


def test_single_product_upload_does_not_check_saved_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class JobService:
        def __init__(self, db) -> None:
            pass

        def mark_uploading(self, job_id: int) -> None:
            pass

        def mark_saved(self, job_id: int) -> None:
            pass

    class Workflow:
        async def run(self, payload):
            return "Product saved successfully.", "https://opencart.test/admin/"

    monkeypatch.setattr(
        automation_routes,
        "ProductJobService",
        JobService,
    )
    monkeypatch.setattr(
        automation_routes,
        "OpenCartAutomationWorkflow",
        Workflow,
    )
    payload = UploadProductRequest(
        product_name="Previously Saved Product",
        description="Verified product description long enough for validation.",
        meta_title="Previously Saved Product Price in Bangladesh",
        meta_description=(
            "View Previously Saved Product information and specifications "
            "at Aknet Innovations Ltd. in Bangladesh."
        ),
        meta_keywords="Previously Saved Product, Product BD",
        product_tags="Previously Saved Product",
        job_id=42,
    )

    response = asyncio.run(
        automation_routes.upload_product_to_opencart(payload, db=None))

    assert response.status == "SAVED"
    assert response.message == "Product saved successfully."


def test_blank_product_name_stays_pending_and_does_not_stop_later_rows(
    tmp_path: Path,
) -> None:
    path = tmp_path / "queue.csv"
    content = _csv_bytes([
        _row("1", "pending", ""),
        _row("2", "pending", "Product B"),
    ])
    path.write_bytes(content)
    queue = BulkCsvQueue.from_bytes(content, path)
    generator_calls: list[str] = []
    workflow_calls: list[str] = []

    events = _run_queue(
        queue,
        generator_calls=generator_calls,
        workflow_calls=workflow_calls,
        payloads=[],
        outcomes={},
        sessions=_session_factory(tmp_path),
    )

    finished = [event for event in events if event["type"] == "product_finished"]
    assert generator_calls == ["Product B"]
    assert workflow_calls == ["Product B"]
    assert finished[0]["upload_status"] == "pending"
    assert "Product Name is blank" in finished[0]["error"]
    assert finished[1]["upload_status"] == "succeed"
    assert [queue.status_at(index) for index in range(2)] == [
        "pending", "succeed",
    ]


def test_blank_price_uses_zero_default(tmp_path: Path) -> None:
    path = tmp_path / "queue.csv"
    row = _row("1", "pending", "Product A")
    row["Price"] = ""
    content = _csv_bytes([row])
    path.write_bytes(content)
    queue = BulkCsvQueue.from_bytes(content, path)
    payloads: list = []

    _run_queue(
        queue,
        generator_calls=[],
        workflow_calls=[],
        payloads=payloads,
        outcomes={},
        sessions=_session_factory(tmp_path),
    )

    assert payloads[0].price == 0


def test_failed_product_stays_pending_and_batch_continues(tmp_path: Path) -> None:
    path = tmp_path / "queue.csv"
    content = _csv_bytes([
        _row("1", "pending", "Product B"),
        _row("2", "pending", "Product C"),
    ])
    path.write_bytes(content)
    queue = BulkCsvQueue.from_bytes(content, path)
    generator_calls: list[str] = []
    workflow_calls: list[str] = []
    payloads: list = []

    events = _run_queue(
        queue,
        generator_calls=generator_calls,
        workflow_calls=workflow_calls,
        payloads=payloads,
        outcomes={"Product B": ["fail"]},
        sessions=_session_factory(tmp_path),
        expected_before={"Product C": (0, "pending")},
    )

    outcomes = [event for event in events if event["type"] == "product_finished"]
    assert workflow_calls == ["Product B", "Product C"]
    assert outcomes[0]["upload_status"] == "pending"
    assert "Failed Product B" in outcomes[0]["error"]
    assert outcomes[1]["upload_status"] == "succeed"
    assert [queue.status_at(index) for index in range(2)] == ["pending", "succeed"]


def test_saved_csv_queue_resumes_after_reloading_and_skips_succeeded_rows(
    tmp_path: Path,
) -> None:
    path = tmp_path / "queue.csv"
    content = _csv_bytes([
        _row("1", "succeed", "Product A"),
        _row("2", "pending", "Product B"),
    ])
    path.write_bytes(content)
    sessions = _session_factory(tmp_path)
    first_queue = BulkCsvQueue.from_bytes(content, path)
    first_generator_calls: list[str] = []
    first_workflow_calls: list[str] = []
    first_payloads: list = []

    _run_queue(
        first_queue,
        generator_calls=first_generator_calls,
        workflow_calls=first_workflow_calls,
        payloads=first_payloads,
        outcomes={"Product B": ["fail"]},
        sessions=sessions,
    )
    assert BulkCsvQueue.from_bytes(path.read_bytes(), path).status_at(1) == "pending"

    restarted_queue = BulkCsvQueue.from_bytes(path.read_bytes(), path)
    resumed_generator_calls: list[str] = []
    resumed_workflow_calls: list[str] = []
    resumed_payloads: list = []
    _run_queue(
        restarted_queue,
        generator_calls=resumed_generator_calls,
        workflow_calls=resumed_workflow_calls,
        payloads=resumed_payloads,
        outcomes={},
        sessions=sessions,
    )

    assert first_workflow_calls == ["Product B"]
    assert resumed_generator_calls == ["Product B"]
    assert resumed_workflow_calls == ["Product B"]
    assert [restarted_queue.status_at(index) for index in range(2)] == [
        "succeed", "succeed",
    ]


def test_xlsx_queue_skips_succeeded_rows_and_resumes_pending_rows(
    tmp_path: Path,
) -> None:
    path = tmp_path / "queue.xlsx"
    original = _xlsx_bytes([
        _row("1", "succeed", "Product A"),
        _row("2", "pending", "Product B"),
    ])
    path.write_bytes(original)
    sessions = _session_factory(tmp_path)
    queue = BulkXlsxQueue.from_bytes(original, path)
    first_generator_calls: list[str] = []
    first_workflow_calls: list[str] = []
    first_payloads: list = []

    _run_queue(
        queue,
        generator_calls=first_generator_calls,
        workflow_calls=first_workflow_calls,
        payloads=first_payloads,
        outcomes={"Product B": ["fail"]},
        sessions=sessions,
    )
    saved_after_failure = BulkXlsxQueue.from_bytes(path.read_bytes(), path)
    assert saved_after_failure.status_at(0) == "succeed"
    assert saved_after_failure.status_at(1) == "pending"
    assert first_workflow_calls == ["Product B"]

    resumed = BulkXlsxQueue.from_bytes(path.read_bytes(), path)
    resumed_generator_calls: list[str] = []
    resumed_workflow_calls: list[str] = []
    _run_queue(
        resumed,
        generator_calls=resumed_generator_calls,
        workflow_calls=resumed_workflow_calls,
        payloads=[],
        outcomes={},
        sessions=sessions,
    )
    assert resumed_generator_calls == ["Product B"]
    assert resumed_workflow_calls == ["Product B"]
    assert [resumed.status_at(index) for index in range(2)] == [
        "succeed", "succeed",
    ]


def test_reuploading_original_csv_starts_a_fresh_saved_queue(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = _csv_bytes([_row("1", "pending", "Product A")])
    previous_batch_id = automation_routes._bulk_batch_id(original)
    previous_path = tmp_path / f"{previous_batch_id}.csv"
    previous_path.write_bytes(
        _csv_bytes([_row("1", "succeed", "Product A")]))
    monkeypatch.setattr(
        automation_routes,
        "_bulk_file_path",
        lambda batch_id, extension: tmp_path / f"{batch_id}{extension}",
    )

    async def fake_process(queue, batch_id):
        successful, pending = queue.counts()
        yield {
            "type": "started",
            "batch_id": str(batch_id),
            "file_extension": queue.path.suffix,
            "rows": queue.display_rows(),
            "total": pending,
            "completed": 0,
            "successful": successful,
            "pending": pending,
        }

    monkeypatch.setattr(automation_routes, "process_bulk_queue", fake_process)
    app = FastAPI()
    app.include_router(automation_routes.router, prefix="/api/automation")
    with TestClient(app) as client:
        response = client.post(
            "/api/automation/bulk-upload",
            files={"file": ("products.csv", original, "text/csv")},
        )

    assert response.status_code == 200
    started = json.loads(response.text.split("data: ", 1)[1].splitlines()[0])
    fresh_batch_id = started["batch_id"]
    fresh_path = tmp_path / f"{fresh_batch_id}.csv"
    assert fresh_batch_id != str(previous_batch_id)
    assert started["pending"] == 1
    assert BulkCsvQueue.from_bytes(fresh_path.read_bytes(), fresh_path).status_at(0) == "pending"
    assert BulkCsvQueue.from_bytes(previous_path.read_bytes(), previous_path).status_at(0) == "succeed"


def test_xlsx_upload_download_keeps_workbook_format(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = _xlsx_bytes([_row("1", "succeed", "Product A")])
    saved_path = tmp_path / "fresh-batch.xlsx"
    monkeypatch.setattr(
        automation_routes,
        "_bulk_file_path",
        lambda _batch_id, _extension: saved_path,
    )
    monkeypatch.setattr(
        automation_routes,
        "_bulk_existing_path",
        lambda _batch_id: saved_path,
    )
    app = FastAPI()
    app.include_router(automation_routes.router, prefix="/api/automation")

    with TestClient(app) as client:
        response = client.post(
            "/api/automation/bulk-upload",
            files={"file": ("products.xlsx", content, "application/octet-stream")},
        )
        started = json.loads(response.text.split("data: ", 1)[1].splitlines()[0])
        batch_id = started["batch_id"]
        download = client.get(f"/api/automation/bulk-upload/{batch_id}/file")

    assert response.status_code == 200
    assert download.status_code == 200
    assert download.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    assert load_workbook(io.BytesIO(download.content)).sheetnames == [
        "Product Queue", "Notes",
    ]
