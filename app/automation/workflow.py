import logging

from app.ai.models import ProductContent
from app.automation.browser import BrowserManager
from app.automation.errors import SelectorResolutionError
from app.automation.login import OpenCartLoginService
from app.automation.products import OpenCartProductService
from app.automation.selectors import SELECTORS
from app.config import settings
from app.services.seo_urls import record_seo_url

logger = logging.getLogger(__name__)


class OpenCartAutomationWorkflow:
    def __init__(self) -> None:
        self.browser = BrowserManager()
        self.login_service = OpenCartLoginService(SELECTORS)
        self.product_service = OpenCartProductService(SELECTORS)

    async def run(self, payload: ProductContent) -> tuple[str, str]:
        context = None
        page = None
        try:
            self._ensure_verified_selectors()
            context, page = await self.browser.start()
            await self.login_service.open_admin(page)
            await self.login_service.login_if_required(page)
            await self.product_service.open_products_add_page(page)
            model = getattr(payload, "model", None)
            await self.product_service.fill_product(
                page,
                payload,
                model=model,
                price=getattr(payload, "price", settings.product_price),
                quantity=getattr(payload, "quantity",
                                 settings.product_quantity),
                stock_status_option_index=getattr(
                    payload, "stock_status_option_index", settings.stock_status_option_index),
            )
            seo_url = payload.seo_url or self.product_service.build_seo_url(
                payload.product_name
            )
            message = await self.product_service.maybe_save(
                page,
                payload.product_name,
                manufacturer=getattr(payload, "manufacturer", ""),
                categories=getattr(payload, "categories", ""),
                filters=getattr(payload, "filters", ""),
                seo_url=seo_url,
                images=getattr(payload, "images", ""),
            )
            if "saved successfully" in message.casefold():
                record_seo_url(seo_url)
            logger.info("Automation completed")
            return message, page.url
        except Exception:
            if page:
                await self.browser.safe_screenshot(page, "automation_failure")
            raise
        finally:
            if context and page and (settings.headless or not settings.keep_browser_open):
                await self.browser.stop()

    def _ensure_verified_selectors(self) -> None:
        required_fields = [
            "catalog_menu_link",
            "products_link",
            "add_product_button",
            "product_name_input",
            "description_editor",
            "meta_title_input",
            "meta_description_input",
            "meta_keywords_input",
            "tags_input",
            "data_tab",
            "image_tab",
            "image_url_input",
            "image_url_button",
            "input_model",
            "input_price",
            "input_quantity",
            "input_stock_status",
            "add_attribute_button",
            "attribute_name_input",
            "seo_tab",
            "seo_url_input",
            "links_tab",
            "manufacturer_input",
            "category_input",
            "filter_input",
            "save_button",
        ]
        missing = [name for name in required_fields if getattr(
            SELECTORS, name) == "REQUIRES_LIVE_INSPECTION"]
        if missing:
            fields = ", ".join(missing)
            raise SelectorResolutionError(
                f"Selectors not verified for: {fields}. Run scripts/inspect_opencart.py and update app/automation/selectors.json."
            )
