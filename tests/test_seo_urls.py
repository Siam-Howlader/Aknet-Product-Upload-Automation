import asyncio
import json

import pytest

from app.ai.models import ProductContent
from app.automation.products import OpenCartProductService
from app.automation.workflow import OpenCartAutomationWorkflow
from app.config import settings
from app.services import seo_urls


def test_record_seo_url_appends_and_ignores_case_insensitive_duplicates(tmp_path) -> None:
    path = tmp_path / "all_seo_urls.json"
    path.write_text(
        json.dumps([{"seo_url": "existing-product"}]),
        encoding="utf-8",
    )

    seo_urls.record_seo_url("New-Product", path)
    seo_urls.record_seo_url("NEW-PRODUCT", path)

    assert json.loads(path.read_text(encoding="utf-8")) == [
        {"seo_url": "existing-product"},
        {"seo_url": "New-Product"},
    ]


def test_workflow_records_seo_url_only_after_successful_save(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "all_seo_urls.json"
    path.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(seo_urls, "SEO_URLS_PATH", path)
    monkeypatch.setattr(settings, "headless", True)

    class Page:
        url = "https://opencart.test/admin/"

    class Browser:
        async def start(self):
            return object(), Page()

        async def stop(self):
            pass

        async def safe_screenshot(self, page, name):
            pass

    class LoginService:
        async def open_admin(self, page):
            pass

        async def login_if_required(self, page):
            pass

    class ProductService:
        def __init__(self, message: str) -> None:
            self.message = message
            self.saved_seo_url: str | None = None

        async def open_products_add_page(self, page):
            pass

        async def fill_product(self, page, payload, **kwargs):
            pass

        async def maybe_save(self, page, product_name, **kwargs):
            self.saved_seo_url = kwargs["seo_url"]
            return self.message

        build_seo_url = staticmethod(OpenCartProductService.build_seo_url)

    async def run(message: str, seo_url: str) -> tuple[str, str]:
        workflow = OpenCartAutomationWorkflow()
        workflow.browser = Browser()
        workflow.login_service = LoginService()
        workflow.product_service = ProductService(message)
        workflow._ensure_verified_selectors = lambda: None
        payload = ProductContent(
            product_name="Example Product",
            seo_url=seo_url,
            description="<p>Example product description.</p>",
            meta_title="Example Product Price in Bangladesh",
            meta_description="Example product description",
            meta_keywords="Example Product",
            product_tags="Example Product",
        )
        return await workflow.run(payload)

    asyncio.run(run("Product saved successfully.", ""))
    assert json.loads(path.read_text(encoding="utf-8")) == [
        {"seo_url": "example-product"},
    ]

    path.write_text("[]", encoding="utf-8")
    asyncio.run(run("Dry-run mode enabled; save not executed.", "custom-slug"))
    assert json.loads(path.read_text(encoding="utf-8")) == []
