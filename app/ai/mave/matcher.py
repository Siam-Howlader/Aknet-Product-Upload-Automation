import re

from app.ai.mave.repository import MaveRepository


ALIASES = {
    "mouse": "gaming mouse",
    "earbuds": "earphones",
    "tws": "earphones",
    "solid state drive": "ssd",
}


def detect_category(product_name: str, categories: list[str]) -> str | None:
    text = _normalize(product_name)
    for category in categories:
        normalized = _normalize(category)
        if normalized and normalized in text:
            return category
    for alias, category in ALIASES.items():
        if alias in text:
            for candidate in categories:
                if _normalize(candidate) == category:
                    return candidate
    return None


def get_catalog_candidates(
    product_name: str,
    repository: MaveRepository,
    limit: int = 30,
) -> tuple[str | None, list[str]]:
    """Get MAVE-identified candidate attributes for a product.

    Returns raw MAVE attributes without restriction to catalog.
    Normalizes names for consistency but preserves MAVE-identified attributes
    even if not in attributes_extracted.txt.
    """
    category = detect_category(product_name, repository.get_categories())
    if not category:
        return None, []
    candidates: list[str] = []
    seen_normalized: set[str] = set()
    for name in repository.get_relevant_attributes(category, limit * 2):
        clean = " ".join(name.split()).strip()
        if not clean:
            continue
        normalized = clean.casefold()
        if normalized in seen_normalized:
            continue
        seen_normalized.add(normalized)
        canonical = _normalize_attribute_name(clean)
        if canonical not in candidates:
            candidates.append(canonical)
        if len(candidates) == limit:
            break
    return category, candidates


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _normalize_attribute_name(name: str) -> str:
    """Normalize attribute name to title case with single spaces."""
    return " ".join(name.split()).title()
