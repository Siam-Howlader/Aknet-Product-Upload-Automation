import asyncio
import csv
import io
import json
import sys
from types import SimpleNamespace

from app.services.csv_update import (
    _column_map,
    _clean_tags,
    _rewrite_description,
    extract_product_data,
    match_product,
    parse_upload,
)
from app.services import csv_update


def test_parse_upload_supports_bom_and_preserves_columns() -> None:
    content = "\ufeffSerial Number,Product Name,Images,Upload Status\n1,Mouse,\"old.jpg\",pending\n".encode()
    headers, rows = parse_upload(content)
    assert headers == ["Serial Number", "Product Name", "Images", "Upload Status"]
    assert rows[0]["Product Name"] == "Mouse"
    assert _column_map(headers)["images"] == "Images"


def test_matching_prefers_exact_normalized_name_and_rejects_ambiguous_fuzzy() -> None:
    records = [
        {"product_name": "A4Tech OP-720", "product_url": "https://www.globalbrand.com.bd/op-720"},
        {"product_name": "A4Tech OP-720 Wireless", "product_url": "https://www.globalbrand.com.bd/op-720-wireless"},
    ]
    match, reason = match_product({"Product Name": "a4tech op 720"}, records)
    assert match and match["product_url"].endswith("/op-720")
    assert "exact" in reason
    no_match, reason = match_product({"Product Name": "Unrelated Product"}, records)
    assert no_match is None
    assert "confident" in reason or "ambiguous" in reason


def test_product_extraction_reads_model_from_key_features_heading() -> None:
    data = extract_product_data(
        "<h1>A4TECH 4200N Wireless Keyboard Mouse Combo</h1>"
        "<h2>Key Features of A4TECH 4200N :</h2>",
        "https://www.globalbrand.com.bd/a4tech-4200n",
    )
    assert data["model"] == "A4TECH 4200N"


def test_product_extraction_keeps_main_and_gallery_images_in_order() -> None:
    html = """
    <html><head>
      <link rel="canonical" href="/mouse">
      <meta name="description" content="A verified mouse">
    </head><body>
      <h2>Key Features of A4TECH 4200N :</h2>
      <div class="product-image"><img data-largeimage="/main-600x600.jpg"></div>
      <div class="thumbnail">
        <img src="/gallery-600x600.jpg" data-srcset="/gallery-2-600x600.jpg 1x, /gallery-3-300x300.jpg 2x">
        <a href="/gallery-4-600x600.jpg">gallery</a>
      </div>
      <script type="application/ld+json">
        {"@type":"Product","name":"A4Tech Mouse","offers":{"price":"1200"},
         "image":["/structured-main-600x600.jpg","/structured-2.jpg"]}
      </script>
    </body></html>
    """
    data = extract_product_data(html, "https://www.globalbrand.com.bd/mouse")
    assert data["product_name"] == "A4Tech Mouse"
    assert data["model"] == "A4TECH 4200N"
    assert data["price"] == "1200"
    assert data["seo_url"] == "mouse"
    assert data["images"].split(", ")[0].endswith("/structured-main-600x600.jpg")
    assert "/gallery-600x600.jpg" in data["images"]
    assert "/gallery-2-600x600.jpg" in data["images"]
    assert "/gallery-4-600x600.jpg" in data["images"]
    assert "/structured-2.jpg" not in data["images"]
    assert data["meta_tag_description"] == "A verified mouse"
    assert _clean_tags("Tags: Mouse, Wireless; Tags: USB") == "Mouse, Wireless, USB"


def test_product_extraction_collects_all_600x600_image_variants() -> None:
    html = """
    <html><body>
      <div class="custom-gallery">
        <img src="/first-600x600.jpg?size=large"
             srcset="/first-600x600.jpg 1x, /second_600x600.PNG 2x"
             data-original="/third-600x600.webp"
             lazy-src="/lazy-600x600.avif">
        <a href="/fourth-600x600.jpeg#gallery">image</a>
      </div>
      <script type="application/ld+json">
        {"@type":"Product","name":"Camera",
         "image":[{"url":"/fifth-600x600.jpg"},{"contentUrl":"/sixth-600x600.png"}]}
      </script>
    </body></html>
    """
    data = extract_product_data(html, "https://www.globalbrand.com.bd/camera")
    images = data["images"].split(", ")
    assert len(images) == 8
    assert all("600x600" in image.casefold() for image in images)
    assert any(image.endswith("/first-600x600.jpg?size=large") for image in images)
    assert any(image.endswith("/second_600x600.PNG") for image in images)
    assert any(image.endswith("/third-600x600.webp") for image in images)
    assert any(image.endswith("/lazy-600x600.avif") for image in images)
    assert any(image.endswith("/fourth-600x600.jpeg#gallery") for image in images)
    assert any(image.endswith("/fifth-600x600.jpg") for image in images)
    assert any(image.endswith("/sixth-600x600.png") for image in images)


def test_product_extraction_puts_explicit_main_image_before_gallery_images() -> None:
    html = """
    <html><body>
      <div class="thumbnail"><img src="/extra-600x600.jpg"></div>
      <div class="product-main-image"><img src="/main-600x600.jpg"></div>
    </body></html>
    """
    images = extract_product_data(
        html, "https://www.globalbrand.com.bd/camera"
    )["images"].split(", ")
    assert images[0].endswith("/main-600x600.jpg")
    assert images[1].endswith("/extra-600x600.jpg")


def test_full_description_is_rewritten_for_aknet(monkeypatch) -> None:
    html = """
    <div class="product-description">
      <p>Full description paragraph with the supported feature.</p>
      <ul><li>Technical specification and compatibility detail.</li></ul>
    </div>
    """
    data = extract_product_data(
        html, "https://www.globalbrand.com.bd/exact-mouse"
    )
    assert "Full description paragraph" in data["description"]
    assert "compatibility detail" in data["description"]

    class FakeOllama:
        def __init__(self, *args):
            pass

        def generate(self, *, system_prompt: str, user_prompt: str) -> str:
            assert "Full description paragraph" in user_prompt
            assert "compatibility detail" in user_prompt
            return "AKNET product description with the verified technical details."

    monkeypatch.setattr(csv_update, "OllamaProvider", FakeOllama)
    monkeypatch.setattr(csv_update.settings, "ollama_model", "test-model")
    rewritten, note = _rewrite_description(data["description"], data)
    assert rewritten.startswith("AKNET product description")
    assert note is None


def test_job_writes_validated_updated_csv_and_preserves_unrelated_values(tmp_path, monkeypatch) -> None:
    class Result:
        html = """
        <h1>Exact Mouse</h1>
        <h2>Key Features of A4TECH 4200N :</h2>
        <meta name="description" content="Verified mouse">
        <div class="price">1,200</div>
        <img data-largeimage="/main-600x600.jpg">
        <div class="thumbnail"><img src="/gallery-600x600.jpg"></div>
        """

    class FakeCrawler:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def arun(self, url):
            return Result()

    monkeypatch.setitem(sys.modules, "crawl4ai", SimpleNamespace(AsyncWebCrawler=FakeCrawler))
    monkeypatch.setattr(csv_update.settings, "catalog_json_path", tmp_path / "globalbrand_product_urls.json")
    monkeypatch.setattr(csv_update.settings, "sqlite_path", str(tmp_path / "app.db"))
    monkeypatch.setattr(csv_update.settings, "ollama_model", "")
    monkeypatch.setattr(csv_update.settings, "ai_model", "")
    monkeypatch.setattr(
        csv_update,
        "SEO_URLS_PATH",
        tmp_path / "all_seo_urls.json",
    )
    (tmp_path / "globalbrand_product_urls.json").write_text(json.dumps([{
        "product_name": "Exact Mouse",
        "product_url": "https://www.globalbrand.com.bd/exact-mouse",
    }]), encoding="utf-8")
    (tmp_path / "all_seo_urls.json").write_text(
        json.dumps([{"seo_url": "exact-mouse"}]),
        encoding="utf-8",
    )
    content = (
        "Serial Number,Product Name,Model,SEO URL,Product Description,Images,Upload Status\n"
        "7,Exact Mouse,,,old description,\"old.jpg\",pending\n"
    ).encode()
    job = asyncio.run(csv_update.create_job(content, "products.csv"))
    asyncio.run(csv_update.process_job(job, content))
    assert job.status == "completed"
    output = job.output_path.read_text(encoding="utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(output)))
    assert rows[0]["Serial Number"] == "7"
    assert rows[0]["Model"] == "A4TECH 4200N"
    assert rows[0]["SEO URL"] == "exact-mouse"
    assert rows[0]["Upload Status"] == "succeed"
    assert rows[0]["Product Description"] == (
        "Buy Exact Mouse from AKNET Innovations Ltd. in Bangladesh"
    )
    assert rows[0]["Images"] == (
        "https://www.globalbrand.com.bd/main-600x600.jpg, https://www.globalbrand.com.bd/gallery-600x600.jpg"
    )


def test_job_clears_old_images_when_no_600x600_image_is_found(
    tmp_path, monkeypatch, caplog
) -> None:
    class Result:
        html = "<h1>Exact Mouse</h1><img src='/main-300x300.jpg'>"

    class FakeCrawler:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def arun(self, url):
            return Result()

    monkeypatch.setitem(
        sys.modules, "crawl4ai", SimpleNamespace(AsyncWebCrawler=FakeCrawler)
    )
    monkeypatch.setattr(
        csv_update.settings,
        "catalog_json_path",
        tmp_path / "globalbrand_product_urls.json",
    )
    monkeypatch.setattr(csv_update.settings, "sqlite_path", str(tmp_path / "app.db"))
    (tmp_path / "globalbrand_product_urls.json").write_text(json.dumps([{
        "product_name": "Exact Mouse",
        "product_url": "https://www.globalbrand.com.bd/exact-mouse",
    }]), encoding="utf-8")
    content = b"Product Name,Images\nExact Mouse,old-800x800.jpg\n"
    job = asyncio.run(csv_update.create_job(content, "products.csv"))
    asyncio.run(csv_update.process_job(job, content))

    with job.output_path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert rows[0]["Images"] == ""
    assert "No matching 600x600 product image URL found" in caplog.text


def test_job_uses_fallback_description_when_product_is_not_matched(
    tmp_path, monkeypatch
) -> None:
    class FakeCrawler:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    monkeypatch.setitem(
        sys.modules, "crawl4ai", SimpleNamespace(AsyncWebCrawler=FakeCrawler)
    )
    monkeypatch.setattr(
        csv_update.settings,
        "catalog_json_path",
        tmp_path / "globalbrand_product_urls.json",
    )
    monkeypatch.setattr(
        csv_update,
        "SEO_URLS_PATH",
        tmp_path / "all_seo_urls.json",
    )
    monkeypatch.setattr(csv_update.settings, "sqlite_path", str(tmp_path / "app.db"))
    (tmp_path / "globalbrand_product_urls.json").write_text("[]", encoding="utf-8")
    (tmp_path / "all_seo_urls.json").write_text("[]", encoding="utf-8")
    content = (
        "Product Name,Product Description\n"
        "Unmatched Keyboard,old description\n"
    ).encode()

    job = asyncio.run(csv_update.create_job(content, "products.csv"))
    asyncio.run(csv_update.process_job(job, content))

    with job.output_path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert rows[0]["Product Description"] == (
        "Buy Unmatched Keyboard from AKNET Innovations Ltd. in Bangladesh"
    )
