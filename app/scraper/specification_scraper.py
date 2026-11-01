import json
import logging
import re
from dataclasses import dataclass
from urllib.parse import quote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup, Tag

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

_ADDITIONAL_INFO_ALIASES = {
    "Model / SKU": "Model",
    "Length": "Cable Length",
    "Connector Type": "Connector",
    "Maximum Power Delivery": "Output Power",
    "Data Speed": "Data Rate",
    "Chipset": "Chipset Model",
    "Cable Material": "Material",
    "Real-time Digital Display": "Display Features",
}


class SpecificationScrapingError(RuntimeError):
    """Raised when product specifications cannot be scraped."""


@dataclass(frozen=True)
class _Source:
    name: str
    search_url: str
    domain: str
    result_selectors: tuple[str, ...]


SOURCES = (
    _Source(
        "Global Brand BD",
        "https://www.globalbrand.com.bd/index.php?route=product/search&search={}",
        "www.globalbrand.com.bd",
        ("div.product-thumb a[href]", ".product-layout a[href]", "a[href]"),
    ),
    _Source(
        "Star Tech",
        "https://www.startech.com.bd/index.php?route=product/search&search={}",
        "www.startech.com.bd",
        ("div.p-item a[href]", ".p-item-inner a[href]",
         ".product-item a[href]", "a[href]"),
    ),
    _Source(
        "Ryans",
        "https://www.ryans.com/search?text={}",
        "www.ryans.com",
        (".product-card a[href]", ".product-item a[href]",
         ".p-item a[href]", "a[href]"),
    ),
)


def scrape_product_specifications(
    product_name: str,
    timeout_seconds: float = 15.0,
) -> dict[str, str]:
    """Try the supported retailers in priority order and return specifications."""
    for source_search in (
        search_globalbrand,
        search_startech,
        search_ryans,
    ):
        try:
            result = source_search(product_name, timeout_seconds)
        except SpecificationScrapingError as exc:
            logger.info("%s", exc)
            continue
        if result:
            return result[1]
    logger.error("All specification sources failed")
    raise SpecificationScrapingError("All specification sources failed")


def scrape_product_content(
    product_name: str,
    timeout_seconds: float = 15.0,
) -> tuple[str, dict[str, str]]:
    """Return the selected product page description and specifications."""
    for source_search in (search_globalbrand, search_startech, search_ryans):
        try:
            result = _search_source_content(
                source_search, product_name, timeout_seconds)
        except SpecificationScrapingError:
            continue
        if result:
            return result
    raise SpecificationScrapingError("All product sources failed")


def scrape_product_specifications_with_source(
    product_name: str,
    timeout_seconds: float = 15.0,
) -> tuple[str, dict[str, str]]:
    for source_search in (search_globalbrand, search_startech, search_ryans):
        try:
            result = source_search(product_name, timeout_seconds)
        except SpecificationScrapingError:
            continue
        if result:
            return result
    raise SpecificationScrapingError("All specification sources failed")


def search_globalbrand(product_name: str, timeout_seconds: float = 15.0) -> tuple[str, dict[str, str]] | None:
    return _search_source(SOURCES[0], product_name, timeout_seconds)


def search_startech(product_name: str, timeout_seconds: float = 15.0) -> tuple[str, dict[str, str]] | None:
    return _search_source(SOURCES[1], product_name, timeout_seconds)


def search_ryans(product_name: str, timeout_seconds: float = 15.0) -> tuple[str, dict[str, str]] | None:
    return _search_source(SOURCES[2], product_name, timeout_seconds)


def _search_source(
    source: _Source,
    product_name: str,
    timeout_seconds: float,
) -> tuple[str, dict[str, str]] | None:
    clean_name = _clean_text(product_name)
    if not clean_name:
        raise SpecificationScrapingError("Product name cannot be empty")
    logger.info("Searching %s...", source.name)
    try:
        response = requests.get(
            source.search_url.format(quote(clean_name, safe="")),
            headers={"User-Agent": USER_AGENT},
            timeout=timeout_seconds,
            allow_redirects=True,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise SpecificationScrapingError(
            f"{source.name}: no suitable product/specifications found") from exc

    product_url, title = _best_product_result(
        response.text, clean_name, source)
    if not product_url:
        logger.info("%s: no suitable product/specifications found", source.name)
        return None
    logger.info("%s product found: %s", source.name, title)
    try:
        product_response = requests.get(
            product_url,
            headers={"User-Agent": USER_AGENT},
            timeout=timeout_seconds,
            allow_redirects=True,
        )
        product_response.raise_for_status()
        specifications = extract_specifications(product_response.text)
        if source.name == "Star Tech":
            specifications = {
                name: value for name, value in specifications.items()
                if name.casefold() not in {"price", "status", "product code"}
            }
    except Exception:
        logger.info("%s: no suitable product/specifications found", source.name)
        return None
    if not specifications:
        logger.info("%s: no suitable product/specifications found", source.name)
        return None
    logger.info("Specifications found: %s", len(specifications))
    return product_url, specifications


def _search_source_content(
    source_search,
    product_name: str,
    timeout_seconds: float,
) -> tuple[str, dict[str, str]] | None:
    result = source_search(product_name, timeout_seconds)
    if not result:
        return None
    product_url, specifications = result
    try:
        response = requests.get(
            product_url,
            headers={"User-Agent": USER_AGENT},
            timeout=timeout_seconds,
            allow_redirects=True,
        )
        response.raise_for_status()
        description = extract_product_description(response.text)
    except requests.RequestException as exc:
        logger.info("Product description request failed: %s", exc)
        return "", specifications
    if not description or not description.strip():
        return "", specifications
    return description, specifications


def _best_product_result(
    html: str,
    product_name: str,
    source: _Source,
) -> tuple[str | None, str]:
    soup = BeautifulSoup(html, "html.parser")
    requested_terms = _matching_terms(product_name)
    candidates: list[tuple[float, str, str]] = []
    seen: set[str] = set()
    for selector in source.result_selectors:
        for anchor in soup.select(selector):
            href = anchor.get("href", "")
            absolute_url = urljoin(f"https://{source.domain}/", href)
            parsed = urlparse(absolute_url)
            if parsed.hostname != source.domain or absolute_url in seen:
                continue
            title = _clean_text(anchor.get_text(" ", strip=True))
            if not title:
                continue
            seen.add(absolute_url)
            container = anchor.find_parent(
                ["div", "li", "article", "section", "td"])
            context = _clean_text(container.get_text(
                " ", strip=True)) if container else title
            score = _match_score(
                requested_terms, title or context)
            if score >= 0.5:
                candidates.append((score, absolute_url, title or context))
    if not candidates:
        return None, ""
    _, url, title = max(candidates, key=lambda candidate: candidate[0])
    return url, title


def _matching_terms(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", value.casefold()))


def _match_score(requested_terms: set[str], candidate_text: str) -> float:
    candidate_terms = _matching_terms(candidate_text)
    if not requested_terms or not candidate_terms:
        return 0.0
    return len(requested_terms & candidate_terms) / len(requested_terms)


def extract_specifications(html: str) -> dict[str, str]:
    """Extract key/value specifications from common product-page structures."""
    soup = BeautifulSoup(html, "html.parser")
    result: dict[str, str] = {}
    seen_keys: set[str] = set()

    spec_nodes = _specification_nodes(soup)
    for heading in soup.find_all(re.compile(r"^h[1-6]$")):
        if _clean_text(heading.get_text(" ", strip=True)).casefold() != "key features":
            continue
        feature_list = heading.find_next_sibling("ul")
        if feature_list:
            _extract_list(feature_list, result, seen_keys)
            _extract_plain_key_features(feature_list, result, seen_keys)
    for node in spec_nodes:
        node_labels = " ".join(
            [node.get("id", ""), *node.get("class", [])]
        ).casefold()
        if "feature" in node_labels:
            _extract_plain_key_features(node, result, seen_keys)
    for node in spec_nodes:
        if node.name == "table":
            _extract_table(node, result, seen_keys)
        elif node.name == "dl":
            _extract_definition_list(node, result, seen_keys)
        else:
            _extract_list(node, result, seen_keys)
            _extract_attribute_rows(node, result, seen_keys)

    for table in soup.find_all("table"):
        _extract_table(table, result, seen_keys)
    for definition_list in soup.find_all("dl"):
        _extract_definition_list(definition_list, result, seen_keys)
    for node in soup.select(
        "[class*='specification'], [id*='specification'], "
        "[class*='technical'], [id*='technical'], [class*='feature'], "
        "[id*='feature'], [class*='detail'], [id*='detail']"
    ):
        _extract_list(node, result, seen_keys)

    _extract_json_ld_specifications(soup, result, seen_keys)
    _extract_embedded_additional_info(result, seen_keys)
    return result


def extract_product_description(html: str) -> str:
    """Extract the main product description HTML, excluding navigation and specs."""
    soup = BeautifulSoup(html, "html.parser")
    candidates = []
    for container in soup.select(
        ".product_extra, [class^='product_extra'], "
        "[class*='description'], #tab-description"
    ):
        title = _clean_text(container.select_one(".title").get_text(
            " ", strip=True)) if container.select_one(".title") else ""
        classes = " ".join(container.get("class", [])).casefold()
        if "description" in title.casefold() or "description" in classes or container.get("id") == "tab-description":
            content = container.select_one(".block-content") or container
            candidates.append(content)
    if not candidates:
        return ""
    content = candidates[0]
    for unwanted in content.select("script, style, nav, form"):
        unwanted.decompose()
    return _clean_html_fragment(content.decode_contents())


def _specification_nodes(soup: BeautifulSoup) -> list[Tag]:
    nodes: list[Tag] = []
    selectors = (
        "#tab-specification",
        "[id*='specification']",
        "[class*='specification']",
        "[class*='technical']",
        "[id*='technical']",
        "[class*='attribute']",
        "[id*='attribute']",
        "[class*='feature']",
        "[id*='feature']",
        "[class*='detail']",
        "[id*='detail']",
    )
    for node in soup.select(", ".join(selectors)):
        if node not in nodes:
            nodes.append(node)
        for table in node.find_all("table"):
            if table not in nodes:
                nodes.append(table)
        for definition_list in node.find_all("dl"):
            if definition_list not in nodes:
                nodes.append(definition_list)
    return nodes


def _extract_table(table: Tag, result: dict[str, str], seen_keys: set[str]) -> None:
    for row in table.find_all("tr"):
        cells = row.find_all(["th", "td"])
        if len(cells) < 2:
            continue
        key = _clean_text(cells[0].get_text(" ", strip=True))
        value = _clean_text(" ".join(cell.get_text(" ", strip=True)
                                     for cell in cells[1:]))
        _add_specification(result, seen_keys, key, value)


def _extract_definition_list(node: Tag, result: dict[str, str], seen_keys: set[str]) -> None:
    terms = node.find_all("dt")
    for term in terms:
        value_node = term.find_next_sibling("dd")
        if value_node:
            _add_specification(
                result,
                seen_keys,
                _clean_text(term.get_text(" ", strip=True)),
                _clean_text(value_node.get_text(" ", strip=True)),
            )


def _extract_list(node: Tag, result: dict[str, str], seen_keys: set[str]) -> None:
    for item in node.find_all("li"):
        parts = [part for part in item.stripped_strings]
        if not parts:
            continue
        item_text = " ".join(parts)
        if len(item_text) > 300:
            continue
        if ":" in item_text:
            key, value = item_text.split(":", 1)
            _add_specification(result, seen_keys, key, value)
            continue
        label = item.find(["strong", "b"])
        if label:
            key = _clean_text(label.get_text(" ", strip=True)).rstrip(":")
            value_text = _clean_text(item.get_text(" ", strip=True))
            label_text = _clean_text(label.get_text(" ", strip=True))
            value = value_text[len(label_text):].lstrip(" :-")
            _add_specification(result, seen_keys, key, value)


def _extract_plain_key_features(
    node: Tag,
    result: dict[str, str],
    seen_keys: set[str],
) -> None:
    next_index = 1
    for item in node.find_all("li"):
        value = _clean_text(item.get_text(" ", strip=True))
        classes = {name.casefold() for name in item.get("class", [])}
        if (
            not value
            or ":" in value
            or len(value) > 200
            or "view-more" in classes
        ):
            continue
        while next_index <= 5 and f"key{next_index}" in seen_keys:
            next_index += 1
        if next_index > 5:
            return
        _add_specification(
            result,
            seen_keys,
            f"Key Feature {next_index}",
            value,
        )
        next_index += 1


def _extract_attribute_rows(
    node: Tag,
    result: dict[str, str],
    seen_keys: set[str],
) -> None:
    row_selector = (
        "tr, p, [class~='row'], [class*='attribute-row'], [class*='specification-row'], "
        "[class*='spec-row'], [class*='feature-row'], "
        "[class*='attribute-item'], [class*='specification-item'], "
        "[class*='spec-item'], [class*='feature-item']"
    )
    label_selector = (
        "[class*='label'], [class*='name'], [itemprop='name']"
    )
    value_selector = (
        "[class*='value'], [class*='detail'], [itemprop='value']"
    )
    for row in node.select(row_selector):
        label_node = row.select_one(label_selector)
        value_node = row.select_one(value_selector)
        if label_node and value_node:
            _add_specification(
                result,
                seen_keys,
                _clean_text(label_node.get_text(" ", strip=True)),
                _clean_text(value_node.get_text(" ", strip=True)),
            )
            continue
        if row.name == "p" and row.find(["div", "p", "table", "ul", "li"]):
            continue
        row_text = _clean_text(row.get_text(" ", strip=True))
        if len(row_text) > 300:
            continue
        if ":" in row_text:
            key, value = row_text.split(":", 1)
            if len(key) > 60:
                continue
            _add_specification(result, seen_keys, key, value)
            continue
        cells = row.find_all(["th", "td"], recursive=False)
        if len(cells) >= 2:
            _add_specification(
                result,
                seen_keys,
                _clean_text(cells[0].get_text(" ", strip=True)),
                _clean_text(" ".join(
                    cell.get_text(" ", strip=True) for cell in cells[1:]
                )),
            )
            continue
        children = row.find_all(
            ["div", "span", "p", "dt", "dd", "strong", "b"],
            recursive=False,
        )
        if len(children) >= 2:
            _add_specification(
                result,
                seen_keys,
                _clean_text(children[0].get_text(" ", strip=True)),
                _clean_text(" ".join(
                    child.get_text(" ", strip=True) for child in children[1:]
                )),
            )


def _extract_json_ld_specifications(
    soup: BeautifulSoup,
    result: dict[str, str],
    seen_keys: set[str],
) -> None:
    def visit(value: object) -> None:
        if isinstance(value, list):
            for item in value:
                visit(item)
            return
        if not isinstance(value, dict):
            return
        properties = value.get("additionalProperty", [])
        if isinstance(properties, dict):
            properties = [properties]
        if isinstance(properties, list):
            for prop in properties:
                if not isinstance(prop, dict):
                    continue
                name = prop.get("name")
                prop_value = prop.get("value")
                if isinstance(name, str) and isinstance(prop_value, (str, int, float)):
                    _add_specification(
                        result, seen_keys, name, str(prop_value))
        for key in ("@graph", "mainEntity"):
            if key in value:
                visit(value[key])

    for script in soup.select('script[type="application/ld+json"]'):
        try:
            visit(json.loads(script.string or script.get_text()))
        except (json.JSONDecodeError, TypeError):
            logger.debug("Ignoring malformed product JSON-LD")


def _add_specification(
    result: dict[str, str],
    seen_keys: set[str],
    key: str,
    value: str,
) -> None:
    key = _clean_text(key)
    value = _clean_text(value)
    key = re.sub(r"^attr\s*[-:]\s*", "", key, flags=re.IGNORECASE)
    key = key.strip(" >:-")
    key_feature_match = re.fullmatch(
        r"key\s*feature\s*([1-5])", key, re.IGNORECASE)
    if key_feature_match:
        key = f"Key{key_feature_match.group(1)}"
    normalized_key = key.casefold()
    if key and value and normalized_key not in seen_keys:
        seen_keys.add(normalized_key)
        result[key] = value


def _extract_embedded_additional_info(
    result: dict[str, str],
    seen_keys: set[str],
) -> None:
    labels = sorted(
        _ADDITIONAL_INFO_ALIASES,
        key=len,
        reverse=True,
    )
    label_pattern = re.compile(
        r"(?<![\w])(" + "|".join(re.escape(label) for label in labels) + r")\s*:",
        re.IGNORECASE,
    )
    for name, text in list(result.items()):
        if name.casefold() != "additional info":
            continue
        matches = list(label_pattern.finditer(text))
        for index, match in enumerate(matches):
            value_start = match.end()
            value_end = (
                matches[index + 1].start()
                if index + 1 < len(matches)
                else len(text)
            )
            value = text[value_start:value_end].strip(" ,;:-")
            canonical_name = next(
                alias for alias in labels
                if alias.casefold() == match.group(1).casefold()
            )
            _add_specification(
                result,
                seen_keys,
                _ADDITIONAL_INFO_ALIASES[canonical_name],
                value,
            )


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _clean_html_fragment(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()
