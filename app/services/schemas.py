from pydantic import BaseModel, Field, field_validator

from app.ai.models import ProductContent


class UploadProductRequest(ProductContent):
    images: str = Field(default="")
    model: str | None = Field(default=None, max_length=64)
    price: float = Field(default=0, ge=0)
    quantity: int = Field(default=10, ge=0)
    stock_status_option_index: int = Field(default=1, ge=0)
    force_duplicate: bool = Field(default=False)
    job_id: int | None = None
    meta_description: str | None = None


class ProductJobResponse(BaseModel):
    id: int
    product_name: str
    generated_content: ProductContent
    status: str
    error_message: str | None
    created_at: str
    updated_at: str


class GenerateRequest(BaseModel):
    product_name: str = Field(min_length=3, max_length=300)
    price: float = Field(default=0, ge=0)

    @field_validator("product_name")
    @classmethod
    def trim_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("product_name cannot be blank")
        return cleaned


class GenerateResponse(BaseModel):
    job_id: int
    content: ProductContent


class UploadResponse(BaseModel):
    job_id: int
    status: str
    message: str
    current_url: str
