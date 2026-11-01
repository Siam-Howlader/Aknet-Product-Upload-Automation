from pathlib import Path


DEFAULT_ATTRIBUTES_PATH = Path(__file__).resolve(
).parents[2] / "attributes_extracted.txt"


def load_attribute_names(path: Path = DEFAULT_ATTRIBUTES_PATH) -> list[str]:
    if not path.exists():
        return []
    names: list[str] = []
    seen: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        name = " ".join(line.split())
        key = name.casefold()
        if name and key not in seen:
            names.append(name)
            seen.add(key)
    return names


def format_attribute_catalog(path: Path = DEFAULT_ATTRIBUTES_PATH) -> str:
    return "\n".join(f"- {name}" for name in load_attribute_names(path))


def canonicalize_attributes(
    specifications: dict[str, str],
    path: Path = DEFAULT_ATTRIBUTES_PATH,
) -> dict[str, str]:
    catalog = {name.casefold(): name for name in load_attribute_names(path)}
    result: dict[str, str] = {}
    for name, value in specifications.items():
        canonical_name = catalog.get(" ".join(name.split()).casefold())
        if canonical_name and isinstance(value, str):
            result[canonical_name] = value
    return result
