import json

import pytest

from app.ai import generator as generator_module
from app.ai.client import (
    OllamaProvider,
    OpenAICompatibleProvider,
)
from app.ai.generator import AIGenerationError, AIContentGenerator
from app.ai.attributes import canonicalize_attributes
from app.ai.models import ProductContent, ProductContentRequest
from app.ai.prompts import build_user_prompt
from app.scraper.specification_scraper import SpecificationScrapingError
from app.ai.specifications import (
    normalize_specification_value,
    process_specifications,
    process_mave_specifications,
)
from app.ai.web_sources import filter_specifications


class StubProvider:
    def __init__(self, should_fail: bool = False) -> None:
        self.should_fail = should_fail

    def generate(self, *, system_prompt: str, user_prompt: str) -> str:
        if self.should_fail:
            raise RuntimeError("provider failure")
        return (
            "<p>Reliable wired mouse for daily use in Bangladesh market.</p>"
            "<p>Order from AKNET Innovations Ltd.</p>"
        )


class RecordingProvider:
    def __init__(self, description: str) -> None:
        self.description = description
        self.user_prompts: list[str] = []

    def generate(self, *, system_prompt: str, user_prompt: str) -> str:
        self.user_prompts.append(user_prompt)
        return self.description


def test_ollama_provider_requests_plain_description_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_payload: dict = {}
    generated = "A wired optical mouse for the product details supplied."

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "message": {"content": generated},
                "done_reason": "stop",
            }

    class FakeClient:
        def __init__(self, timeout: float) -> None:
            pass

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def post(self, url: str, json: dict) -> FakeResponse:
            request_payload.update(json)
            return FakeResponse()

    monkeypatch.setattr("app.ai.client.httpx.Client", FakeClient)

    description = OllamaProvider(
        base_url="http://localhost:11434",
        model="test",
        temperature=0.35,
        num_ctx=12288,
        num_predict=1800,
    ).generate(
        system_prompt="system",
        user_prompt="user",
    )

    assert request_payload["options"]["num_ctx"] == 12288
    assert request_payload["options"]["num_predict"] == 1800
    assert request_payload["options"]["temperature"] == 0.35
    assert "format" not in request_payload
    assert description == generated


def test_openai_compatible_provider_uses_description_only_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_payload: dict = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "choices": [{
                    "message": {
                        "content": json.dumps({
                            "description": (
                                "A wired optical mouse based on the supplied "
                                "product information."
                            ),
                        }),
                    },
                }],
            }

    class FakeClient:
        def __init__(self, timeout: float) -> None:
            pass

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def post(self, url: str, headers: dict, json: dict) -> FakeResponse:
            request_payload.update(json)
            return FakeResponse()

    monkeypatch.setattr("app.ai.client.httpx.Client", FakeClient)
    content = OpenAICompatibleProvider(
        base_url="http://localhost:1234/v1",
        api_key="test",
        model="test",
    ).generate(system_prompt="system", user_prompt="facts")

    schema = request_payload["response_format"]["json_schema"]["schema"]
    assert schema["required"] == ["description"]
    assert set(schema["properties"]) == {"description"}
    assert content.startswith("A wired optical mouse")


def test_generator_configures_ollama_from_environment_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(generator_module.settings, "ai_provider", "ollama")
    monkeypatch.setattr(generator_module.settings, "ai_model", "qwen2.5:14b")
    monkeypatch.setattr(generator_module.settings, "ai_base_url", "http://localhost:11434")
    monkeypatch.setattr(generator_module.settings, "ai_temperature", 0.25)
    monkeypatch.setattr(generator_module.settings, "ollama_timeout_seconds", 420)
    monkeypatch.setattr(generator_module.settings, "ollama_num_ctx", 12288)
    monkeypatch.setattr(generator_module.settings, "ollama_num_predict", 1800)

    provider = AIContentGenerator().provider

    assert isinstance(provider, OllamaProvider)
    assert provider.model == "qwen2.5:14b"
    assert provider.timeout_seconds == 420
    assert provider.temperature == 0.25
    assert provider.num_ctx == 12288
    assert provider.num_predict == 1800


def test_ollama_provider_reports_request_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx

    class FakeClient:
        def __init__(self, timeout: float) -> None:
            pass

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def post(self, url: str, json: dict) -> None:
            raise httpx.ReadTimeout("request timed out")

    monkeypatch.setattr("app.ai.client.httpx.Client", FakeClient)

    with pytest.raises(TimeoutError, match="OLLAMA_TIMEOUT_SECONDS"):
        OllamaProvider(
            base_url="http://localhost:11434",
            model="test",
            timeout_seconds=420,
        ).generate(system_prompt="system", user_prompt="user")


def test_ollama_provider_reports_output_limit_without_retrying(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_count = 0

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "message": {
                    "content": "<p>A partially generated product description"
                },
                "done_reason": "length",
            }

    class FakeClient:
        def __init__(self, timeout: float) -> None:
            pass

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def post(self, url: str, json: dict) -> FakeResponse:
            nonlocal request_count
            request_count += 1
            return FakeResponse()

    monkeypatch.setattr("app.ai.client.httpx.Client", FakeClient)

    with pytest.raises(RuntimeError, match="OLLAMA_NUM_PREDICT"):
        OllamaProvider(base_url="http://localhost:11434", model="test").generate(
            system_prompt="system",
            user_prompt="user",
        )
    assert request_count == 1


def test_generator_uses_provider_when_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        generator_module,
        "scrape_product_content",
        lambda product_name: ("", {}),
    )
    generator = AIContentGenerator(provider=StubProvider())
    content = generator.generate(
        ProductContentRequest(
            product_name="A4TECH OP-730D 2X Click wired optical mouse"))
    assert content.product_name == "A4TECH OP-730D 2X Click wired optical mouse"
    assert content.price == 0
    assert content.key_attributes == {}


def test_generator_uses_fixed_copy_after_provider_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_description = "<p>Original retailer copy for A4TECH OP-730D.</p>"
    monkeypatch.setattr(
        generator_module,
        "scrape_product_content",
        lambda product_name: (source_description, {"Brand": "A4TECH"}),
    )
    generator = AIContentGenerator(provider=StubProvider(should_fail=True))
    content = generator.generate(
        ProductContentRequest(product_name="A4TECH OP-730D"))

    assert content.description == (
        "Buy A4TECH OP-730D from AKNET Innovations Ltd. in Bangladesh"
    )


def test_generator_sends_scraped_description_for_an_original_rewrite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_description = (
        "<p>A4TECH OP-730D is a wired optical mouse with 2X Click.</p>"
    )
    rewritten_description = (
        "<p>Designed for everyday computer use, the A4TECH OP-730D combines "
        "a wired connection, optical tracking, and 2X Click.</p>"
        "<p>Aknet Innovations Ltd. presents this product using the supplied "
        "product information.</p>"
    )
    monkeypatch.setattr(
        generator_module,
        "scrape_product_content",
        lambda product_name: (
            source_description,
            {"Brand": "A4TECH"},
        ),
    )
    provider = RecordingProvider(rewritten_description)

    content = AIContentGenerator(provider=provider).generate(
        ProductContentRequest(product_name="A4TECH OP-730D 2X Click Mouse"))

    assert source_description in provider.user_prompts[0]
    assert "SOURCE MATERIAL ONLY" in provider.user_prompts[0]
    assert "verified facts" in provider.user_prompts[0]
    assert content.description == rewritten_description
    assert content.description != source_description
    assert content.key_attributes == {"Key1": "Brand is A4TECH."}


@pytest.mark.parametrize("source_description", [None, "", "   \n\t"])
def test_generator_uses_available_facts_when_description_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    source_description: str | None,
) -> None:
    generated_description = (
        "<p>The A4TECH OP-730D is presented for everyday computer use.</p>"
        "<p>Aknet Innovations Ltd. provides this listing based on available "
        "product information.</p>"
    )
    monkeypatch.setattr(
        generator_module,
        "scrape_product_content",
        lambda product_name: (
            source_description,
            {"Brand": "A4TECH"},
        ),
    )
    provider = RecordingProvider(generated_description)

    content = AIContentGenerator(provider=provider).generate(
        ProductContentRequest(product_name="A4TECH OP-730D Optical Mouse"))

    assert "No usable retailer description was found" in provider.user_prompts[0]
    assert "A4TECH" in provider.user_prompts[0]
    assert content.description == generated_description
    assert content.key_attributes == {"Key1": "Brand is A4TECH."}


def test_generator_preserves_scraped_key_features_ahead_of_specifications(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        generator_module,
        "scrape_product_content",
        lambda product_name: (
            "",
            {
                "Key1": "Fast charging up to 240 W",
                "Key2": "Smart LED display",
                "Brand": "UGREEN",
                "Cable Length": "1 m",
            },
        ),
    )
    provider = RecordingProvider(
        "<p>UGREEN charging cable based on the verified product details.</p>"
    )

    content = AIContentGenerator(provider=provider).generate(
        ProductContentRequest(product_name="UGREEN L530 Cable"))

    assert content.key_attributes == {
        "Key1": "Fast charging up to 240 W",
        "Key2": "Smart LED display",
        "Key3": "Cable Length is 1m.",
        "Key4": "Brand is UGREEN.",
    }


def test_generator_continues_when_scraping_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_scraping(product_name: str) -> tuple[str, dict[str, str]]:
        raise SpecificationScrapingError("All product sources failed")

    monkeypatch.setattr(
        generator_module,
        "scrape_product_content",
        fail_scraping,
    )
    provider = RecordingProvider(
        "<p>A4TECH OP-730D product information.</p>"
        "<p>Aknet Innovations Ltd.</p>"
    )

    content = AIContentGenerator(provider=provider).generate(
        ProductContentRequest(product_name="A4TECH OP-730D"))

    assert "No usable retailer description was found" in provider.user_prompts[0]
    assert content.description == provider.description


def test_generator_rejects_original_description_echo_and_uses_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_description = (
        "<p>The A4TECH OP-730D is a wired optical mouse for daily use.</p>"
    )
    monkeypatch.setattr(
        generator_module,
        "scrape_product_content",
        lambda product_name: (source_description, {}),
    )
    provider = RecordingProvider(source_description)
    generator = AIContentGenerator(provider=provider)
    generator.retries = 1

    content = generator.generate(
        ProductContentRequest(product_name="A4TECH OP-730D"))

    assert len(provider.user_prompts) == 2
    assert content.description == (
        "Buy A4TECH OP-730D from AKNET Innovations Ltd. in Bangladesh"
    )


@pytest.mark.parametrize(
    "ai_description",
    [
        "",
        "Description not found",
        "No usable retailer description was found.",
    ],
)
def test_generator_uses_fixed_copy_when_ai_cannot_find_description(
    monkeypatch: pytest.MonkeyPatch,
    ai_description: str,
) -> None:
    monkeypatch.setattr(
        generator_module,
        "scrape_product_content",
        lambda product_name: ("", {}),
    )
    content = AIContentGenerator(
        provider=RecordingProvider(ai_description)
    ).generate(ProductContentRequest(product_name="A4TECH OP-730D"))

    assert content.description == (
        "Buy A4TECH OP-730D from AKNET Innovations Ltd. in Bangladesh"
    )


def test_generator_passes_structured_verified_facts_and_ignores_ai_feature_claims(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_description = "Retailer wording describing the product."
    captured: dict[str, dict] = {}

    class CapturingProvider(RecordingProvider):
        def generate(self, *, system_prompt: str, user_prompt: str) -> str:
            captured["system"] = {"prompt": system_prompt}
            captured["user"] = {"prompt": user_prompt}
            return super().generate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )

    monkeypatch.setattr(
        generator_module,
        "scrape_product_content",
        lambda product_name: (
            source_description,
            {"Brand": "A4TECH"},
        ),
    )
    provider = CapturingProvider(
        "<p>A4TECH OP-730D is described using only the verified brand fact.</p>"
        "<p>Aknet Innovations Ltd. presents the available product details.</p>"
    )

    content = AIContentGenerator(provider=provider).generate(
        ProductContentRequest(
            product_name="A4TECH OP-730D",
            price=17.25,
        ))

    prompt = captured["user"]["prompt"]
    assert '"product_name":"A4TECH OP-730D"' in prompt
    assert '"price":17.25' in prompt
    assert '"Brand":"A4TECH"' in prompt
    assert "SOURCE MATERIAL ONLY" in prompt
    assert source_description in prompt
    assert "never copy them verbatim" in captured["system"]["prompt"]
    assert "Never invent specifications" in captured["system"]["prompt"]
    assert content.product_name == "A4TECH OP-730D"
    assert content.price == 17.25
    assert content.specifications == {"Brand": "A4TECH"}
    assert content.key_attributes == {"Key1": "Brand is A4TECH."}


def test_ollama_plain_text_output_builds_complete_product_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[dict] = []
    generated_description = (
        "<p>A4TECH OP-730D optical mouse is based on the supplied "
        "product information.</p>"
    )

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "message": {"content": generated_description},
                "done_reason": "stop",
            }

    class FakeClient:
        def __init__(self, timeout: float) -> None:
            pass

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def post(self, url: str, json: dict) -> FakeResponse:
            requests.append(json)
            return FakeResponse()

    monkeypatch.setattr("app.ai.client.httpx.Client", FakeClient)
    monkeypatch.setattr(
        generator_module,
        "scrape_product_content",
        lambda product_name: ("", {"Brand": "A4TECH"}),
    )
    generator = AIContentGenerator(
        provider=OllamaProvider(
            base_url="http://localhost:11434",
            model="test",
        ))
    result = generator.generate(
        ProductContentRequest(product_name="A4TECH OP-730D"))

    assert result.description == generated_description
    assert result.product_name == "A4TECH OP-730D"
    assert result.meta_title == "A4TECH OP-730D Price in Bangladesh"
    assert result.meta_description.startswith("View A4TECH OP-730D")
    assert result.meta_keywords
    assert result.product_tags
    assert result.specifications == {"Brand": "A4TECH"}
    assert '"Brand":"A4TECH"' in requests[0]["messages"][1]["content"]
    assert '"price":0' in requests[0]["messages"][1]["content"]
    assert "format" not in requests[0]


def test_negative_specification_results_are_removed() -> None:
    assert filter_specifications({
        "Brand": "Rapoo",
        "Warranty": "Not available",
        "NFC": "No",
        "Weight": "4.1g",
    }) == {"Brand": "Rapoo", "Weight": "4.1g"}


def test_specifications_are_limited_to_the_catalog() -> None:
    assert canonicalize_attributes({
        "Brand": "Rapoo",
        "Made Up Attribute": "value",
    }) == {"Brand": "Rapoo"}


def test_prompt_requests_broad_specification_coverage() -> None:
    prompt = build_user_prompt("Rapoo T100 Bluetooth TWS Earphones")
    assert "verified facts" in prompt
    assert "Do not infer missing details" in prompt


def test_description_prompt_requests_plain_text_not_structured_json() -> None:
    from app.ai.prompts import SYSTEM_PROMPT

    assert "plain text" in SYSTEM_PROMPT
    assert "Do not return JSON" in SYSTEM_PROMPT
    assert "80 words" in SYSTEM_PROMPT


def test_product_content_does_not_treat_key_features_as_verified_specifications() -> None:
    content = ProductContent(
        product_name="Test Product",
        description="A reliable product description with enough detail for validation.",
        meta_title="Test Product Price in Bangladesh",
        meta_description="Buy this test product in Bangladesh with dependable performance for everyday use.",
        meta_keywords="test product, product Bangladesh",
        product_tags="Test Product",
        key_features="Cable Length: 3m, Material: Plastic, Connectivity: Ethernet",
    )
    assert content.specifications == {}


def test_specifications_normalize_units_without_changing_meaning() -> None:
    assert normalize_specification_value("16 GB") == "16GB"
    assert normalize_specification_value("3200 mhz") == "3200MHz"
    assert normalize_specification_value("25 x 18 x 28 mm") == "25 x 18 x 28mm"


def test_specification_names_are_case_and_whitespace_insensitive() -> None:
    assert process_specifications({"  bRaNd  ": "Rapoo"}) == {"Brand": "Rapoo"}


def test_specification_processing_rejects_placeholders_and_keeps_valid_names() -> None:
    result = process_specifications({
        "Brand": "Rapoo",
        "Warranty": "Not Specified",
        "Power Consumption": "Cannot determine",
        "Invented Field": "100W",
        "Weight": "   ",
    })
    assert result == {"Brand": "Rapoo", "Invented Field": "100W"}


def test_specification_processing_removes_duplicate_and_conflicting_aliases() -> None:
    assert process_specifications({
        "Dimension": "25 x 18 x 28 mm",
        "Dimensions": "25 x 18 x 28mm",
    }) == {"Dimension": "25 x 18 x 28mm"}
    assert process_specifications({
        "Capacity": "1TB",
        "Storage Capacity": "2TB",
    }) == {}


def test_specification_processing_maps_retailer_aliases_and_splits_combined_values() -> None:
    assert process_specifications({
        "Data Transfer Rate": "Up to 480 Mbps, PD 3.1 Output: Up to 240W",
        "Cable Length": "1 Meter, Power Delivery Fast Charging",
    }) == {
        "Output Power": "Up to 240W",
        "Data Rate": "Up to 480 Mbps",
        "Cable Length": "1 Meter",
    }


def test_more_than_twenty_valid_catalog_specifications_can_survive() -> None:
    from app.ai.attributes import load_attribute_names

    names = load_attribute_names()[:25]
    result = process_specifications({name: f"Value {index}"
                                     for index, name in enumerate(names)})
    assert len(result) == 25
