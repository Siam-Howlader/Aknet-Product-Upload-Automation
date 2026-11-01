from datetime import UTC, datetime
from enum import Enum

from sqlalchemy import DateTime, Enum as SqlEnum, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.db import Base


class ProductJobStatus(str, Enum):
    GENERATED = "GENERATED"
    UPLOADING = "UPLOADING"
    FILLED = "FILLED"
    FAILED = "FAILED"
    SAVED = "SAVED"


class ProductJob(Base):
    __tablename__ = "product_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    product_name: Mapped[str] = mapped_column(String(200), index=True)
    generated_content: Mapped[str] = mapped_column(Text)
    status: Mapped[ProductJobStatus] = mapped_column(
        SqlEnum(ProductJobStatus), default=ProductJobStatus.GENERATED, index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))

