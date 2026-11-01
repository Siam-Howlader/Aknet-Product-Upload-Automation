import logging
import re
from html import unescape
from typing import Any

from bs4 import BeautifulSoup
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from app.ai.models import ProductContent
from app.automation.errors import SelectorResolutionError, VerificationError
from app.automation.selectors import OpenCartSelectors
from app.config import settings

logger = logging.getLogger(__name__)


class OpenCartProductService:
    """Catalog/Product navigation, field filling, and verification."""

    def __init__(self, selectors: OpenCartSelectors) -> None:
        self.selectors = selectors

    @staticmethod
    def _attribute_rows(
        specifications: dict[str, str],
        key_attributes: dict[str, str] | None = None,
    ) -> list[tuple[str, str]]:
        """Upload Key1-Key5 as names and their generated sentences as values."""
        supplied_keys = key_attributes or {}
        key_rows = [
            (f"Key{index}", supplied_keys[f"Key{index}"])
            for index in range(1, 6)
            if f"Key{index}" in supplied_keys
        ]
        extra_key_rows = [
            (name, value) for name, value in supplied_keys.items()
            if name not in {key_name for key_name, _ in key_rows}
        ]
        key_rows.extend(extra_key_rows)
        key_names = {name.casefold() for name, _ in key_rows}
        specification_rows = [
            (name, result) for name, result in specifications.items()
            if name.casefold() not in key_names
            and not re.match(r"^key\s*feature\s*[1-5](?:\b|$)", name.strip(), re.IGNORECASE)
        ]
        return key_rows + specification_rows

    async def open_products_add_page(self, page: Any) -> None:
        logger.info("Opening Products")
        await self._click_first_existing(page, self.selectors.catalog_menu_link)
        await self._click_first_existing(page, self.selectors.products_link)
        await page.wait_for_load_state("domcontentloaded")
        await self._step_delay(page)

        logger.info("Opening Add Product")
        await self._click_first_existing(page, self.selectors.add_product_button)
        await page.wait_for_load_state("domcontentloaded")
        await self._step_delay(page)

    async def fill_product(
        self,
        page: Any,
        payload: ProductContent,
        model: str | None = None,
        price: float = 0,
        quantity: int = 10,
        stock_status_option_index: int = 1,
    ) -> None:
        logger.info("Filling product name")
        await self._fill_input(page, self.selectors.product_name_input, payload.product_name)

        logger.info("Filling description")
        await self._fill_description(
            page,
            payload.description,
        )

        logger.info("Filling SEO fields")
        await self._fill_input(page, self.selectors.meta_title_input, payload.meta_title)
        await self._fill_input(page, self.selectors.meta_description_input, payload.meta_description)
        await self._fill_input(page, self.selectors.meta_keywords_input, payload.meta_keywords)
        await self._fill_tags(page, payload.product_tags)

        if model and model.strip():
            logger.info("Filling model")
            await self._click_first_existing(page, self.selectors.data_tab)
            await page.wait_for_load_state("domcontentloaded")
            await self._fill_input(page, self.selectors.input_model, model.strip())

        logger.info("Filling price and quantity")
        if not model or not model.strip():
            await self._click_first_existing(page, self.selectors.data_tab)
            await page.wait_for_load_state("domcontentloaded")
        await self._fill_input(page, self.selectors.input_price, str(price))
        await self._fill_input(page, self.selectors.input_quantity, str(quantity))
        await self._select_stock_status(page, stock_status_option_index)

        await self._fill_specifications(
            page, payload.specifications, payload.key_attributes)

    async def verify_product(
        self,
        page: Any,
        payload: ProductContent,
        model: str | None = None,
        price: float = 0,
        quantity: int = 10,
        stock_status_option_index: int = 1,
    ) -> None:
        logger.info("Verifying fields")

        actual_name = await self._read_input(page, self.selectors.product_name_input)
        if actual_name.strip() != payload.product_name.strip():
            raise VerificationError("Product Name verification failed")

        actual_meta_title = await self._read_input(page, self.selectors.meta_title_input)
        if actual_meta_title.strip() != payload.meta_title.strip():
            raise VerificationError("Meta Title verification failed")

        actual_meta_description = await self._read_input(page, self.selectors.meta_description_input)
        if actual_meta_description.strip() != payload.meta_description.strip():
            raise VerificationError("Meta Description verification failed")

        actual_meta_keywords = await self._read_input(page, self.selectors.meta_keywords_input)
        if actual_meta_keywords.strip() != payload.meta_keywords.strip():
            raise VerificationError("Meta Keywords verification failed")

        desc_html = await self._read_description(page)
        expected_description = " ".join(
            BeautifulSoup(payload.description, "html.parser")
            .get_text(" ", strip=True).split())
        actual_description = " ".join(
            BeautifulSoup(desc_html, "html.parser")
            .get_text(" ", strip=True).split())
        if expected_description not in actual_description:
            raise VerificationError("Description verification failed")

        tags_value = await self._read_input(page, self.selectors.tags_input)
        first_tag = payload.product_tags.split(",")[0].strip()
        if first_tag and first_tag.lower() not in tags_value.lower():
            # Tag widgets often mirror tokens elsewhere, so only enforce contains check here.
            raise VerificationError("Product Tags verification failed")

        if model and model.strip():
            actual_model = await self._read_input(page, self.selectors.input_model)
            if actual_model.strip() != model.strip():
                raise VerificationError("Model verification failed")

        actual_price = await self._read_input(page, self.selectors.input_price)
        if actual_price.strip() not in {str(price), f"{price:.1f}"}:
            raise VerificationError("Price verification failed")

        actual_quantity = await self._read_input(page, self.selectors.input_quantity)
        if actual_quantity.strip() != str(quantity):
            raise VerificationError("Quantity verification failed")

        stock_status = page.locator(self.selectors.input_stock_status)
        if await stock_status.count() == 0:
            raise SelectorResolutionError("Stock status selector not found")
        selected_index = await stock_status.first.evaluate(
            "el => el.selectedIndex")
        if selected_index != stock_status_option_index:
            raise VerificationError("Stock status verification failed")
        await self._step_delay(page)

        await self._verify_specifications(
            page, payload.specifications, payload.key_attributes)

    async def maybe_save(
        self,
        page: Any,
        product_name: str,
        manufacturer: str = "",
        categories: str = "",
        filters: str = "",
        seo_url: str = "",
        images: str = "",
    ) -> str:
        await self._fill_links_tab(page, manufacturer=manufacturer, categories=categories, filters=filters)
        await self._fill_seo_url(
            page,
            seo_url or self.build_seo_url(product_name),
        )

        if settings.dry_run:
            return "Dry-run mode enabled. Product is filled and verified; save not executed."
        if not settings.auto_save:
            return "AUTO_SAVE is disabled. Product is filled and verified; save not executed."

        logger.info("Opening Data tab before save")
        await self._click_first_existing(page, self.selectors.data_tab)
        await page.wait_for_load_state("domcontentloaded")
        await self._step_delay(page)

        image_urls = self._split_csv(images)
        if image_urls:
            logger.info("Adding %s product image(s)", len(image_urls))
            await self._click_first_existing(page, self.selectors.image_tab)
            for image_url in image_urls:
                await self._fill_input(
                    page, self.selectors.image_url_input, image_url)
                image_button = page.locator(self.selectors.image_url_button)
                if await image_button.count() == 0:
                    raise SelectorResolutionError(
                        f"No selector matched: {self.selectors.image_url_button}")
                await image_button.first.click()
                await page.wait_for_timeout(1000)

        await self._click_first_existing(page, self.selectors.save_button)
        await page.wait_for_load_state("networkidle")
        await self._step_delay(page)
        success_locator = page.locator(
            ".alert-success, .toast-success, .notification-success, "
            "[role='alert'].alert-success"
        )
        if await success_locator.count() > 0:
            return "Product saved successfully."

        body_text = (await page.locator("body").inner_text()).lower()
        success_texts = (
            "success: you have modified products",
            "success: you have added a product",
            "successfully modified",
            "successfully added",
        )
        if any(text in body_text for text in success_texts):
            return "Product saved successfully."

        # OpenCart normally redirects from product/add to the product list after save.
        if "route=catalog/product" in page.url and "/add" not in page.url:
            return "Product saved successfully."

        if await success_locator.count() == 0:
            raise VerificationError(
                "Save was clicked but success notification was not detected.")

    @staticmethod
    def _split_csv(value: str) -> list[str]:
        return [
            item.strip()
            for item in str(value or "").split(",")
            if item.strip()
        ]

    @staticmethod
    def _description_with_key_features(
        description: str,
        key_attributes: dict[str, str],
    ) -> str:
        return description

    async def _fill_links_tab(
        self,
        page: Any,
        manufacturer: str = "",
        categories: str = "",
        filters: str = "",
    ) -> None:
        if not manufacturer and not categories and not filters:
            return
        logger.info("Opening Links tab")
        await self._click_first_existing(page, self.selectors.links_tab)
        tab = page.locator("#tab-links")
        if await tab.count() == 0:
            raise SelectorResolutionError(
                "Links tab content selector not found")
        await tab.first.wait_for(state="visible", timeout=settings.browser_timeout)
        await self._step_delay(page)
        if manufacturer.strip():
            await self._fill_autocomplete_and_select_second(
                page, self.selectors.manufacturer_input, manufacturer.strip(), "manufacturer")
        for category in self._split_csv(categories):
            await self._fill_autocomplete_and_select_first(
                page, self.selectors.category_input, category, "category")
        for filter_value in self._split_csv(filters):
            await self._fill_autocomplete_and_select_first(
                page, self.selectors.filter_input, filter_value, "filter")

    async def _fill_specifications(
        self,
        page: Any,
        specifications: dict[str, str],
        key_attributes: dict[str, str] | None = None,
    ) -> None:
        attribute_rows = self._attribute_rows(specifications, key_attributes)
        if not attribute_rows:
            return
        logger.info("Opening Attribute tab")
        await self._click_first_existing(page, self.selectors.attribute_tab)
        attribute_tab = page.locator("#tab-attribute")
        if await attribute_tab.count() == 0:
            raise SelectorResolutionError(
                "Attribute tab content selector not found")
        await attribute_tab.first.wait_for(
            state="visible", timeout=settings.browser_timeout)

        for row_index, (attribute_name, result) in enumerate(attribute_rows):
            await self._click_first_existing(page, self.selectors.add_attribute_button)
            name_selector = f'input[name="product_attribute[{row_index}][name]"]'
            text_selector = f'textarea[name="product_attribute[{row_index}][product_attribute_description][1][text]"]'
            attribute_input = await self._wait_for_indexed_locator(
                page, name_selector, "input[name^='product_attribute'][name$='[name]']",
                row_index, f"{attribute_name} input")
            await self._apply_attribute_name(page, attribute_input, attribute_name, "")
            text_input = await self._wait_for_indexed_locator(
                page, text_selector, "textarea[name^='product_attribute'][name$='[text]']",
                row_index, f"{attribute_name} textarea")
            await self._commit_field_value(text_input, result)

    async def _fill_autocomplete_and_select_first(
        self, page: Any, selector: str, value: str, label: str
    ) -> None:
        if not value:
            return
        locator = page.locator(selector)
        if await locator.count() == 0:
            raise SelectorResolutionError(
                f"{label.title()} input selector not found")
        input_box = locator.first
        await input_box.click()
        await input_box.fill(value)
        await input_box.dispatch_event("input")
        await input_box.dispatch_event("change")
        await self._select_first_real_autocomplete_option(page, label)
        await self._step_delay(page)

    async def _fill_autocomplete_and_select_second(
        self, page: Any, selector: str, value: str, label: str
    ) -> None:
        await self._fill_autocomplete_and_select_first(page, selector, value, label)

    async def _select_first_real_autocomplete_option(self, page: Any, label: str) -> None:
        dropdown = page.locator("ul.dropdown-menu:visible")
        try:
            await dropdown.first.wait_for(state="visible", timeout=settings.browser_timeout)
            option = page.locator(
                "ul.dropdown-menu:visible li[data-value]:not([data-value='0']) a"
            ).first
            await option.wait_for(state="visible", timeout=settings.browser_timeout)
            await option.click()
        except Exception as exc:
            raise SelectorResolutionError(
                f"No {label} autocomplete options appeared") from exc

    async def _fill_seo_url(self, page: Any, seo_url: str) -> None:
        logger.info("Filling SEO URL")
        await self._click_first_existing(page, self.selectors.seo_tab)
        seo_tab = page.locator("#tab-seo")
        if await seo_tab.count() == 0:
            raise SelectorResolutionError("SEO tab content selector not found")
        await seo_tab.first.wait_for(
            state="visible", timeout=settings.browser_timeout)

        seo_url = seo_url.strip()
        if not seo_url:
            raise VerificationError("SEO URL cannot be blank")
        seo_input = page.locator(self.selectors.seo_url_input)
        if await seo_input.count() == 0:
            raise SelectorResolutionError("SEO URL input selector not found")
        await self._commit_field_value(seo_input.first, seo_url)
        if (await seo_input.first.input_value()).strip() != seo_url:
            raise VerificationError("SEO URL verification failed")

    @staticmethod
    def build_seo_url(product_name: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", product_name.casefold()).strip("-")
        if not slug:
            raise VerificationError(
                "Product name cannot produce a valid SEO URL")
        return slug[:255].rstrip("-")

    async def _click_first_existing(self, page: Any, selector: str) -> None:
        options = [part.strip()
                   for part in selector.split(",") if part.strip()]
        for option in options:
            loc = page.locator(option)
            if await loc.count() > 0:
                await loc.first.click()
                await self._step_delay(page)
                return
        raise SelectorResolutionError(f"No selector matched: {selector}")

    async def _fill_input(self, page: Any, selector: str, value: str) -> None:
        loc = page.locator(selector)
        if await loc.count() == 0:
            raise SelectorResolutionError(
                f"Field selector not found: {selector}")
        await loc.first.fill(value)
        await loc.first.dispatch_event("change")
        await self._step_delay(page)

    async def _read_input(self, page: Any, selector: str) -> str:
        loc = page.locator(selector)
        if await loc.count() == 0:
            raise SelectorResolutionError(
                f"Field selector not found: {selector}")
        value = await loc.first.input_value()
        await self._step_delay(page)
        return value

    async def _fill_description(self, page: Any, html: str) -> None:
        # Summernote contenteditable
        summernote = page.locator("div.note-editable")
        if await summernote.count() > 0:
            await summernote.first.click()
            await summernote.first.evaluate("(el, value) => { el.innerHTML = value; }", html)
            textarea = page.locator(
                "textarea[name='product_description[1][description]']")
            if await textarea.count() > 0:
                await textarea.first.evaluate("(el, value) => { el.value = value; }", html)
                await textarea.first.dispatch_event("change")
            await self._step_delay(page)
            return

        # TinyMCE iframe
        tinymce_iframe = page.locator("iframe.tox-edit-area__iframe")
        if await tinymce_iframe.count() > 0:
            frame = await tinymce_iframe.first.content_frame()
            if frame:
                body = frame.locator("body")
                await body.fill("")
                await body.type(html)
                await self._step_delay(page)
                return

        # CKEditor iframe
        ck_iframe = page.locator("iframe.cke_wysiwyg_frame")
        if await ck_iframe.count() > 0:
            frame = await ck_iframe.first.content_frame()
            if frame:
                body = frame.locator("body")
                await body.fill("")
                await body.type(html)
                await self._step_delay(page)
                return

        # Fallback textarea
        textarea = page.locator(
            "textarea[name='product_description[1][description]']")
        if await textarea.count() == 0:
            raise SelectorResolutionError(
                "Description editor not found. Verify editor selector for this OpenCart version.")
        await textarea.first.fill(html)
        await textarea.first.dispatch_event("change")
        await self._step_delay(page)

    async def _read_description(self, page: Any) -> str:
        summernote = page.locator("div.note-editable")
        if await summernote.count() > 0:
            value = await summernote.first.inner_html()
            await self._step_delay(page)
            return value

        textarea = page.locator(
            "textarea[name='product_description[1][description]']")
        if await textarea.count() > 0:
            value = await textarea.first.input_value()
            await self._step_delay(page)
            return value

        return ""

    async def _fill_tags(self, page: Any, tags_csv: str) -> None:
        tag_input = page.locator(self.selectors.tags_input)
        if await tag_input.count() == 0:
            raise SelectorResolutionError("Tag input selector not found")

        tags = [tag.strip() for tag in tags_csv.split(",") if tag.strip()]
        if not tags:
            return

        await tag_input.first.click()
        await tag_input.first.fill("")
        # Some OpenCart variants accept comma-separated tags directly.
        await tag_input.first.fill(", ".join(tags))
        await tag_input.first.dispatch_event("input")
        await tag_input.first.dispatch_event("change")
        await self._step_delay(page)

    async def _select_stock_status(self, page: Any, option_index: int) -> None:
        stock_status = page.locator(self.selectors.input_stock_status)
        if await stock_status.count() == 0:
            raise SelectorResolutionError("Stock status selector not found")
        option_count = await stock_status.first.locator("option").count()
        if option_count <= option_index:
            raise SelectorResolutionError(
                f"Stock status option index {option_index} is unavailable")
        await stock_status.first.select_option(index=option_index)
        await stock_status.first.dispatch_event("change")
        await self._step_delay(page)

    async def _fill_specifications(
        self,
        page: Any,
        specifications: dict[str, str],
        key_attributes: dict[str, str] | None = None,
    ) -> None:
        attribute_rows = self._attribute_rows(specifications, key_attributes)
        if not attribute_rows:
            return

        logger.info("Opening Attribute tab")
        await self._click_first_existing(page, self.selectors.attribute_tab)
        attribute_tab = page.locator("#tab-attribute")
        if await attribute_tab.count() == 0:
            raise SelectorResolutionError(
                "Attribute tab content selector not found")
        await attribute_tab.first.wait_for(
            state="visible", timeout=settings.browser_timeout)

        add_button = page.locator(
            self.selectors.add_attribute_button).locator(":visible")
        if await add_button.count() == 0:
            raise SelectorResolutionError(
                "Visible Add Attribute button not found")

        for row_index, (attribute_name, result) in enumerate(attribute_rows):
            await add_button.first.click()

            name_selector = (
                f"input[name=\"product_attribute[{row_index}][name]\"]")
            text_selector = (
                f"textarea[name=\"product_attribute[{row_index}]"
                "[product_attribute_description][1][text]\"]")
            attribute_input = await self._wait_for_indexed_locator(
                page,
                name_selector,
                "input[name^='product_attribute'][name$='[name]']",
                row_index,
                f"{attribute_name} input",
            )
            await self._apply_attribute_name(
                page, attribute_input, attribute_name, "a[href='#']")

            text_input = await self._wait_for_indexed_locator(
                page,
                text_selector,
                "textarea[name^='product_attribute'][name$='[text]']",
                row_index,
                f"{attribute_name} textarea",
            )
            await self._commit_field_value(text_input, result)

    async def _verify_specifications(
        self,
        page: Any,
        specifications: dict[str, str],
        key_attributes: dict[str, str] | None = None,
    ) -> None:
        attribute_rows = self._attribute_rows(specifications, key_attributes)
        for row_index, (attribute_name, result) in enumerate(attribute_rows):
            name_selector = (
                f"input[name=\"product_attribute[{row_index}][name]\"]")
            text_selector = (
                f"textarea[name=\"product_attribute[{row_index}]"
                "[product_attribute_description][1][text]\"]")
            attribute_input = await self._wait_for_indexed_locator(
                page,
                name_selector,
                "input[name^='product_attribute'][name$='[name]']",
                row_index,
                f"{attribute_name} input",
            )
            actual_attribute_name = await attribute_input.input_value()
            if self._normalize_attribute_name(actual_attribute_name) != self._normalize_attribute_name(attribute_name):
                raise VerificationError(
                    f"Specification {attribute_name} name verification failed")

            text_input = await self._wait_for_indexed_locator(
                page,
                text_selector,
                "textarea[name^='product_attribute'][name$='[text]']",
                row_index,
                f"{attribute_name} textarea",
            )
            actual_result = await text_input.input_value()
            if self._normalize_attribute_value(actual_result) != self._normalize_attribute_value(result):
                raise VerificationError(
                    f"Specification {attribute_name} result verification failed")

    @staticmethod
    def _normalize_attribute_name(value: str) -> str:
        return " ".join(unescape(value).split()).casefold()

    @staticmethod
    def _normalize_attribute_value(value: str) -> str:
        normalized = unescape(value).replace("\r\n", "\n").replace("\r", "\n")
        return "\n".join(" ".join(line.split()) for line in normalized.split("\n"))

    async def _fill_single_attribute(
        self,
        page: Any,
        key_number: int,
        attribute_name: str,
        feature_text: str,
    ) -> None:
        add_button = getattr(
            self.selectors, f"add_attribute_button_key{key_number}")
        name_selector = getattr(
            self.selectors, f"attribute_name_input_key{key_number}")
        autocomplete_selector = getattr(
            self.selectors, f"attribute_autocomplete_option_key{key_number}"
        )
        text_selector = getattr(
            self.selectors, f"attribute_text_input_key{key_number}")

        logger.info("Adding attribute %s", attribute_name)
        add_locator = page.locator(add_button)
        if await add_locator.count() == 0:
            raise SelectorResolutionError(
                f"Add-attribute button not found for {attribute_name}")

        await add_locator.last.click()

        row_index = key_number - 1
        attribute_input = await self._wait_for_indexed_locator(
            page,
            name_selector,
            "input[name^='product_attribute'][name$='[name]']",
            row_index,
            f"{attribute_name} input",
        )
        logger.info("Entering attribute: %s", attribute_name)
        await self._apply_attribute_name(
            page,
            attribute_input,
            attribute_name,
            autocomplete_selector,
        )

        attribute_text_input = await self._wait_for_indexed_locator(
            page,
            text_selector,
            "textarea[name^='product_attribute'][name$='[text]']",
            row_index,
            f"{attribute_name} textarea",
        )

        logger.info("Filling %s attribute text", attribute_name)
        await self._commit_field_value(attribute_text_input.first, feature_text)
        logger.info("Attribute %s filled successfully", attribute_name)

    async def _apply_attribute_name(
        self,
        page: Any,
        attribute_input: Any,
        attribute_name: str,
        autocomplete_selector: str,
    ) -> None:
        await attribute_input.fill(attribute_name)
        await attribute_input.dispatch_event("input")
        await attribute_input.dispatch_event("change")
        selected = await self._select_first_attribute_option(
            page, autocomplete_selector)
        if not selected:
            await attribute_input.dispatch_event("blur")

    async def _select_first_attribute_option(
        self,
        page: Any,
        autocomplete_selector: str,
    ) -> bool:
        dropdowns = page.locator("ul.dropdown-menu:visible")
        try:
            await dropdowns.first.wait_for(
                state="visible", timeout=min(settings.browser_timeout, 1500))
        except (TimeoutError, PlaywrightTimeoutError):
            return False
        dropdown = dropdowns.nth(await dropdowns.count() - 1)
        option_selector = (
            autocomplete_selector
            if autocomplete_selector
            and autocomplete_selector != "REQUIRES_LIVE_INSPECTION"
            else "li[data-value]:not([data-value='0']) a"
        )
        options = dropdown.locator(option_selector)
        try:
            await options.first.wait_for(
                state="visible", timeout=min(settings.browser_timeout, 1500))
            await options.first.click()
            return True
        except (TimeoutError, PlaywrightTimeoutError):
            return False


    async def _commit_field_value(self, locator: Any, value: str) -> None:
        await locator.fill(value)
        await locator.dispatch_event("input")
        await locator.dispatch_event("change")
        await locator.dispatch_event("blur")

    async def _wait_for_attribute_input(
        self,
        page: Any,
        selector: str,
        row_index: int,
    ) -> Any:
        locator = page.locator(selector)
        try:
            await locator.nth(row_index).wait_for(
                state="visible", timeout=settings.browser_timeout
            )
        except Exception as exc:
            raise SelectorResolutionError(
                f"Attribute input row {row_index + 1} was not created") from exc
        return locator.nth(row_index)

    async def _wait_for_attribute_textarea(
        self,
        page: Any,
        selector: str,
        row_index: int,
    ) -> Any:
        locator = page.locator(selector)
        try:
            await locator.nth(row_index).wait_for(
                state="visible", timeout=settings.browser_timeout
            )
        except Exception as exc:
            raise SelectorResolutionError(
                f"Attribute textarea row {row_index + 1} was not created") from exc
        return locator.nth(row_index)

    async def _wait_for_indexed_locator(
        self,
        page: Any,
        selector: str,
        fallback_selector: str,
        row_index: int,
        field_name: str,
    ) -> Any:
        locator = page.locator(selector)
        try:
            await locator.nth(row_index).wait_for(
                state="visible", timeout=1000
            )
            return locator.nth(row_index)
        except Exception:
            fallback = page.locator(fallback_selector)
            try:
                await fallback.nth(row_index).wait_for(
                    state="visible", timeout=settings.browser_timeout
                )
            except Exception as exc:
                raise SelectorResolutionError(
                    f"{field_name} row {row_index + 1} was not created") from exc
            return fallback.nth(row_index)

    async def _find_attribute_input(self, page: Any, selector: str | None = None, minimum_count: int = 1) -> Any:
        selectors = [selector, self.selectors.attribute_name_input, "input[name^='product_attribute'][name$='[name]']"] if selector else [
            self.selectors.attribute_name_input, "input[name^='product_attribute'][name$='[name]']"]
        for candidate_selector in selectors:
            if not candidate_selector:
                continue
            locator = page.locator(candidate_selector)
            if await locator.count() >= minimum_count:
                for index in range(await locator.count() - 1, -1, -1):
                    candidate = locator.nth(index)
                    if await candidate.is_visible():
                        return candidate
        raise SelectorResolutionError(
            "Attribute name input row did not appear. Verify attribute_name_input selector.")

    async def _find_visible_suggestion(
        self,
        page: Any,
        attribute_name: str,
        autocomplete_selector: str,
    ) -> Any:
        if autocomplete_selector != "REQUIRES_LIVE_INSPECTION":
            exact_locator = page.locator(autocomplete_selector)
            try:
                await exact_locator.first.wait_for(state="visible", timeout=3000)
            except Exception:
                pass
            for index in range(await exact_locator.count()):
                candidate = exact_locator.nth(index)
                if await candidate.is_visible():
                    suggestion_text = " ".join((await candidate.inner_text()).split())
                    if suggestion_text.casefold() == attribute_name.casefold():
                        return candidate

        selectors = [
            self.selectors.attribute_autocomplete_suggestions,
            ".ui-autocomplete li",
            ".dropdown-menu li",
            "[role='option']",
        ]
        visible_candidates: list[Any] = []
        for selector in selectors:
            locator = page.locator(selector)
            try:
                if await locator.count() == 0:
                    continue
                await locator.first.wait_for(state="visible", timeout=3000)
                for index in range(await locator.count()):
                    candidate = locator.nth(index)
                    if await candidate.is_visible():
                        visible_candidates.append(candidate)
            except Exception:
                continue

        for candidate in visible_candidates:
            suggestion_text = " ".join((await candidate.inner_text()).split())
            if suggestion_text.casefold() == attribute_name.casefold():
                return candidate

        raise SelectorResolutionError(
            f"No exact autocomplete suggestion appeared for attribute '{attribute_name}'.")

    async def _step_delay(self, page: Any) -> None:
        await page.wait_for_timeout(round(settings.automation_step_delay * 1000))

    async def upload_product(self) -> None:
        raise NotImplementedError(
            "Product automation will be implemented in later phases")
