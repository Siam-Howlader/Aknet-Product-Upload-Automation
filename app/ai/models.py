from pydantic import BaseModel, Field, ValidationInfo, field_validator, model_validator

from app.ai.rules import normalize_csv_terms, validate_meta_title
from app.ai.specifications import process_specifications


class ProductContentRequest(BaseModel):
    product_name: str = Field(min_length=3, max_length=200)
    price: float = Field(default=0, ge=0)

    @field_validator("product_name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("product_name cannot be empty")
        return cleaned


class ProductContent(BaseModel):
    product_name: str = Field(min_length=3, max_length=200)
    price: float = Field(default=0, ge=0)
    seo_url: str = Field(default="", max_length=255)
    model: str | None = Field(default="", max_length=64)
    description: str
    meta_title: str = Field(min_length=10, max_length=170)
    meta_description: str
    meta_keywords: str = Field(default="", max_length=255)
    product_tags: str = Field(min_length=3)
    manufacturer: str = Field(default="", max_length=80)
    categories: str = Field(default="", max_length=200)
    filters: str = Field(default="", max_length=200)
    key_attributes: dict[str, str] = Field(default_factory=dict, max_length=5)
    specifications: dict[str, str] = Field(
        default_factory=dict, max_length=100)

    @field_validator("meta_title")
    @classmethod
    def enforce_meta_title_format(cls, value: str, info) -> str:
        if not value.strip().lower().endswith("price in bangladesh"):
            raise ValueError("meta_title must end with 'Price in Bangladesh'")
        return value.strip()

    @field_validator("model")
    @classmethod
    def normalize_model(cls, value: str | None) -> str:
        return value.strip() if value else ""

    @field_validator("meta_description")
    @classmethod
    def normalize_meta_description(cls, value: str) -> str:
        return value.strip()

    @field_validator("seo_url")
    @classmethod
    def normalize_seo_url(cls, value: str) -> str:
        return value.strip()

    @field_validator("manufacturer")
    @classmethod
    def normalize_manufacturer(cls, value: str) -> str:
        return " ".join(value.split()).strip()

    @field_validator("meta_keywords", mode="before")
    @classmethod
    def discard_oversized_meta_keywords(cls, value: str) -> str:
        normalized = normalize_csv_terms(str(value or ""))
        return normalized if len(normalized) <= 255 else ""

    @field_validator("meta_keywords", "product_tags")
    @classmethod
    def normalize_comma_separated_fields(
        cls, value: str, info: ValidationInfo,
    ) -> str:
        normalized = normalize_csv_terms(value)
        if not normalized and info.field_name == "product_tags":
            raise ValueError("comma-separated value cannot be empty")
        return normalized

    @field_validator("categories", "filters")
    @classmethod
    def normalize_optional_list_fields(cls, value: str) -> str:
        normalized = normalize_csv_terms(value)
        return normalized

    @field_validator("specifications")
    @classmethod
    def normalize_specifications(cls, value: dict[str, str]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for name, result in value.items():
            clean_name = " ".join(name.split()).strip()
            normalized_result = result.replace("\r\n", "\n").replace("\r", "\n")
            clean_result = "\n".join(
                " ".join(line.split()) for line in normalized_result.split("\n")
            ).strip()
            if clean_name and clean_result:
                normalized[clean_name] = clean_result
        return process_specifications(normalized)


class AIError(BaseModel):
    message: str
