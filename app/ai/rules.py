import re


def normalize_csv_terms(raw_value: str) -> str:
    parts = [part.strip() for part in raw_value.split(",") if part.strip()]
    seen: set[str] = set()
    result: list[str] = []
    for part in parts:
        key = part.lower()
        if key not in seen:
            seen.add(key)
            result.append(part)
    return ", ".join(result)


def build_meta_title(product_name: str) -> str:
    return f"{product_name.strip()} Price in Bangladesh"


def validate_meta_title(product_name: str, meta_title: str) -> bool:
    expected_suffix = "Price in Bangladesh"
    return meta_title.strip().lower().endswith(expected_suffix.lower()) and product_name.lower() in meta_title.lower()


def validate_meta_description(meta_description: str) -> bool:
    text = re.sub(r"\s+", " ", meta_description).strip()
    return 80 <= len(text) <= 180


def heuristic_keywords(product_name: str) -> str:
    name = product_name.strip()
    lowered = name.lower()
    terms = [
        f"{name} price in Bangladesh",
        f"{name} BD",
        f"{name.split()[0]} price BD",
    ]
    if "mouse" in lowered:
        terms.extend(["wired mouse BD", "optical mouse Bangladesh"])
    if "keyboard" in lowered:
        terms.extend(["keyboard price BD", "computer keyboard Bangladesh"])
    return normalize_csv_terms(", ".join(terms))


def heuristic_tags(product_name: str) -> str:
    words = product_name.split()
    base_brand = words[0] if words else "Product"
    tags = [base_brand, "Computer Accessory"]
    lowered = product_name.lower()
    if "mouse" in lowered:
        tags.extend(["Wired Mouse", "Optical Mouse"])
    if "keyboard" in lowered:
        tags.append("Keyboard")
    return normalize_csv_terms(", ".join(tags))


def heuristic_model(product_name: str) -> str:
    """Return a model token from the name, or blank when none is identifiable."""
    for token in product_name.split():
        cleaned = token.strip("(),[]{}")
        if any(char.isdigit() for char in cleaned) and ("-" in cleaned or "/" in cleaned):
            return cleaned[:64]
    return ""
