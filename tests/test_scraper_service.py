import pytest

from app.scraper import specification_scraper
from app.ai.specifications import select_key_attributes
from app.scraper.specification_scraper import (
    SpecificationScrapingError,
    extract_product_description,
    extract_specifications,
    search_globalbrand,
    scrape_product_specifications,
)


class FakeResponse:
    def __init__(self, text: str, status_code: int = 200) -> None:
        self.text = text
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise specification_scraper.requests.HTTPError(
                str(self.status_code))


def test_source_result_requires_a_close_product_match() -> None:
    html = """
        <div class="product-thumb">
            <a href="/right"><img src="product.jpg"></a>
            <a href="/wrong">Unrelated Keyboard</a>
            <a href="/right">ADATA SU650 512GB SSD</a>
        </div>
    """
    source = specification_scraper.SOURCES[0]
    assert specification_scraper._best_product_result(
        html, "ADATA SU650 512GB SSD", source)[0].endswith("/right")


def test_extract_specifications_supports_tables_definition_lists_and_lists() -> None:
    html = """
    <div id="tab-specification">
      <table class="table-bordered">
        <tr><th>Brand</th><td>ADATA</td></tr>
        <tr><td>Capacity</td><td>1 TB</td></tr>
      </table>
      <dl><dt>Interface</dt><dd>USB-C</dd></dl>
      <ul><li>Form Factor: Portable SSD</li></ul>
    </div>
    """
    assert extract_specifications(html) == {
        "Brand": "ADATA",
        "Capacity": "1 TB",
        "Interface": "USB-C",
        "Form Factor": "Portable SSD",
    }


def test_extract_specifications_supports_nested_retailer_attribute_rows() -> None:
    html = """
    <section class="product-specification">
      <div class="row">
        <div class="attribute-name">Brand</div>
        <div class="attribute-value">UGREEN</div>
      </div>
      <div class="specification-row">
        <span class="label">Cable Length</span>
        <span class="value">1 m</span>
      </div>
      <div class="feature-item">
        <strong>Output Power:</strong> 240 W
      </div>
    </section>
    """
    assert extract_specifications(html) == {
        "Brand": "UGREEN",
        "Cable Length": "1 m",
        "Output Power": "240 W",
    }


def test_extract_specifications_reads_product_additional_properties_from_json_ld() -> None:
    html = """
    <script type="application/ld+json">
    {
      "@context": "https://schema.org",
      "@type": "Product",
      "additionalProperty": [
        {"@type": "PropertyValue", "name": "Connector", "value": "USB-C"},
        {"@type": "PropertyValue", "name": "Cable Length", "value": "1 m"}
      ]
    }
    </script>
    """
    assert extract_specifications(html) == {
        "Connector": "USB-C",
        "Cable Length": "1 m",
    }


def test_extract_specifications_reads_bold_labeled_key_features() -> None:
    html = """
    <div class="product-features">
      <ul>
        <li><strong>Power:</strong> 240 W</li>
        <li><strong>Cable Length:</strong> 1 m</li>
      </ul>
    </div>
    """
    assert extract_specifications(html) == {
        "Power": "240 W",
        "Cable Length": "1 m",
    }


def test_extract_specifications_normalizes_retailer_key_feature_labels() -> None:
    html = """
    <section class="product-specification">
      <div class="attribute-row">
        <span class="label">attr - Key Feature 1 &gt;</span>
        <span class="value">Super-fast charging up to 240 W</span>
      </div>
      <div class="attribute-row">
        <span class="label">attr -Key Feature 2 &gt;</span>
        <span class="value">Smart LED display</span>
      </div>
    </section>
    """
    assert extract_specifications(html) == {
        "Key1": "Super-fast charging up to 240 W",
        "Key2": "Smart LED display",
    }


def test_extract_specifications_reads_unlabeled_feature_lists() -> None:
    html = """
    <section class="product-key-features">
      <ul>
        <li>Super-fast charging up to 240 W</li>
        <li>Smart LED display</li>
        <li>Data transfer support</li>
      </ul>
    </section>
    """
    assert extract_specifications(html) == {
        "Key1": "Super-fast charging up to 240 W",
        "Key2": "Smart LED display",
        "Key3": "Data transfer support",
    }


def test_extract_specifications_reads_star_tech_key_features_section() -> None:
    html = """
    <div class="short-description">
      <h2>Key Features</h2>
      <ul>
        <li id="mpn">MPN: 65866</li>
        <li>Model: L530</li>
        <li>Data Transfer Rate: Up to 480 Mbps, PD 3.1 Output: Up to 240W</li>
        <li>Battery Protection, Overvoltage Protection</li>
        <li>Cable Length: 1 Meter, Power Delivery Fast Charging</li>
        <li>Aluminum Shell and Nylon Braided Cable, Digital Display</li>
        <li class="view-more">View More Info</li>
      </ul>
    </div>
    """
    assert extract_specifications(html) == {
        "MPN": "65866",
        "Model": "L530",
        "Data Transfer Rate": "Up to 480 Mbps, PD 3.1 Output: Up to 240W",
        "Key1": "Battery Protection, Overvoltage Protection",
        "Cable Length": "1 Meter, Power Delivery Fast Charging",
        "Key2": "Aluminum Shell and Nylon Braided Cable, Digital Display",
    }


def test_extract_specifications_splits_embedded_additional_info_fields() -> None:
    html = """
    <table class="specification">
      <tr>
        <td>Additional Info</td>
        <td>Model / SKU: 65868 (L530) Length: 1 m
            Connector Type: USB-C to USB-C
            Maximum Power Delivery: Up to 240 W
            Data Speed: Up to 480 Mbps
            Cable Material: Reinforced braided nylon</td>
      </tr>
    </table>
    """
    specifications = extract_specifications(html)

    assert specifications["Cable Length"] == "1 m"
    assert specifications["Connector"] == "USB-C to USB-C"
    assert specifications["Output Power"] == "Up to 240 W"
    assert specifications["Data Rate"] == "Up to 480 Mbps"
    assert specifications["Material"] == "Reinforced braided nylon"


def test_extract_specifications_skips_unstructured_page_sections() -> None:
    html = """
    <section class="product-features">
      <p>Questions Reviews Description Long page content with unrelated
         information and a colon: which must not be treated as a specification.</p>
      <div class="feature-item"><strong>Output Power:</strong> 240 W</div>
    </section>
    """
    assert extract_specifications(html) == {"Output Power": "240 W"}


def test_extract_product_description_uses_description_block_only() -> None:
    html = """
        <div class="product_extra-243">
            <span class="title">Description:</span>
            <div class="block-content">
                <h2>Product heading</h2>
                <p>Main product description.</p>
            </div>
        </div>
        <div class="product_extra-311"><span class="title">Specification:</span>
            <p>Brand: Example</p>
        </div>
        """
    description = extract_product_description(html)
    assert "Main product description." in description
    assert "Brand: Example" not in description


def test_scraper_keeps_specifications_when_description_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    specifications = {"Brand": "ADATA", "Capacity": "1 TB"}
    monkeypatch.setattr(
        specification_scraper.requests,
        "get",
        lambda url, **kwargs: FakeResponse("<html><body>No description</body></html>"),
    )

    result = specification_scraper._search_source_content(
        lambda product_name, timeout: ("https://example.com/product", specifications),
        "ADATA SU650 SSD",
        1.0,
    )

    assert result == ("", specifications)


def test_content_search_stops_at_first_product_even_without_description(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    specifications = {"Brand": "ADATA"}
    searched: list[str] = []

    def fake_search(source_search, product_name, timeout):
        searched.append(source_search.__name__)
        return "", specifications

    monkeypatch.setattr(
        specification_scraper,
        "_search_source_content",
        fake_search,
    )

    assert specification_scraper.scrape_product_content("ADATA SU650 SSD") == (
        "",
        specifications,
    )
    assert searched == ["search_globalbrand"]


def test_content_search_continues_after_global_brand_miss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    searched: list[str] = []
    specifications = {"Brand": "ADATA"}

    def fake_search(source_search, product_name, timeout):
        searched.append(source_search.__name__)
        if source_search is specification_scraper.search_startech:
            return "<p>Product description.</p>", specifications
        return None

    monkeypatch.setattr(
        specification_scraper,
        "_search_source_content",
        fake_search,
    )

    assert specification_scraper.scrape_product_content("ADATA SU650 SSD") == (
        "<p>Product description.</p>",
        specifications,
    )
    assert searched == ["search_globalbrand", "search_startech"]


def test_content_search_preserves_failure_when_no_retailer_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    searched: list[str] = []

    def fake_search(source_search, product_name, timeout):
        searched.append(source_search.__name__)
        return None

    monkeypatch.setattr(
        specification_scraper,
        "_search_source_content",
        fake_search,
    )

    with pytest.raises(
        SpecificationScrapingError,
        match="All product sources failed",
    ):
        specification_scraper.scrape_product_content("Unknown Product")

    assert searched == ["search_globalbrand", "search_startech", "search_ryans"]


@pytest.mark.parametrize(
    ("first_result", "expected_searches"),
    [
        (("https://globalbrand.test/product", {"Brand": "ADATA"}), ["globalbrand"]),
        (None, ["globalbrand", "startech"]),
    ],
)
def test_specification_search_stops_at_first_successful_retailer(
    monkeypatch: pytest.MonkeyPatch,
    first_result,
    expected_searches: list[str],
) -> None:
    searched: list[str] = []

    def search_globalbrand(product_name: str, timeout: float):
        searched.append("globalbrand")
        return first_result

    def search_startech(product_name: str, timeout: float):
        searched.append("startech")
        return ("https://startech.test/product", {"Brand": "ADATA"})

    def search_ryans(product_name: str, timeout: float):
        searched.append("ryans")
        return ("https://ryans.test/product", {"Brand": "ADATA"})

    monkeypatch.setattr(
        specification_scraper, "search_globalbrand", search_globalbrand)
    monkeypatch.setattr(specification_scraper, "search_startech", search_startech)
    monkeypatch.setattr(specification_scraper, "search_ryans", search_ryans)

    result = specification_scraper.scrape_product_specifications(
        "ADATA SU650 SSD")

    assert result == {"Brand": "ADATA"}
    assert searched == expected_searches


def test_specification_search_continues_after_global_brand_miss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    searched: list[str] = []

    def global_brand_miss(product_name: str, timeout: float):
        searched.append("globalbrand")
        return None

    def startech_match(product_name: str, timeout: float):
        searched.append("startech")
        return ("https://startech.test/product", {"Brand": "ADATA"})

    def ryans_should_not_run(product_name: str, timeout: float):
        searched.append("ryans")
        return ("https://ryans.test/product", {"Brand": "ADATA"})

    monkeypatch.setattr(
        specification_scraper, "search_globalbrand", global_brand_miss)
    monkeypatch.setattr(
        specification_scraper, "search_startech", startech_match)
    monkeypatch.setattr(
        specification_scraper, "search_ryans", ryans_should_not_run)

    result = specification_scraper.scrape_product_specifications_with_source(
        "ADATA SU650 SSD")

    assert result == ("https://startech.test/product", {"Brand": "ADATA"})
    assert searched == ["globalbrand", "startech"]


def test_specification_search_preserves_failure_when_no_retailer_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    searched: list[str] = []

    def retailer_miss(name: str):
        def search(product_name: str, timeout: float):
            searched.append(name)
            return None
        return search

    monkeypatch.setattr(
        specification_scraper, "search_globalbrand", retailer_miss("globalbrand"))
    monkeypatch.setattr(
        specification_scraper, "search_startech", retailer_miss("startech"))
    monkeypatch.setattr(
        specification_scraper, "search_ryans", retailer_miss("ryans"))

    with pytest.raises(
        SpecificationScrapingError,
        match="All specification sources failed",
    ):
        specification_scraper.scrape_product_specifications("Unknown Product")

    assert searched == ["globalbrand", "startech", "ryans"]


def test_scraper_uses_global_brand_first(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = iter([
        FakeResponse(
            '<div class="product-thumb"><a href="/product">ADATA SU650 SSD</a></div>'),
        FakeResponse(
            '<table class="specification"><tr><td>Brand</td><td>ADATA</td></tr></table>'),
    ])
    calls: list[str] = []

    def fake_get(url: str, **kwargs):
        calls.append(url)
        return next(responses)

    monkeypatch.setattr(specification_scraper.requests, "get", fake_get)
    assert search_globalbrand("ADATA SU650 SSD") == (
        "https://www.globalbrand.com.bd/product", {"Brand": "ADATA"})
    assert calls[0].startswith(
        "https://www.globalbrand.com.bd/index.php?route=product/search")


def test_scraper_raises_when_no_specifications_are_found(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = iter([FakeResponse("<html><body>No product</body></html>")])
    monkeypatch.setattr(
        specification_scraper.requests,
        "get",
        lambda url, **kwargs: FakeResponse(
            "<html><body>No product</body></html>"),
    )
    with pytest.raises(SpecificationScrapingError, match="All specification sources failed"):
        scrape_product_specifications("Unknown Product")


def test_top_five_attributes_use_sentence_results() -> None:
    assert select_key_attributes({
        "Brand": "UGREEN",
        "Power": "100W",
        "Ports": "4",
        "Plug": "EU",
        "Technology": "GaN",
        "Extra": "ignored",
    }) == {
        "Key1": "Brand is UGREEN.",
        "Key2": "Power is 100W.",
        "Key3": "Ports is 4.",
        "Key4": "Plug is EU.",
        "Key5": "Technology is GaN.",
    }


def test_scraped_key_features_take_priority_over_specification_fallbacks() -> None:
    assert select_key_attributes(
        {"Brand": "UGREEN", "Cable Length": "1m"},
        {"Key1": "Fast charging up to 240W", "Key2": "Smart LED display"},
    ) == {
        "Key1": "Fast charging up to 240W",
        "Key2": "Smart LED display",
        "Key3": "Brand is UGREEN.",
        "Key4": "Cable Length is 1m.",
    }


def test_star_tech_skips_price_status_and_product_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = iter([
        FakeResponse(
            '<div class="p-item"><a href="/product">UGREEN Charger</a></div>'),
        FakeResponse("""<table><tr><td>Price</td><td>100</td></tr>
        <tr><td>Status</td><td>In Stock</td></tr>
        <tr><td>Product Code</td><td>X688</td></tr>
        <tr><td>Power</td><td>100W</td></tr></table>"""),
    ])
    monkeypatch.setattr(
        specification_scraper.requests,
        "get", lambda url, **kwargs: next(responses),
    )
    result = specification_scraper.search_startech("UGREEN Charger")
    assert result is not None
    assert result[1] == {"Power": "100W"}
