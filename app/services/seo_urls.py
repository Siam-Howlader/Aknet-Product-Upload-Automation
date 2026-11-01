import json
import os
import tempfile
from pathlib import Path


SEO_URLS_PATH = Path(__file__).resolve().parents[2] / "all_seo_urls.json"


def _read_records(path: Path, *, missing_ok: bool = False) -> list[dict[str, str]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        if missing_ok:
            return []
        raise ValueError(f"Could not read the SEO URL JSON: {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read the SEO URL JSON: {path}") from exc

    if not isinstance(value, list):
        raise ValueError("SEO URL JSON must contain an array.")
    if any(
        not isinstance(item, dict) or not isinstance(item.get("seo_url"), str)
        for item in value
    ):
        raise ValueError("Each SEO URL record must contain a string seo_url.")
    return value


def load_seo_urls(path: Path) -> set[str]:
    return {
        record["seo_url"].strip().casefold()
        for record in _read_records(path)
        if record["seo_url"].strip()
    }


def record_seo_url(seo_url: str, path: Path | None = None) -> None:
    clean_url = seo_url.strip()
    if not clean_url:
        raise ValueError("SEO URL cannot be blank.")

    target_path = path or SEO_URLS_PATH
    records = _read_records(target_path, missing_ok=True)
    if clean_url.casefold() in {
        record["seo_url"].strip().casefold() for record in records
    }:
        return

    records.append({"seo_url": clean_url})
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target_path.parent,
            delete=False,
        ) as output:
            temporary_path = Path(output.name)
            json.dump(records, output, ensure_ascii=False, indent=4)
            output.write("\n")
        os.replace(temporary_path, target_path)
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()
