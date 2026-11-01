import re
from collections import defaultdict
from pathlib import Path

from app.ai.attributes import load_attribute_names


PLACEHOLDER_VALUES = {
    "", "-", "--", "n/a", "na", "none", "null", "unknown",
    "not available", "not applicable", "not specified", "unavailable",
    "cannot determine",
}

SPECIFICATION_ALIASES = {
    "data transfer rate": "Data Rate",
}


def normalize_specification_value(value: str) -> str:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    normalized = "\n".join(
        " ".join(line.split()) for line in normalized.split("\n")
    ).strip()
    unit_pattern = re.compile(
        r"(?P<number>\d+(?:\.\d+)?)\s*(?P<unit>gb|tb|mb|kb|mhz|ghz|khz|mah|ah|mm|cm|m|w|v|a|hz|%)\b",
        re.IGNORECASE,
    )

    def join_unit(match: re.Match[str]) -> str:
        unit = match.group("unit")
        canonical_units = {
            "gb": "GB", "tb": "TB", "mb": "MB", "kb": "KB",
            "mhz": "MHz", "ghz": "GHz", "khz": "kHz",
            "mah": "mAh", "ah": "Ah", "mm": "mm", "cm": "cm",
            "m": "m", "w": "W", "v": "V", "a": "A", "hz": "Hz",
            "%": "%",
        }
        return f"{match.group('number')}{canonical_units[unit.casefold()]}"

    return unit_pattern.sub(join_unit, normalized)


def is_usable_specification_value(value: str) -> bool:
    normalized = normalize_specification_value(value)
    lowered = normalized.casefold()
    return bool(normalized) and lowered not in PLACEHOLDER_VALUES


def _semantic_key(name: str) -> str:
    key = re.sub(r"[^a-z0-9]+", " ", name.casefold()).strip()
    aliases = {
        "dimension": "dimension",
        "dimensions": "dimension",
        "storage": "capacity",
        "storage capacity": "capacity",
    }
    return aliases.get(key, key)


def process_specifications(
    specifications: dict[str, str],
    catalog_path: Path | None = None,
    product_name: str = "",
) -> dict[str, str]:
    catalog = load_attribute_names(
        catalog_path) if catalog_path else load_attribute_names()
    canonical_catalog = {name.casefold(): name for name in catalog}
    candidates: dict[str, list[tuple[str, str]]] = defaultdict(list)

    for raw_name, raw_value in specifications.items():
        if not isinstance(raw_name, str) or not isinstance(raw_value, str):
            continue
        clean_name = " ".join(raw_name.split()).strip()
        if not clean_name or not is_usable_specification_value(raw_value):
            continue
        canonical_name = canonical_catalog.get(clean_name.casefold())
        canonical_name = canonical_name or SPECIFICATION_ALIASES.get(
            clean_name.casefold())
        canonical_name = canonical_name or clean_name
        value = normalize_specification_value(raw_value)
        if canonical_name == "Data Rate":
            output_match = re.search(
                r",?\s*Output:\s*(.+)$", value, re.IGNORECASE)
            if output_match:
                value = value[:output_match.start()].rstrip(" ,;")
                output_value = normalize_specification_value(
                    output_match.group(1))
                candidates[_semantic_key("Output Power")].append(
                    ("Output Power", output_value))
            rate_match = re.search(
                r"\d+(?:\.\d+)?\s*(?:kbps|mbps|gbps|tbps)\b",
                value,
                re.IGNORECASE,
            )
            if rate_match:
                value = value[:rate_match.end()].strip()
        elif canonical_name == "Cable Length":
            length_match = re.match(
                r"\d+(?:\.\d+)?\s*(?:mm|cm|m|meters?|ft|feet|inches?|in)\b",
                value,
                re.IGNORECASE,
            )
            if length_match:
                value = length_match.group(0)
        candidates[_semantic_key(canonical_name)].append(
            (canonical_name, value))

    accepted: list[tuple[int, str, str]] = []
    for entries in candidates.values():
        unique_values = {value.casefold() for _, value in entries}
        if len(unique_values) > 1:
            continue
        canonical_name = entries[0][0]
        value = entries[0][1]
        accepted.append((
            specification_quality_score(canonical_name, value, product_name),
            canonical_name,
            value,
        ))

    result: dict[str, str] = {}
    for _, canonical_name, value in sorted(accepted, reverse=True):
        result[canonical_name] = value
    return result


def process_mave_specifications(
    specifications: dict[str, str],
    product_name: str = "",
) -> dict[str, str]:
    """Process MAVE-driven specifications without catalog whitelist.

    MAVE determines relevant attributes. This processor:
    - Normalizes attribute names
    - Validates values
    - Removes placeholders
    - Deduplicates semantic duplicates
    - Resolves conflicts
    - Ranks by quality/relevance
    """
    candidates: dict[str, list[tuple[str, str]]] = defaultdict(list)

    for raw_name, raw_value in specifications.items():
        if not isinstance(raw_name, str) or not isinstance(raw_value, str):
            continue
        clean_name = " ".join(raw_name.split()).strip()
        if not clean_name or not is_usable_specification_value(raw_value):
            continue
        value = normalize_specification_value(raw_value)
        canonical_name = _normalize_attribute_name(clean_name)
        candidates[_semantic_key(canonical_name)].append(
            (canonical_name, value))

    accepted: list[tuple[int, str, str]] = []
    for entries in candidates.values():
        unique_values = {value.casefold() for _, value in entries}
        if len(unique_values) > 1:
            continue
        canonical_name = entries[0][0]
        value = entries[0][1]
        accepted.append((
            specification_quality_score(canonical_name, value, product_name),
            canonical_name,
            value,
        ))

    result: dict[str, str] = {}
    for _, canonical_name, value in sorted(accepted, reverse=True):
        result[canonical_name] = value
    return result


def select_key_attributes(
    specifications: dict[str, str],
    scraped_key_features: dict[str, str] | None = None,
) -> dict[str, str]:
    """Prioritize scraped key features, then fill remaining slots from specs."""
    selected: dict[str, str] = {}
    for index in range(1, 6):
        value = (scraped_key_features or {}).get(f"Key{index}", "").strip()
        if value:
            selected[f"Key{index}"] = value

    for name, value in specifications.items():
        if len(selected) == 5:
            break
        if not value or name.casefold().startswith("key"):
            continue
        next_index = next(
            index for index in range(1, 6)
            if f"Key{index}" not in selected
        )
        selected[f"Key{next_index}"] = f"{name} is {value}."
    return selected


def _normalize_attribute_name(name: str) -> str:
    """Normalize attribute name: title case, single spaces."""
    return " ".join(name.split()).title()


def specification_quality_score(name: str, value: str, product_name: str = "") -> int:
    score = 0
    if name.casefold() in product_name.casefold():
        score += 3
    if re.search(r"\d", value):
        score += 2
    if re.search(r"[a-zA-Z]", value):
        score += 1
    if len(value) <= 120:
        score += 1
    return score
