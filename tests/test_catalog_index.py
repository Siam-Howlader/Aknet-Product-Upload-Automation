import asyncio
import json
from urllib.parse import parse_qs, urlparse

from app.services.catalog_index import (
    _merge_json_index,
    extract_catalog_links,
    extract_catalog_records,
    normalize_catalog_url,
    normalize_text,
)


def test_catalog_links_extract_products_and_pagination() -> None:
    html = """
    <div class="product-thumb"><a class="product-img"
      href="/a4tech-pk-935hl-full-hd-webcam">Webcam</a></div>
    <div class="product-thumb"><a href="https://example.com/nope">Nope</a></div>
    <div class="pagination"><a href="/index.php?route=product/catalog&amp;page=2">2</a></div>
    """
    products, pages = extract_catalog_links(
        html, "https://www.globalbrand.com.bd/index.php?route=product/catalog")
    assert products == {"https://www.globalbrand.com.bd/a4tech-pk-935hl-full-hd-webcam"}
    assert pages == {"https://www.globalbrand.com.bd/index.php?route=product%2Fcatalog&page=2"}


def test_catalog_records_use_listing_name_and_only_url_fields() -> None:
    html = """
    <div class="product-thumb">
      <a class="product-img" href="/product-one"><img alt="ignored"></a>
      <div class="caption"><h4><a href="/product-one">Exact Product One</a></h4></div>
    </div>
    <div class="pagination"><a href="/index.php?route=product/catalog&amp;page=2">2</a></div>
    """
    records, _ = extract_catalog_records(
        html, "https://www.globalbrand.com.bd/index.php?route=product/catalog")
    assert records == [{
        "product_name": "Exact Product One",
        "product_url": "https://www.globalbrand.com.bd/product-one",
    }]
    assert set(records[0]) == {"product_name", "product_url"}


def test_json_refresh_merges_discovered_records_and_deduplicates(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.catalog_index.settings.catalog_json_path",
        tmp_path / "globalbrand_product_urls.json",
    )
    existing = [{
        "product_name": "Old Name",
        "product_url": "https://www.globalbrand.com.bd/product-one?utm_source=x",
    }]
    (tmp_path / "globalbrand_product_urls.json").write_text(
        json.dumps(existing), encoding="utf-8"
    )
    count = _merge_json_index([{
        "product_name": "Verified New Name",
        "product_url": "https://www.globalbrand.com.bd/product-one",
    }, {
        "product_name": "Product Two",
        "product_url": "https://www.globalbrand.com.bd/product-two",
    }])
    assert count == 2
    data = json.loads(
        (tmp_path / "globalbrand_product_urls.json").read_text(encoding="utf-8")
    )
    assert data == [
        {"product_name": "Product Two", "product_url": "https://www.globalbrand.com.bd/product-two"},
        {"product_name": "Verified New Name", "product_url": "https://www.globalbrand.com.bd/product-one"},
    ]


def test_json_refresh_preserves_previous_records_when_discovery_fails(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.catalog_index.settings.catalog_json_path",
        tmp_path / "globalbrand_product_urls.json",
    )
    previous = [{"product_name": "Known Product", "product_url": "https://www.globalbrand.com.bd/known"}]
    (tmp_path / "globalbrand_product_urls.json").write_text(
        json.dumps(previous), encoding="utf-8"
    )
    assert _merge_json_index([]) == 1
    assert json.loads(
        (tmp_path / "globalbrand_product_urls.json").read_text(encoding="utf-8")
    ) == previous


def test_catalog_url_normalization_rejects_external_and_non_product_paths() -> None:
    assert normalize_catalog_url("https://example.com/product") is None
    assert normalize_catalog_url("/category/networking") is None
    assert normalize_catalog_url(
        "https://www.globalbrand.com.bd/index.php?route=product/catalog&page=3"
    ) == "https://www.globalbrand.com.bd/index.php?route=product%2Fcatalog&page=3"


def test_normalized_values_are_stable_for_matching() -> None:
    assert normalize_text("A4Tech PK-935HL") == "a4tech pk 935hl"


def test_catalog_pages_are_crawled_concurrently_and_pagination_streams(
    monkeypatch,
) -> None:
    from app.services.catalog_index import _discover_catalog

    monkeypatch.setattr(
        "app.services.catalog_index.settings.globalbrand_max_concurrency", 2
    )
    monkeypatch.setattr(
        "app.services.catalog_index.settings.catalog_max_pages", 3
    )
    monkeypatch.setattr(
        "app.services.catalog_index.settings.catalog_request_delay", 0
    )
    monkeypatch.setattr(
        "app.services.catalog_index.settings.catalog_max_products", 10
    )
    monkeypatch.setattr(
        "app.services.catalog_index._write_progress_index", lambda records: None
    )

    active = 0
    peak = 0
    seen: list[str] = []

    class Result:
        def __init__(self, html: str):
            self.html = html

    class FakeCrawler:
        async def arun(self, url: str):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            seen.append(url)
            await asyncio.sleep(0.02)
            page = parse_qs(urlparse(url).query).get("page", ["1"])[0]
            next_page = int(page) + 1
            pagination = (
                f'<a href="/index.php?route=product/catalog&page=2">2</a>'
                f'<a href="/index.php?route=product/catalog&page=3">3</a>'
                if page == "1"
                else f'<a href="/index.php?route=product/catalog&page={next_page}">{next_page}</a>'
            )
            html = f"""
            <div class="product-thumb">
              <a class="product-img" href="/product-{page}">Product {page}</a>
            </div>
            <div class="pagination">
              {pagination}
            </div>
            """
            active -= 1
            return Result(html)

    progress: list[dict] = []

    async def on_progress(snapshot):
        progress.append(snapshot)

    records, pages, failed, cancelled = asyncio.run(
        _discover_catalog("test-run", FakeCrawler(), on_progress)
    )
    assert peak == 2
    assert len(seen) == 3
    assert len(records) == 3
    assert len(pages) == 3
    assert failed == 0
    assert not cancelled
    assert progress[-1]["pages_processed"] == 3
