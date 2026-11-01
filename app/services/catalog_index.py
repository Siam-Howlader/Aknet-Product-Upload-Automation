from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse
from uuid import UUID, uuid4

from bs4 import BeautifulSoup

from app.config import settings

logger = logging.getLogger(__name__)
CATALOG_HOST = "globalbrand.com.bd"
EXCLUDED_PATH_PARTS = (
    "/category", "/search", "/account", "/checkout", "/cart", "/compare",
    "/wishlist", "/login", "/register", "/contact", "/products-hotline",
)
active_index_runs: set[UUID] = set()
cancelled_index_runs: set[UUID] = set()


@dataclass
class IndexStatus:
    run_id: str | None = None
    status: str = "idle"
    total_pages: int = 0
    pages_processed: int = 0
    products_discovered: int = 0
    failed_pages: int = 0
    current_page: str | None = None
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


_status = IndexStatus()
_status_lock = asyncio.Lock()


def normalize_catalog_url(url: str, base: str = settings.catalog_url) -> str | None:
    absolute = urljoin(base, url.strip())
    parsed = urlparse(absolute)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    host = parsed.hostname.casefold().rstrip(".")
    if host != CATALOG_HOST and not host.endswith("." + CATALOG_HOST):
        return None
    if parsed.username or parsed.password or parsed.port:
        return None
    query = parse_qs(parsed.query, keep_blank_values=False)
    if parsed.path.rstrip("/") in {"", "/"}:
        return None
    if parsed.path.rstrip("/") == "/products" or query.get("route") == ["product/catalog"]:
        page = query.get("page", ["1"])[0]
        if not page.isdigit() or int(page) < 1:
            return None
        query = {"route": ["product/catalog"], "page": [page]}
        return urlunparse((parsed.scheme, parsed.netloc.casefold(), "/index.php",
                           "", urlencode(query, doseq=True), ""))
    path = parsed.path.casefold()
    if any(part in path for part in EXCLUDED_PATH_PARTS):
        return None
    if path.endswith((".xml", ".json", ".png", ".jpg", ".jpeg", ".webp", ".css", ".js")):
        return None
    return urlunparse((parsed.scheme, parsed.netloc.casefold(), parsed.path.rstrip("/"), "", "", ""))


def is_catalog_page(url: str) -> bool:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    return (
        parsed.path.rstrip("/") == "/index.php"
        and query.get("route") == ["product/catalog"]
    ) or parsed.path.rstrip("/") == "/products"


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def extract_catalog_links(html: str, page_url: str) -> tuple[set[str], set[str]]:
    records, pages = extract_catalog_records(html, page_url)
    return {item["product_url"] for item in records}, pages


def extract_catalog_records(html: str, page_url: str) -> tuple[list[dict[str, str]], set[str]]:
    soup = BeautifulSoup(html, "html.parser")
    products: dict[str, str] = {}
    pages: set[str] = set()
    for anchor in soup.select(".product-thumb a.product-img, .product-thumb a[href]"):
        candidate = normalize_catalog_url(anchor.get("href", ""), page_url)
        if candidate and not is_catalog_page(candidate):
            card = anchor.find_parent(class_="product-thumb") or anchor.parent
            name_node = (
                card.select_one(".caption h4 a, .caption .name a, h4 a, .name a")
                if card else None
            )
            name_source = name_node or anchor
            name = clean_text(name_source.get("title") or name_source.get_text(" ", strip=True))
            if name:
                products[candidate] = name
    for anchor in soup.select(".pagination a[href], a[href]"):
        candidate = normalize_catalog_url(anchor.get("href", ""), page_url)
        if candidate and is_catalog_page(candidate):
            pages.add(candidate)
    return [
        {"product_name": name, "product_url": url}
        for url, name in products.items()
    ], pages


def normalize_text(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").casefold()).strip()


def _read_json_index() -> list[dict[str, str]]:
    path = settings.catalog_json_file
    if not path.is_file():
        return []
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Ignoring invalid catalog JSON index %s: %s", path, exc)
        return []
    if not isinstance(value, list):
        return []
    records: dict[str, dict[str, str]] = {}
    for item in value:
        if not isinstance(item, dict):
            continue
        name, url = item.get("product_name"), item.get("product_url")
        normalized = normalize_catalog_url(url) if isinstance(url, str) else None
        if isinstance(name, str) and name.strip() and normalized:
            records[normalized] = {"product_name": name.strip(), "product_url": normalized}
    return list(records.values())


def _write_json_file(path: Path, records: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _write_progress_index(records: list[dict[str, str]]) -> None:
    _write_json_file(settings.catalog_json_file.with_suffix(".json.progress"), records)


def _remove_progress_index() -> None:
    try:
        settings.catalog_json_file.with_suffix(".json.progress").unlink(missing_ok=True)
    except OSError:
        logger.warning("Could not remove catalog progress file")


def _merge_json_index(discovered: list[dict[str, str]]) -> int:
    existing = _read_json_index()
    merged = {item["product_url"]: item for item in existing}
    for item in discovered:
        url = normalize_catalog_url(item.get("product_url", ""))
        name = clean_text(item.get("product_name", ""))
        if url and name:
            merged[url] = {"product_name": name, "product_url": url}
    if not merged:
        return len(existing)
    records = sorted(merged.values(), key=lambda item: item["product_name"].casefold())
    _write_json_file(settings.catalog_json_file, records)
    return len(records)


async def _crawl_with_shared_crawler(crawler, url: str) -> str:
    last_error: Exception | None = None
    for attempt in range(settings.crawl_retries + 1):
        try:
            result = await asyncio.wait_for(
                crawler.arun(url=url), timeout=settings.crawl_timeout_seconds
            )
            html = getattr(result, "html", None) or getattr(result, "cleaned_html", None)
            if not html:
                raise RuntimeError("Crawl4AI returned no HTML.")
            return html
        except Exception as exc:
            last_error = exc
            if attempt < settings.crawl_retries:
                await asyncio.sleep(min(2 ** attempt, 8))
    raise RuntimeError("Crawl4AI could not retrieve the page.") from last_error


async def _discover_catalog(run_id: str | UUID, crawler, progress_callback=None):
    queue: asyncio.Queue[str] = asyncio.Queue()
    scheduled: set[str] = set()
    processed: set[str] = set()
    records: dict[str, str] = {}
    failed = 0
    state_lock = asyncio.Lock()
    run_uuid = run_id if isinstance(run_id, UUID) else None
    initial = normalize_catalog_url(settings.catalog_url)
    if not initial:
        raise RuntimeError("CATALOG_URL is not a valid Global Brand catalog URL.")
    scheduled.add(initial)
    await queue.put(initial)

    async def update_progress(current: str | None = None) -> None:
        snapshot = {
            "pages_discovered": len(scheduled), "pages_processed": len(processed),
            "products_discovered": len(records), "failed_pages": failed,
            "current_page": current,
        }
        if progress_callback:
            await progress_callback(snapshot)
        else:
            async with _status_lock:
                _status.total_pages = len(scheduled)
                _status.pages_processed = len(processed)
                _status.products_discovered = len(records)
                _status.failed_pages = failed
                _status.current_page = current

    async def worker() -> None:
        nonlocal failed
        while True:
            page = await queue.get()
            try:
                if run_uuid and run_uuid in cancelled_index_runs:
                    continue
                try:
                    html = await _crawl_with_shared_crawler(crawler, page)
                    discovered, pagination = extract_catalog_records(html, page)
                    async with state_lock:
                        for item in discovered:
                            records[item["product_url"]] = item["product_name"]
                        for next_page in pagination:
                            if len(scheduled) >= settings.catalog_max_pages or len(records) >= settings.catalog_max_products:
                                break
                            if next_page not in scheduled:
                                scheduled.add(next_page)
                                await queue.put(next_page)
                        processed.add(page)
                        await update_progress(page)
                        _write_progress_index([
                            {"product_name": name, "product_url": url}
                            for url, name in records.items()
                        ])
                except Exception as exc:
                    async with state_lock:
                        failed += 1
                        processed.add(page)
                        logger.warning("Catalog page failed %s: %s", page, exc)
                        await update_progress(page)
            finally:
                queue.task_done()

    workers = [
        asyncio.create_task(worker())
        for _ in range(settings.globalbrand_max_concurrency)
    ]
    await queue.join()
    for task in workers:
        task.cancel()
    await asyncio.gather(*workers, return_exceptions=True)
    return records, scheduled, failed, bool(run_uuid and run_uuid in cancelled_index_runs)


def _serialize_status() -> dict:
    return {
        "run_id": _status.run_id,
        "status": _status.status,
        "total_pages": _status.total_pages,
        "pages_processed": _status.pages_processed,
        "products_discovered": _status.products_discovered,
        "products_added": 0,
        "products_updated": 0,
        "failed_pages": _status.failed_pages,
        "current_page": _status.current_page,
        "error": _status.error,
        "started_at": _status.started_at.isoformat() if _status.started_at else None,
        "completed_at": _status.completed_at.isoformat() if _status.completed_at else None,
    }


def create_index_run() -> dict:
    global _status
    if _status.status in {"queued", "running"}:
        return _serialize_status()
    _status = IndexStatus(run_id=str(uuid4()), status="queued")
    return _serialize_status()


def get_index_run() -> dict:
    return _serialize_status()


def serialize_index_run(run: dict | None = None) -> dict:
    return run if run is not None else _serialize_status()


async def process_index_run(run_id: UUID) -> None:
    active_index_runs.add(run_id)
    try:
        global _status
        _status.status = "running"
        _status.started_at = datetime.now(UTC)
        try:
            from crawl4ai import AsyncWebCrawler
        except ImportError as exc:
            raise RuntimeError(
                "Crawl4AI is not installed in the Python environment running the app."
            ) from exc
        async with AsyncWebCrawler() as crawler:
            records, pages, failed, cancelled = await _discover_catalog(run_id, crawler)
        discovered = [
            {"product_name": name, "product_url": url}
            for url, name in list(records.items())[:settings.catalog_max_products]
        ]
        if not failed and not cancelled and discovered:
            saved = _merge_json_index(discovered)
            _remove_progress_index()
        else:
            saved = len(_read_json_index())
            logger.warning(
                "Preserving previous JSON after partial catalog run %s: pages=%d failed=%d cancelled=%s",
                run_id, len(pages), failed, cancelled,
            )
        _status.status = (
            "cancelled" if cancelled
            else ("partial" if failed or not discovered else "completed")
        )
        if not discovered and not _status.error:
            _status.error = "No product records were discovered."
        _status.completed_at = datetime.now(UTC)
        _status.current_page = None
        logger.info("Catalog JSON run %s saved %d records from %d discovered products",
                    run_id, saved, len(discovered))
    except Exception as exc:
        logger.exception("Catalog index run %s failed", run_id)
        _status.status, _status.error = "failed", str(exc)
        _status.completed_at = datetime.now(UTC)
    finally:
        active_index_runs.discard(run_id)
        cancelled_index_runs.discard(run_id)


async def launch_index_run(run_id: UUID) -> None:
    await process_index_run(run_id)


def cancel_index_run(run_id: UUID) -> None:
    cancelled_index_runs.add(run_id)
