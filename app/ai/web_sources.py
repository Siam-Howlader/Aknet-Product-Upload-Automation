import html
import re
from dataclasses import dataclass
from urllib.parse import urlparse

from app.ai.attributes import load_attribute_names

import httpx


@dataclass(frozen=True)
class ProductSource:
    title: str
    url: str
    snippet: str


PREFERRED_DOMAINS = ("globalbrand.com.bd", "startech.com.bd")
NEGATIVE_SPEC_VALUES = {
    "no", "n/a", "na", "none", "not available", "not applicable",
    "unavailable", "unknown", "-", "--",
}


def search_product_sources(product_name: str, timeout_seconds: float = 4.0) -> list[ProductSource]:
    results: list[ProductSource] = []
    queries = [
        f'site:{domain} "{product_name}" specifications'
        for domain in PREFERRED_DOMAINS
    ] + [f'"{product_name}" specifications']
    for query in queries:
        results.extend(_search_query(query, timeout_seconds))
    unique: dict[str, ProductSource] = {}
    for result in results:
        unique.setdefault(result.url, result)
    ranked = sorted(
        unique.values(),
        key=lambda source: 0 if _is_preferred_domain(source.url) else 1,
    )
    enriched = [_enrich_source(source, timeout_seconds / 2)
                for source in ranked[:4]]
    return enriched


def research_attribute_values(
    product_name: str,
    sources: list[ProductSource],
    attribute_names: list[str] | None = None,
) -> tuple[list[str], dict[str, str]]:
    """Find source-supported attributes and values before asking the AI to infer anything."""
    catalog = attribute_names or load_attribute_names()
    evidence = " ".join(source.snippet for source in sources)
    normalized_evidence = re.sub(r"\s+", " ", evidence).strip()
    suitable: list[str] = []
    values: dict[str, str] = {}
    for attribute in catalog:
        escaped = re.escape(attribute)
        if not re.search(rf"(?<![\w]){escaped}(?![\w])", normalized_evidence, re.IGNORECASE):
            continue
        suitable.append(attribute)
        value = _extract_attribute_value(
            normalized_evidence, attribute, catalog)
        if value:
            values[attribute] = value

    product_terms = set(re.findall(r"[a-z0-9]+", product_name.casefold()))
    for attribute in catalog:
        if attribute not in suitable and attribute.casefold() in product_terms:
            suitable.append(attribute)
    return suitable, filter_specifications(values)


def _extract_attribute_value(text: str, attribute: str, catalog: list[str]) -> str | None:
    other_labels = "|".join(
        re.escape(item) for item in catalog if item.casefold() != attribute.casefold())
    pattern = re.compile(
        rf"{re.escape(attribute)}\s*(?:[:：\-]|is)?\s*([^|;]{{1,160}}?)(?=\s+(?:{other_labels})\s*(?:[:：\-]|is)|$)",
        re.IGNORECASE,
    )
    match = pattern.search(text)
    if not match:
        return None
    value = " ".join(match.group(1).split()).strip(" .,:;-|")
    return value if value.casefold() not in NEGATIVE_SPEC_VALUES else None


def _search_query(query: str, timeout_seconds: float) -> list[ProductSource]:
    try:
        response = httpx.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=timeout_seconds,
            follow_redirects=True,
        )
        response.raise_for_status()
    except httpx.HTTPError:
        return []

    page = html.unescape(response.text)
    pattern = re.compile(
        r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>.*?'
        r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
        flags=re.IGNORECASE | re.DOTALL,
    )
    results: list[ProductSource] = []
    for match in pattern.finditer(page):
        title = _clean_html(match.group(2))
        snippet = _clean_html(match.group(3))
        if title and snippet:
            results.append(ProductSource(
                title=title, url=match.group(1), snippet=snippet))
        if len(results) == 4:
            break
    return results


def _enrich_source(source: ProductSource, timeout_seconds: float) -> ProductSource:
    try:
        response = httpx.get(
            source.url,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=max(timeout_seconds, 2.0),
            follow_redirects=True,
        )
        response.raise_for_status()
        text = _clean_html(response.text)
        if text:
            return ProductSource(source.title, source.url, text[:12000])
    except httpx.HTTPError:
        pass
    return source


def _is_preferred_domain(url: str) -> bool:
    hostname = urlparse(url).hostname or ""
    return any(hostname == domain or hostname.endswith(f".{domain}")
               for domain in PREFERRED_DOMAINS)


def format_product_sources(sources: list[ProductSource], max_chars: int = 6000) -> str:
    lines: list[str] = []
    for source in sources:
        line = f"Source: {source.title}\nURL: {source.url}\nDetails: {source.snippet}"
        remaining = max_chars - sum(len(item) + 1 for item in lines)
        if remaining <= 0:
            break
        if len(line) > remaining:
            line = line[:remaining]
        lines.append(line)
        if len(line) < remaining:
            continue
        break
    return "\n\n".join(lines)


def filter_specifications(specifications: dict[str, str]) -> dict[str, str]:
    filtered: dict[str, str] = {}
    for name, value in specifications.items():
        clean_value = " ".join(value.split()).strip()
        if clean_value.casefold() not in NEGATIVE_SPEC_VALUES:
            filtered[name] = clean_value
    return filtered


def _clean_html(value: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", value).split())
