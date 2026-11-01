from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urljoin, urlparse
from uuid import UUID, uuid4

from bs4 import BeautifulSoup

from app.ai.client import OllamaProvider
from app.config import settings
from app.services.catalog_index import normalize_catalog_url
from app.services.seo_urls import SEO_URLS_PATH, load_seo_urls

logger = logging.getLogger(__name__)
_jobs: dict[str, "CsvUpdateJob"] = {}
_jobs_lock = asyncio.Lock()

FIELD_ALIASES = {
    "product name": ("product name",),
    "model": ("model",),
    "price": ("price",),
    "seo url": ("seo url", "seo_url", "seo slug"),
    "upload status": ("upload status", "upload_status"),
    "product tags": ("product tags", "tags", "product tag"),
    "product description": ("product description", "description"),
    "images": ("images", "image", "image urls", "image_urls"),
    "meta tag description": (
        "meta tag description", "meta description", "meta_description",
    ),
    "manufacturer": ("manufacturer", "brand"),
}


@dataclass
class CsvUpdateJob:
    id: str
    filename: str
    output_path: Path | None = None
    status: str = "queued"
    total_rows: int = 0
    processed_rows: int = 0
    successful_rows: int = 0
    review_rows: int = 0
    failed_rows: int = 0
    current_product: str | None = None
    error: str | None = None
    report: list[dict[str, object]] = field(default_factory=list)


def _header_key(header: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", header.casefold()).strip()


def _column_map(headers: list[str]) -> dict[str, str]:
    normalized = {_header_key(header): header for header in headers}
    result: dict[str, str] = {}
    for field_name, aliases in FIELD_ALIASES.items():
        matches = [normalized[_header_key(alias)] for alias in aliases if _header_key(alias) in normalized]
        if len(set(matches)) > 1:
            raise ValueError(f"CSV has multiple columns that could represent '{field_name}'.")
        if matches:
            result[field_name] = matches[0]
    if "product name" not in result:
        raise ValueError("CSV must contain a Product Name column.")
    return result


def parse_upload(content: bytes) -> tuple[list[str], list[dict[str, str]]]:
    if not content:
        raise ValueError("The uploaded CSV is empty.")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("CSV must be UTF-8 or UTF-8 with BOM.") from exc
    try:
        reader = csv.DictReader(io.StringIO(text, newline=""))
        headers = [header.strip() for header in (reader.fieldnames or [])]
        if not headers or any(not header for header in headers):
            raise ValueError("CSV must contain a non-empty header row.")
        if len(headers) != len(set(headers)):
            raise ValueError("CSV contains duplicate column names.")
        rows = [dict(row) for row in reader]
    except csv.Error as exc:
        raise ValueError("CSV has invalid quoting or structure.") from exc
    _column_map(headers)
    if not rows:
        raise ValueError("CSV contains no product rows.")
    return headers, rows


def _load_index() -> list[dict[str, str]]:
    path = settings.catalog_json_file
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read the product URL JSON: {path}") from exc
    if not isinstance(value, list):
        raise ValueError("Product URL JSON must contain an array.")
    records: dict[str, dict[str, str]] = {}
    for item in value:
        if not isinstance(item, dict):
            continue
        name, url = item.get("product_name"), item.get("product_url")
        normalized_url = normalize_catalog_url(url) if isinstance(url, str) else None
        if isinstance(name, str) and name.strip() and normalized_url:
            records[normalized_url] = {
                "product_name": name.strip(), "product_url": normalized_url,
            }
    return list(records.values())


def _load_seo_urls() -> set[str]:
    return load_seo_urls(SEO_URLS_PATH)


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", value.casefold()))


def match_product(row: dict[str, str], records: list[dict[str, str]]) -> tuple[dict[str, str] | None, str]:
    name = next((value for key, value in row.items() if _header_key(key) == "product name"), "").strip()
    model = next((value for key, value in row.items() if _header_key(key) == "model"), "").strip()
    manufacturer = next((value for key, value in row.items() if _header_key(key) == "manufacturer"), "").strip()
    normalized_name = " ".join(sorted(_tokens(name)))
    exact = [
        item for item in records
        if " ".join(sorted(_tokens(item["product_name"]))) == normalized_name
    ]
    if len(exact) == 1:
        return exact[0], "exact normalized product-name match"
    if len(exact) > 1:
        narrowed = [item for item in exact if model and model.casefold() in item["product_name"].casefold()]
        if len(narrowed) == 1:
            return narrowed[0], "exact name and model match"
        return None, "ambiguous exact product-name match"

    candidates: list[tuple[float, dict[str, str]]] = []
    for item in records:
        score = SequenceMatcher(None, name.casefold(), item["product_name"].casefold()).ratio()
        if model and model.casefold() in item["product_name"].casefold():
            score += 0.12
        if manufacturer and manufacturer.casefold() in item["product_name"].casefold():
            score += 0.04
        candidates.append((min(score, 1.0), item))
    candidates.sort(key=lambda pair: pair[0], reverse=True)
    if not candidates or candidates[0][0] < 0.88:
        return None, "no confident product-name match"
    if len(candidates) > 1 and candidates[0][0] - candidates[1][0] < 0.08:
        return None, "ambiguous fuzzy product-name match"
    return candidates[0][1], "confident fuzzy product-name match"


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", BeautifulSoup(value or "", "html.parser").get_text(" ", strip=True)).strip()


def _clean_tags(value: str) -> str:
    value = _clean(value)
    value = re.sub(r"^\s*(?:product\s+)?tags?\s*:\s*", "", value, flags=re.IGNORECASE)
    parts = [re.sub(r"^\s*(?:product\s+)?tags?\s*:\s*", "", part, flags=re.IGNORECASE).strip()
             for part in re.split(r"[,;\n|]+", value)]
    seen: set[str] = set()
    return ", ".join(part for part in parts if part and not (part.casefold() in seen or seen.add(part.casefold())))


def _is_600x600_image(url: str) -> bool:
    path = urlparse(url).path.casefold()
    return bool(re.search(r"600x600(?=\.[a-z0-9]+$)", path))


def _image_candidates(node) -> list[str]:
    candidates: list[str] = []
    for attr, value in node.attrs.items():
        if not value:
            continue
        values = value if isinstance(value, list) else [value]
        for item in values:
            if not isinstance(item, str):
                continue
            if attr == "srcset":
                candidates.extend(
                    part.strip().split()[0]
                    for part in item.split(",")
                    if part.strip()
                )
            else:
                candidates.append(item.strip())
    return candidates


def _structured_image_candidates(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        candidates: list[str] = []
        for item in value:
            candidates.extend(_structured_image_candidates(item))
        return candidates
    if isinstance(value, dict):
        candidates: list[str] = []
        for key in ("url", "contentUrl", "image"):
            if key in value:
                candidates.extend(_structured_image_candidates(value[key]))
        return candidates
    return []


def _first_text(soup: BeautifulSoup, selectors: tuple[str, ...]) -> str:
    for selector in selectors:
        node = soup.select_one(selector)
        if node:
            value = node.get("content") or node.get_text(" ", strip=True)
            if value:
                return _clean(value)
    return ""


def _full_description(soup: BeautifulSoup, structured: dict) -> str:
    candidates: list[str] = []
    structured_description = structured.get("description")
    if isinstance(structured_description, str):
        candidates.append(_clean(structured_description))
    for selector in (
        "[itemprop='description']", ".product-description", ".description",
        "#description", ".tab-content .description", ".product-info-description",
    ):
        for node in soup.select(selector):
            text = _clean(node.get_text(" ", strip=True))
            if text:
                candidates.append(text)
    if not candidates:
        return ""
    return max(dict.fromkeys(candidates), key=len)


def extract_product_data(html: str, page_url: str) -> dict[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    data: dict[str, str] = {}
    structured: dict = {}
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            parsed = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        values = parsed if isinstance(parsed, list) else [parsed]
        structured = next((item for item in values if isinstance(item, dict) and (
            item.get("@type") == "Product" or "Product" in item.get("@type", [])
        )), structured)
    if structured.get("name"):
        data["product_name"] = _clean(str(structured["name"]))
    offers = structured.get("offers", {})
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    if isinstance(offers, dict) and offers.get("price") is not None:
        data["price"] = str(offers["price"]).strip()
    data["product_name"] = data.get("product_name") or _first_text(soup, ("h1", "meta[property='og:title']", "title"))
    model_heading = re.search(
        r"\bKey\s+Features\s+of\s+([^:]{1,100}?)\s*:",
        soup.get_text(" ", strip=True),
        flags=re.IGNORECASE,
    )
    if model_heading:
        data["model"] = _clean(model_heading.group(1))
    data["description"] = _full_description(soup, structured)
    canonical = soup.select_one("link[rel='canonical']")
    canonical_url = normalize_catalog_url(canonical.get("href"), page_url) if canonical else normalize_catalog_url(page_url)
    data["seo_url"] = urlparse(canonical_url or page_url).path.strip("/").split("/")[-1]
    meta = soup.select_one("meta[name='description']")
    data["meta_tag_description"] = _clean(meta.get("content", "")) if meta else ""
    tags = _first_text(soup, (".product-tags", "[itemprop='keywords']", ".tags"))
    data["product_tags"] = _clean_tags(tags)

    main_image_nodes = soup.select(
        ".product-main-image, .product-main-image img, .product-image-main, "
        ".product-image-main img, .main-image, .main-image img, "
        "[data-role='main-image'], [data-main-image]"
    )
    image_values: list[str] = []
    for node in main_image_nodes:
        image_values.extend(_image_candidates(node))
    for selector in ("meta[property='og:image']", "meta[name='twitter:image']"):
        image_values.extend(
            node.get("content", "")
            for node in soup.select(selector)
            if node.get("content")
        )
    image_values.extend(_structured_image_candidates(structured.get("image", [])))
    main_node_ids = {id(node) for node in main_image_nodes}
    for node in soup.find_all(["img", "a", "source"]):
        if id(node) not in main_node_ids:
            image_values.extend(_image_candidates(node))
    absolute_images: list[str] = []
    for image in image_values:
        absolute = urljoin(page_url, image)
        if (
            urlparse(absolute).hostname
            and _is_600x600_image(absolute)
            and absolute not in absolute_images
        ):
            absolute_images.append(absolute)
    data["images"] = ", ".join(absolute_images)
    if data.get("price") is None:
        price = _first_text(soup, (".price", "[itemprop='price']"))
        if price:
            data["price"] = re.sub(r"[^\d.,]", "", price)
    return data


def _rewrite_description(source: str, data: dict[str, str]) -> tuple[str, str | None]:
    if not source:
        return "", "product description not found"
    model = settings.ollama_model or settings.ai_model
    if not model:
        return source, "Ollama model is not configured; preserved full source description"
    prompt = (
        "Rewrite the complete verified product description for AKNET Innovations Ltd. "
        "Return only the rewritten description. Keep every supported feature, "
        "specification, model identifier, compatibility detail, and meaningful "
        "technical fact from the source. Remove duplicated content, navigation, "
        "promotional claims, and unsupported statements. Do not summarize away "
        "technical details or invent facts. Use clear paragraphs.\n\n"
        f"Product name: {data.get('product_name', '')}\n"
        f"Manufacturer: {data.get('manufacturer', '')}\n"
        f"Source description:\n{source}"
    )
    try:
        rewritten = OllamaProvider(
            settings.ollama_base_url,
            model,
            settings.ollama_timeout_seconds,
            settings.ai_temperature,
            settings.ollama_num_ctx,
            settings.ollama_num_predict,
        ).generate(
            system_prompt=(
                "You are a careful product-content editor for AKNET Innovations Ltd. "
                "Preserve all source facts and never fabricate product information."
            ),
            user_prompt=prompt,
        )
        cleaned = _clean(rewritten)
        if not cleaned:
            raise ValueError("Ollama returned an empty rewritten description")
        return cleaned, None
    except Exception as exc:
        logger.warning("Ollama description rewrite failed: %s", exc)
        return source, f"Ollama rewrite failed; preserved full source description: {exc}"


async def _crawl(crawler, url: str) -> str:
    last_error: Exception | None = None
    for attempt in range(settings.crawl_retries + 1):
        try:
            result = await asyncio.wait_for(crawler.arun(url=url), settings.crawl_timeout_seconds)
            html = getattr(result, "html", None) or getattr(result, "cleaned_html", None)
            if not html:
                raise RuntimeError("Crawl4AI returned no HTML.")
            return html
        except Exception as exc:
            last_error = exc
            if attempt < settings.crawl_retries:
                await asyncio.sleep(min(2 ** attempt, 8))
    raise RuntimeError("Crawl4AI could not retrieve the product page.") from last_error


def serialize_job(job: CsvUpdateJob) -> dict:
    return {
        "job_id": job.id, "filename": job.filename, "status": job.status,
        "total_rows": job.total_rows, "processed_rows": job.processed_rows,
        "successful_rows": job.successful_rows, "review_rows": job.review_rows,
        "failed_rows": job.failed_rows, "current_product": job.current_product,
        "error": job.error, "report": job.report,
        "download_ready": job.status == "completed" and job.output_path is not None,
    }


def get_job(job_id: UUID) -> CsvUpdateJob:
    job = _jobs.get(str(job_id))
    if job is None:
        raise KeyError("CSV update job was not found.")
    return job


async def create_job(content: bytes, filename: str) -> CsvUpdateJob:
    headers, rows = parse_upload(content)
    job = CsvUpdateJob(str(uuid4()), Path(filename).name, total_rows=len(rows))
    _jobs[job.id] = job
    return job


async def process_job(job: CsvUpdateJob, content: bytes) -> None:
    try:
        headers, rows = parse_upload(content)
        columns = _column_map(headers)
        records = _load_index()
        known_seo_urls = _load_seo_urls()
        job.status = "running"
        semaphore = asyncio.Semaphore(max(1, settings.globalbrand_max_concurrency))
        from crawl4ai import AsyncWebCrawler

        async with AsyncWebCrawler() as crawler:
            async def process_row(index: int, row: dict[str, str]) -> None:
                async with semaphore:
                    product_name = row.get(columns["product name"], "")
                    job.current_product = product_name
                    if "images" in columns:
                        row[columns["images"]] = ""
                    if "product description" in columns:
                        row[columns["product description"]] = ""
                    match, reason = match_product(row, records)
                    report: dict[str, object] = {
                        "row": index + 2, "product": product_name,
                        "url": match["product_url"] if match else None, "status": "review",
                        "reason": reason,
                    }
                    try:
                        if not match:
                            logger.warning(
                                "No matching 600x600 product image URL could be checked for %s: %s",
                                product_name,
                                reason,
                            )
                            job.review_rows += 1
                        else:
                            data = extract_product_data(await _crawl(crawler, match["product_url"]), match["product_url"])
                            if not data.get("description"):
                                product_label = data.get("product_name") or product_name
                                data["description"] = (
                                    f"Buy {product_label} from AKNET Innovations Ltd. "
                                    "in Bangladesh"
                                )
                                report["reason"] = (
                                    f"{reason}; product description not found; "
                                    "used AKNET fallback description"
                                )
                                job.review_rows += 1
                            else:
                                data["description"], rewrite_note = await asyncio.to_thread(
                                    _rewrite_description, data["description"], data
                                )
                                if rewrite_note:
                                    report["reason"] = f"{report['reason']}; {rewrite_note}"
                            if not data.get("product_tags") and data.get("product_name"):
                                tags = list(dict.fromkeys(_tokens(data["product_name"])))
                                data["product_tags"] = ", ".join(tags[:4])
                            else:
                                data["product_tags"] = _clean_tags(data.get("product_tags", ""))
                            if data.get("product_name"):
                                product_label = str(data["product_name"]).strip()
                                data["meta_tag_description"] = (
                                    f"Buy {product_label} from AKNET Innovations Ltd."
                                )[:120]
                            field_columns = {
                                "product_name": "product name",
                                "model": "model",
                                "price": "price",
                                "seo_url": "seo url",
                                "product_tags": "product tags",
                                "description": "product description",
                                "images": "images",
                                "meta_tag_description": "meta tag description",
                            }
                            for field_name, value in data.items():
                                column_key = field_columns.get(field_name)
                                if value and column_key in columns:
                                    row[columns[column_key]] = value
                            if not data.get("images") and not row.get(columns.get("images", ""), "").strip():
                                report["reason"] = f"{report['reason']}; verified images unavailable"
                                logger.warning(
                                    "No matching 600x600 product image URL found for %s (%s)",
                                    product_name,
                                    match["product_url"],
                                )
                                job.review_rows += 1
                            else:
                                job.successful_rows += 1
                                report["status"] = "updated"
                    except Exception as exc:
                        job.failed_rows += 1
                        report["status"] = "failed"
                        report["reason"] = str(exc)
                        logger.warning("CSV row %s failed: %s", index + 2, exc)
                    finally:
                        description_column = columns.get("product description")
                        if (
                            description_column
                            and not row.get(description_column, "").strip()
                        ):
                            row[description_column] = (
                                f"Buy {product_name.strip()} from AKNET Innovations Ltd. "
                                "in Bangladesh"
                            )
                        seo_url_column = columns.get("seo url")
                        upload_status_column = columns.get("upload status")
                        if (
                            seo_url_column
                            and upload_status_column
                            and row.get(seo_url_column, "").strip().casefold()
                            in known_seo_urls
                        ):
                            row[upload_status_column] = "succeed"
                        job.report.append(report)
                        job.processed_rows += 1
                        job.current_product = None

            await asyncio.gather(*(process_row(index, row) for index, row in enumerate(rows)))
        output_path = settings.sqlite_file.parent / "csv_updates" / (
            f"{Path(job.filename).stem}_updated{Path(job.filename).suffix}"
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = output_path.with_suffix(output_path.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=headers, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        # Reopen the output before publishing it.
        with temporary.open("r", encoding="utf-8-sig", newline="") as stream:
            validated = list(csv.DictReader(stream))
        if len(validated) != len(rows) or list(validated[0]) != headers:
            raise ValueError("Updated CSV validation failed.")
        temporary.replace(output_path)
        job.output_path, job.status = output_path, "completed"
    except Exception as exc:
        job.status, job.error = "failed", str(exc)
        logger.exception("CSV update job %s failed", job.id)


async def launch_job(job: CsvUpdateJob, content: bytes) -> None:
    await process_job(job, content)
