import asyncio
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.ai.models import ProductContent, ProductContentRequest
from app.ai.attributes import format_attribute_catalog, load_attribute_names
from app.ai.prompts import build_user_prompt
from app.automation.products import OpenCartProductService
from app.automation.selectors import OpenCartSelectors
from app.services.schemas import UploadProductRequest
from app.ai.rules import (
    build_meta_title,
    heuristic_keywords,
    heuristic_model,
    heuristic_tags,
    normalize_csv_terms,
    normalize_key_features,
    validate_meta_description,
    validate_meta_title,
)
from app.database.models import ProductJobStatus


def test_product_name_validation_accepts_trimmed_value() -> None:
    payload = ProductContentRequest(product_name="  A4TECH OP-730D  ")
    assert payload.product_name == "A4TECH OP-730D"


def test_product_name_validation_rejects_empty_string() -> None:
    try:
        ProductContentRequest(product_name="   ")
    except ValidationError:
        assert True
        return
    assert False, "ValidationError was expected for blank product name"


def test_meta_title_validation_helpers() -> None:
    product_name = "A4TECH OP-730D"
    title = build_meta_title(product_name)
    assert validate_meta_title(product_name, title)


def test_product_content_accepts_meta_title_up_to_170_characters() -> None:
    suffix = "Price in Bangladesh"
    title = f"{'T' * (170 - len(suffix))}{suffix}"
    content = {
        "product_name": "Test Product",
        "description": "A reliable product description with enough detail for validation.",
        "meta_description": "Buy this test product in Bangladesh with dependable performance for everyday use.",
        "product_tags": "Test Product",
    }

    product = ProductContent(**content, meta_title=title)
    assert len(product.meta_title) == 170

    with pytest.raises(ValidationError):
        ProductContent(**content, meta_title=f"T{title}")


def test_upload_product_request_accepts_product_tags_longer_than_255_characters() -> None:
    tags = ", ".join(f"Product tag {index}" for index in range(30))

    product = UploadProductRequest(
        product_name="Test Product",
        description="",
        meta_title="Test Product Price in Bangladesh",
        meta_description="Buy this test product in Bangladesh with dependable performance for everyday use.",
        product_tags=tags,
    )

    assert len(product.product_tags) > 255


def test_product_content_accepts_empty_description() -> None:
    product = ProductContent(
        product_name="Test Product",
        description="",
        meta_title="Test Product Price in Bangladesh",
        meta_description="Buy this test product in Bangladesh with dependable performance for everyday use.",
        product_tags="Test Product",
    )

    assert product.description == ""


def test_meta_description_validation_helpers() -> None:
    assert validate_meta_description(
        "Buy A4TECH OP-730D in Bangladesh from AKNET Innovations Ltd. for dependable daily office and home computer use."
    )


def test_keyword_generation_is_comma_separated() -> None:
    keywords = heuristic_keywords("A4TECH OP-730D wired optical mouse")
    assert "," in keywords


def test_tag_generation_is_comma_separated() -> None:
    tags = heuristic_tags("A4TECH OP-730D wired optical mouse")
    assert "Wired Mouse" in tags


def test_model_generation_extracts_exact_model_token() -> None:
    assert heuristic_model(
        "A4TECH OP-730D 2X Click wired optical mouse") == "OP-730D"


def test_csv_normalization_removes_duplicates() -> None:
    normalized = normalize_csv_terms("A4TECH, Mouse, mouse, A4TECH")
    assert normalized == "A4TECH, Mouse"


def test_key_features_require_exactly_five_items() -> None:
    from app.ai.models import ProductContent

    content = ProductContent(
        product_name="A4TECH OP-730D",
        description="<p>Reliable wired optical mouse for everyday computer use in Bangladesh market.</p><p>Order from AKNET Innovations Ltd.</p>",
        meta_title="A4TECH OP-730D Price in Bangladesh",
        meta_description="Buy A4TECH OP-730D in Bangladesh from AKNET Innovations Ltd. for dependable everyday computer use and practical office performance.",
        meta_keywords="A4TECH OP-730D price in Bangladesh, wired mouse BD",
        product_tags="A4TECH Mouse, Wired Mouse",
        key_features="Wired connection, Optical tracking, Comfortable control, Everyday use, Reliable design",
    )
    assert len(content.key_features.split(", ")) == 5


def test_product_content_normalizes_specifications() -> None:
    content = ProductContent(
        product_name="A4TECH OP-730D",
        description="<p>Reliable wired optical mouse for everyday computer use in Bangladesh market.</p><p>Order from AKNET Innovations Ltd.</p>",
        meta_title="A4TECH OP-730D Price in Bangladesh",
        meta_description="Buy A4TECH OP-730D in Bangladesh from AKNET Innovations Ltd. for dependable everyday computer use and practical office performance.",
        meta_keywords="A4TECH OP-730D price in Bangladesh, wired mouse BD",
        product_tags="A4TECH Mouse, Wired Mouse",
        specifications={"  Brand  ": "  A4TECH  ", "Empty": "   "},
    )
    assert content.specifications == {"Brand": "A4TECH"}


def test_product_content_discards_oversized_meta_keywords() -> None:
    content = ProductContent(
        product_name="Test Product",
        description="A reliable product description with enough detail for validation.",
        meta_title="Test Product Price in Bangladesh",
        meta_description="Buy this test product in Bangladesh with dependable performance for everyday use.",
        meta_keywords="x" * 256,
        product_tags="Test Product",
    )

    assert content.meta_keywords == ""


def test_product_content_accepts_manufacturer_categories_and_filters() -> None:
    content = ProductContent(
        product_name="A4TECH OP-730D",
        description="<p>Reliable wired optical mouse for everyday computer use in Bangladesh market.</p><p>Order from AKNET Innovations Ltd.</p>",
        meta_title="A4TECH OP-730D Price in Bangladesh",
        meta_description="Buy A4TECH OP-730D in Bangladesh from AKNET Innovations Ltd. for dependable everyday computer use and practical office performance.",
        meta_keywords="A4TECH OP-730D price in Bangladesh, wired mouse BD",
        product_tags="A4TECH Mouse, Wired Mouse",
        key_features="Comfortable grip, Wired connection, Accurate tracking, Everyday use, Reliable design",
        manufacturer=" Asus ",
        categories=" Laptop, Gaming Laptop, ASUS ",
        filters=" RGB, Wireless, Ergonomic ",
    )
    assert content.manufacturer == "Asus"
    assert content.categories == "Laptop, Gaming Laptop, ASUS"
    assert content.filters == "RGB, Wireless, Ergonomic"


def test_attribute_catalog_is_loaded_but_not_sent_to_generation_prompt() -> None:
    catalog_path = Path(__file__).parents[1] / "attributes_extracted.txt"
    names = load_attribute_names(catalog_path)
    assert "Brand" in names
    assert "Battery Life" in names
    assert "- Brand" in format_attribute_catalog(catalog_path)
    prompt = build_user_prompt("Rapoo T100")
    assert "attribute catalog" not in prompt
    assert "Rapoo T100" in prompt


def test_key_features_reject_wrong_item_count() -> None:
    from pydantic import ValidationError
    from app.ai.models import ProductContent

    try:
        ProductContent(
            product_name="A4TECH OP-730D",
            description="<p>Reliable wired optical mouse for everyday computer use in Bangladesh market.</p><p>Order from AKNET Innovations Ltd.</p>",
            meta_title="A4TECH OP-730D Price in Bangladesh",
            meta_description="Buy A4TECH OP-730D in Bangladesh from AKNET Innovations Ltd. for dependable everyday computer use and practical office performance.",
            meta_keywords="A4TECH OP-730D price in Bangladesh, wired mouse BD",
            product_tags="A4TECH Mouse, Wired Mouse",
            key_features="Only one feature",
        )
    except ValidationError:
        return
    assert False, "ValidationError was expected for fewer than five key features"


def test_key_features_preserve_numeric_commas_and_add_labels() -> None:
    features = normalize_key_features(
        "Capacity: 65,000mAh, 130W Charging, Multi-Protocol Support, Compact Design, Safety Protection"
    )
    assert features.startswith("Key1: Capacity: 65,000mAh")
    assert len(features.split(", ")) == 5


def test_key_features_support_space_variants_between_key_labels() -> None:
    features = normalize_key_features(
        "Key 1: First feature, Key2: Second feature, Key 3: Third feature, Key4: Fourth feature, Key 5: Fifth feature"
    )
    assert features.startswith("Key1: First feature")
    assert "Key2: Second feature" in features
    assert "Key3: Third feature" in features
    assert "Key4: Fourth feature" in features
    assert "Key5: Fifth feature" in features


def test_attribute_name_falls_back_to_direct_fill_when_autocomplete_is_missing() -> None:
    service = OpenCartProductService(OpenCartSelectors())

    class DummyAttributeInput:
        def __init__(self) -> None:
            self.value = ""

        async def input_value(self) -> str:
            return self.value

        async def fill(self, value: str) -> None:
            self.value = value

        async def dispatch_event(self, event_name: str) -> None:
            self.event_name = event_name

    class DummyPage:
        def __init__(self, input_widget: DummyAttributeInput) -> None:
            self.input_widget = input_widget

        def locator(self, selector: str):
            return self

        async def count(self):
            return 0

    async def run() -> None:
        widget = DummyAttributeInput()
        page = DummyPage(widget)
        await service._apply_attribute_name(
            page,
            widget,
            "Key1",
            "a[href=\"#\"]",
        )
        assert widget.value == "Key1"

    asyncio.run(run())


def test_status_enum_has_saved() -> None:
    assert ProductJobStatus.SAVED.value == "SAVED"
