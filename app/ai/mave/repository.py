import json
from functools import lru_cache
from pathlib import Path

from app.ai.mave.schemas import AttributeStat, MaveCategory


class MaveRepository:
    def __init__(self, index_path: Path) -> None:
        self.index_path = index_path
        self._categories = self._load()

    def _load(self) -> dict[str, MaveCategory]:
        if not self.index_path.exists():
            return {}
        try:
            data = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        categories: dict[str, MaveCategory] = {}
        for raw_category, raw_attributes in data.items():
            if not isinstance(raw_category, str) or not isinstance(raw_attributes, dict):
                continue
            attributes: list[AttributeStat] = []
            for raw_name, raw_stat in raw_attributes.items():
                if isinstance(raw_stat, dict):
                    frequency = int(raw_stat.get("frequency", 0))
                    relevance = float(raw_stat.get("relevance", 0))
                else:
                    frequency = 0
                    relevance = float(raw_stat)
                if isinstance(raw_name, str) and relevance > 0:
                    attributes.append(AttributeStat(
                        raw_name, frequency, relevance))
            attributes.sort(key=lambda item: (-item.relevance, -
                            item.frequency, item.name.casefold()))
            categories[raw_category.casefold()] = MaveCategory(
                raw_category, tuple(attributes))
        return categories

    def get_relevant_attributes(self, category: str, limit: int = 30) -> list[str]:
        category_data = self._categories.get(category.casefold())
        if not category_data:
            return []
        return [item.name for item in category_data.attributes[:limit]]

    def get_categories(self) -> list[str]:
        return [item.name for item in self._categories.values()]

    def get_attribute_statistics(self, category: str, attribute: str) -> AttributeStat | None:
        category_data = self._categories.get(category.casefold())
        if not category_data:
            return None
        for item in category_data.attributes:
            if item.name.casefold() == attribute.casefold():
                return item
        return None


@lru_cache(maxsize=8)
def get_repository(index_path: str) -> MaveRepository:
    return MaveRepository(Path(index_path))
