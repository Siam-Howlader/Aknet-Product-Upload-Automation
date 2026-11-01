from dataclasses import dataclass
import json
from pathlib import Path

from app.config import settings


@dataclass(frozen=True, init=False)
class OpenCartSelectors:
    """Selectors must be validated against the live OpenCart instance."""

    username_input: str = 'input[name="username"]'
    password_input: str = 'input[name="password"]'
    login_button: str = 'button[type="submit"]'

    catalog_menu_link: str = "REQUIRES_LIVE_INSPECTION"
    products_link: str = "REQUIRES_LIVE_INSPECTION"
    add_product_button: str = "REQUIRES_LIVE_INSPECTION"

    product_name_input: str = "REQUIRES_LIVE_INSPECTION"
    description_editor: str = "REQUIRES_LIVE_INSPECTION"
    meta_title_input: str = "REQUIRES_LIVE_INSPECTION"
    meta_description_input: str = "REQUIRES_LIVE_INSPECTION"
    meta_keywords_input: str = "REQUIRES_LIVE_INSPECTION"
    tags_input: str = "REQUIRES_LIVE_INSPECTION"
    data_tab: str = "REQUIRES_LIVE_INSPECTION"
    image_tab: str = "REQUIRES_LIVE_INSPECTION"
    image_url_input: str = "REQUIRES_LIVE_INSPECTION"
    image_url_button: str = "REQUIRES_LIVE_INSPECTION"
    input_model: str = "REQUIRES_LIVE_INSPECTION"
    input_price: str = "REQUIRES_LIVE_INSPECTION"
    input_quantity: str = "REQUIRES_LIVE_INSPECTION"
    input_stock_status: str = "REQUIRES_LIVE_INSPECTION"
    attribute_tab: str = "REQUIRES_LIVE_INSPECTION"
    add_attribute_button: str = "REQUIRES_LIVE_INSPECTION"
    attribute_name_input: str = "REQUIRES_LIVE_INSPECTION"
    attribute_autocomplete_option_key1: str = "REQUIRES_LIVE_INSPECTION"
    attribute_text_input_key1: str = "REQUIRES_LIVE_INSPECTION"
    attribute_autocomplete_suggestions: str = "REQUIRES_LIVE_INSPECTION"
    save_button: str = "REQUIRES_LIVE_INSPECTION"

    add_attribute_button_key1: str = "REQUIRES_LIVE_INSPECTION"
    attribute_name_input_key1: str = "REQUIRES_LIVE_INSPECTION"
    attribute_autocomplete_option_key2: str = "REQUIRES_LIVE_INSPECTION"
    attribute_text_input_key2: str = "REQUIRES_LIVE_INSPECTION"
    add_attribute_button_key2: str = "REQUIRES_LIVE_INSPECTION"
    attribute_name_input_key2: str = "REQUIRES_LIVE_INSPECTION"
    attribute_autocomplete_option_key3: str = "REQUIRES_LIVE_INSPECTION"
    attribute_text_input_key3: str = "REQUIRES_LIVE_INSPECTION"
    add_attribute_button_key3: str = "REQUIRES_LIVE_INSPECTION"
    attribute_name_input_key3: str = "REQUIRES_LIVE_INSPECTION"
    attribute_autocomplete_option_key4: str = "REQUIRES_LIVE_INSPECTION"
    attribute_text_input_key4: str = "REQUIRES_LIVE_INSPECTION"
    add_attribute_button_key4: str = "REQUIRES_LIVE_INSPECTION"
    attribute_name_input_key4: str = "REQUIRES_LIVE_INSPECTION"
    attribute_autocomplete_option_key5: str = "REQUIRES_LIVE_INSPECTION"
    attribute_text_input_key5: str = "REQUIRES_LIVE_INSPECTION"
    seo_tab: str = "REQUIRES_LIVE_INSPECTION"
    seo_url_input: str = "REQUIRES_LIVE_INSPECTION"
    links_tab: str = "REQUIRES_LIVE_INSPECTION"
    manufacturer_input: str = "REQUIRES_LIVE_INSPECTION"
    category_input: str = "REQUIRES_LIVE_INSPECTION"
    filter_input: str = "REQUIRES_LIVE_INSPECTION"
    add_attribute_button_key5: str = "REQUIRES_LIVE_INSPECTION"
    attribute_name_input_key5: str = "REQUIRES_LIVE_INSPECTION"

    def __init__(self, **data: str) -> None:
        defaults = {
            "username_input": 'input[name="username"]',
            "password_input": 'input[name="password"]',
            "login_button": 'button[type="submit"]',
            "catalog_menu_link": "REQUIRES_LIVE_INSPECTION",
            "products_link": "REQUIRES_LIVE_INSPECTION",
            "add_product_button": "REQUIRES_LIVE_INSPECTION",
            "product_name_input": "REQUIRES_LIVE_INSPECTION",
            "description_editor": "REQUIRES_LIVE_INSPECTION",
            "meta_title_input": "REQUIRES_LIVE_INSPECTION",
            "meta_description_input": "REQUIRES_LIVE_INSPECTION",
            "meta_keywords_input": "REQUIRES_LIVE_INSPECTION",
            "tags_input": "REQUIRES_LIVE_INSPECTION",
            "data_tab": "REQUIRES_LIVE_INSPECTION",
            "image_tab": "REQUIRES_LIVE_INSPECTION",
            "image_url_input": "REQUIRES_LIVE_INSPECTION",
            "image_url_button": "REQUIRES_LIVE_INSPECTION",
            "input_model": "REQUIRES_LIVE_INSPECTION",
            "input_price": "REQUIRES_LIVE_INSPECTION",
            "input_quantity": "REQUIRES_LIVE_INSPECTION",
            "input_stock_status": "REQUIRES_LIVE_INSPECTION",
            "attribute_tab": "REQUIRES_LIVE_INSPECTION",
            "add_attribute_button": "REQUIRES_LIVE_INSPECTION",
            "attribute_name_input": "REQUIRES_LIVE_INSPECTION",
            "attribute_autocomplete_option_key1": "REQUIRES_LIVE_INSPECTION",
            "attribute_text_input_key1": "REQUIRES_LIVE_INSPECTION",
            "attribute_autocomplete_suggestions": "REQUIRES_LIVE_INSPECTION",
            "save_button": "REQUIRES_LIVE_INSPECTION",
            "add_attribute_button_key1": "REQUIRES_LIVE_INSPECTION",
            "attribute_name_input_key1": "REQUIRES_LIVE_INSPECTION",
            "attribute_autocomplete_option_key2": "REQUIRES_LIVE_INSPECTION",
            "attribute_text_input_key2": "REQUIRES_LIVE_INSPECTION",
            "add_attribute_button_key2": "REQUIRES_LIVE_INSPECTION",
            "attribute_name_input_key2": "REQUIRES_LIVE_INSPECTION",
            "attribute_autocomplete_option_key3": "REQUIRES_LIVE_INSPECTION",
            "attribute_text_input_key3": "REQUIRES_LIVE_INSPECTION",
            "add_attribute_button_key3": "REQUIRES_LIVE_INSPECTION",
            "attribute_name_input_key3": "REQUIRES_LIVE_INSPECTION",
            "attribute_autocomplete_option_key4": "REQUIRES_LIVE_INSPECTION",
            "attribute_text_input_key4": "REQUIRES_LIVE_INSPECTION",
            "add_attribute_button_key4": "REQUIRES_LIVE_INSPECTION",
            "attribute_name_input_key4": "REQUIRES_LIVE_INSPECTION",
            "attribute_autocomplete_option_key5": "REQUIRES_LIVE_INSPECTION",
            "attribute_text_input_key5": "REQUIRES_LIVE_INSPECTION",
            "seo_tab": "REQUIRES_LIVE_INSPECTION",
            "seo_url_input": "REQUIRES_LIVE_INSPECTION",
            "links_tab": "REQUIRES_LIVE_INSPECTION",
            "manufacturer_input": "REQUIRES_LIVE_INSPECTION",
            "category_input": "REQUIRES_LIVE_INSPECTION",
            "filter_input": "REQUIRES_LIVE_INSPECTION",
            "add_attribute_button_key5": "REQUIRES_LIVE_INSPECTION",
            "attribute_name_input_key5": "REQUIRES_LIVE_INSPECTION",
        }
        defaults.update(data)
        for field_name, value in defaults.items():
            if field_name in self.__dataclass_fields__:
                object.__setattr__(self, field_name, value)

        if "attribute_name_input" not in data and "attribute_name_input_key1" in data:
            object.__setattr__(self, "attribute_name_input",
                               data["attribute_name_input_key1"])
        if "add_attribute_button" not in data and "add_attribute_button_key1" in data:
            object.__setattr__(self, "add_attribute_button",
                               data["add_attribute_button_key1"])
        if "attribute_text_input_key1" not in data and "attribute_text_input_key1" in data:
            object.__setattr__(self, "attribute_text_input_key1",
                               data["attribute_text_input_key1"])

        if "attribute_autocomplete_option_key1" not in data and "attribute_autocomplete_option_key1" in data:
            object.__setattr__(self, "attribute_autocomplete_option_key1",
                               data["attribute_autocomplete_option_key1"])


def load_selectors() -> OpenCartSelectors:
    path = Path(settings.selectors_file)
    if not path.exists():
        return OpenCartSelectors()
    data = json.loads(path.read_text(encoding="utf-8"))
    return OpenCartSelectors(**data)


SELECTORS = load_selectors()
