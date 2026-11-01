"""Build a compact category-to-attribute MAVE index.

Usage:
  python scripts/build_mave_index.py [raw-file-or-directory]

The script does not download MAVE. It accepts JSON, JSONL, CSV, or TSV files.
Records may use common MAVE field names such as category/product_category,
attribute/attribute_name, and value/attribute_value.
"""
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

DEFAULT_RAW = Path("data/mave/raw")
OUTPUT = Path("data/mave/processed/category_attributes.json")
CATEGORY_FIELDS = ("category", "product_category", "category_name")
ATTRIBUTE_FIELDS = ("attribute", "attribute_name", "key")
VALUE_FIELDS = ("value", "attribute_value", "value_name")


def main() -> int:
    raw_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_RAW
    files = [raw_path] if raw_path.is_file() else sorted(
        raw_path.glob("*")) if raw_path.is_dir() else []
    files = [path for path in files if path.suffix.lower() in {
        ".json", ".jsonl", ".csv", ".tsv"}]
    if not files:
        raise SystemExit(
            f"No MAVE files found. Place JSON/JSONL/CSV/TSV files in {raw_path} or pass a file path.")

    counts: dict[str, Counter[str]] = defaultdict(Counter)
    for path in files:
        for record in _records(path):
            category = _first(record, CATEGORY_FIELDS)
            attribute = _first(record, ATTRIBUTE_FIELDS)
            value = _first(record, VALUE_FIELDS)
            if category and attribute and value:
                counts[_clean(category)][_clean(attribute)] += 1

    if not counts:
        raise SystemExit(
            "MAVE files were read, but no category/attribute/value records were found.")
    output: dict[str, dict[str, dict[str, float | int]]] = {}
    for category, attributes in counts.items():
        total = sum(attributes.values())
        output[category] = {
            attribute: {"frequency": frequency,
                        "relevance": round(frequency / total, 6)}
            for attribute, frequency in attributes.most_common()
        }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(output, indent=2,
                      ensure_ascii=True), encoding="utf-8")
    print(f"Wrote {len(output)} categories to {OUTPUT}")
    return 0


def _records(path: Path):
    if path.suffix.lower() == ".jsonl":
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if isinstance(record, dict):
                yield record
        return
    if path.suffix.lower() == ".json":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            return
        if isinstance(data, dict):
            data = data.get("records", data.get("data", [data]))
        if isinstance(data, list):
            yield from (item for item in data if isinstance(item, dict))
        return
    with path.open(encoding="utf-8-sig", newline="") as handle:
        yield from csv.DictReader(handle, delimiter="\t" if path.suffix.lower() == ".tsv" else ",")


def _first(record: dict, fields: tuple[str, ...]) -> str:
    for field in fields:
        value = record.get(field)
        if value is not None and str(value).strip():
            return str(value)
    return ""


def _clean(value: str) -> str:
    return " ".join(value.split()).casefold()


if __name__ == "__main__":
    main()
