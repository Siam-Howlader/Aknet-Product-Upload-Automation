import json
import importlib.util

from app.ai.mave.matcher import detect_category, get_catalog_candidates
from app.ai.mave.repository import MaveRepository
from app.ai.prompts import build_user_prompt


def test_mave_repository_loads_and_ranks_categories(tmp_path) -> None:
    index = tmp_path / "category_attributes.json"
    index.write_text(json.dumps({
        "gaming mouse": {
            "DPI": {"frequency": 90, "relevance": 0.9},
            "Sensor": {"frequency": 80, "relevance": 0.8},
        }
    }), encoding="utf-8")
    repository = MaveRepository(index)
    assert repository.get_relevant_attributes(
        "gaming mouse") == ["DPI", "Sensor"]


def _build_script_module():
    path = __import__("pathlib").Path(
        __file__).parents[1] / "scripts" / "build_mave_index.py"
    spec = importlib.util.spec_from_file_location("build_mave_index", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_category_matching_supports_aliases() -> None:
    assert detect_category("Logitech wireless mouse", [
                           "gaming mouse"]) == "gaming mouse"
    assert detect_category("office printer", ["gaming mouse"]) is None


def test_mave_candidates_intersect_with_authoritative_catalog(tmp_path) -> None:
    index = tmp_path / "category_attributes.json"
    index.write_text(json.dumps({
        "gaming mouse": {
            "DPI": 0.95,
            "Not An OpenCart Attribute": 0.99,
            "Weight": 0.7,
        }
    }), encoding="utf-8")
    category, candidates = get_catalog_candidates(
        "gaming mouse", MaveRepository(index), limit=30)
    assert category == "gaming mouse"
    assert "DPI" in candidates
    assert "Weight" in candidates
    assert "Not An OpenCart Attribute" not in candidates


def test_missing_mave_index_falls_back() -> None:
    repository = MaveRepository(__import__(
        "pathlib").Path("missing-mave-index.json"))
    assert repository.get_relevant_attributes("gaming mouse") == []


def test_mave_preprocessor_skips_malformed_jsonl_records(tmp_path) -> None:
    module = _build_script_module()
    raw = tmp_path / "records.jsonl"
    raw.write_text(
        '{"category":"mouse","attribute":"DPI","value":"16000"}\nnot-json\n', encoding="utf-8")
    records = list(module._records(raw))
    assert records == [{"category": "mouse",
                        "attribute": "DPI", "value": "16000"}]


def test_mave_candidates_are_not_added_to_generation_prompt() -> None:
    prompt = build_user_prompt("gaming mouse")
    assert "gaming mouse" in prompt
    assert "DPI" not in prompt
    assert "Sensor" not in prompt
