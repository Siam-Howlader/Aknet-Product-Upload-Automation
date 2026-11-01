from app.automation.products import OpenCartProductService
from app.automation.selectors import OpenCartSelectors, load_selectors


def test_selectors_load_default_values() -> None:
    selectors = load_selectors()
    assert "route=catalog/product" in selectors.products_link


def test_generated_keys_are_uploaded_before_specifications() -> None:
    rows = OpenCartProductService._attribute_rows(
        {"Weight": "3.87 kg", "Warranty": "2 years", "Screen Size": "24 inches"},
        {"Key1": "Weight is 3.87 kg.", "Key2": "Warranty is 2 years."},
    )

    assert rows == [
        ("Key1", "Weight is 3.87 kg."),
        ("Key2", "Warranty is 2 years."),
        ("Weight", "3.87 kg"),
        ("Warranty", "2 years"),
        ("Screen Size", "24 inches"),
    ]


def test_specifications_are_used_when_generated_keys_are_missing() -> None:
    rows = OpenCartProductService._attribute_rows(
        {"Weight": "3.87 kg"},
        {},
    )

    assert rows == [("Weight", "3.87 kg")]


def test_redundant_key_feature_specifications_are_not_uploaded() -> None:
    rows = OpenCartProductService._attribute_rows(
        {
            "Key Feature 1 Something >": "Already represented by Key1",
            "Key Feature 2 Something >": "Already represented by Key2",
            "Brand": "Example",
        },
        {"Key1": "First feature", "Key2": "Second feature"},
    )

    assert rows == [
        ("Key1", "First feature"),
        ("Key2", "Second feature"),
        ("Brand", "Example"),
    ]


def test_generated_key_attributes_are_not_added_to_description_features() -> None:
    description = OpenCartProductService._description_with_key_features(
        "<p>Monitor description.</p>",
        {"Key1": "Weight is 3.87 kg.", "Key2": "Warranty is 2 years."},
    )

    assert description == "<p>Monitor description.</p>"


def test_attribute_verification_normalizes_browser_text() -> None:
    assert OpenCartProductService._normalize_attribute_name(
        " USB&nbsp;Type-C ") == "usb type-c"
    assert OpenCartProductService._normalize_attribute_value(
        "Weight   is 5.96 kg") == "Weight is 5.96 kg"
    assert OpenCartProductService._normalize_attribute_value(
        "Line one\r\nLine   two") == "Line one\nLine two"


def test_attribute_name_selects_first_visible_autocomplete_option() -> None:
    import asyncio

    service = OpenCartProductService(OpenCartSelectors())

    class DummyAttributeInput:
        async def fill(self, value: str) -> None:
            self.value = value

        async def dispatch_event(self, event_name: str) -> None:
            pass

    class DummyOption:
        def __init__(self) -> None:
            self.clicked = False

        async def is_visible(self) -> bool:
            return True

        async def click(self) -> None:
            self.clicked = True

    class DummyLocator:
        def __init__(self, option: DummyOption | None) -> None:
            self.option = option

        async def count(self) -> int:
            return 1 if self.option else 0

        def nth(self, index: int) -> "DummyLocator":
            return self

        @property
        def first(self) -> "DummyLocator":
            return self

        async def wait_for(self, state: str, timeout: int) -> None:
            if not self.option:
                raise TimeoutError

        def locator(self, selector: str) -> "DummyLocator":
            return self

        async def click(self) -> None:
            await self.option.click()

    class DummyPage:
        def __init__(self, option: DummyOption) -> None:
            self.option = option

        def locator(self, selector: str) -> DummyLocator:
            return DummyLocator(
                self.option if "dropdown-menu" in selector else None)

    async def run() -> None:
        option = DummyOption()
        await service._apply_attribute_name(
            DummyPage(option),
            DummyAttributeInput(),
            "Brand",
            "",
        )
        assert option.clicked

    asyncio.run(run())
