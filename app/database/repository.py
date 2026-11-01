import json
from datetime import UTC, datetime

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.ai.models import ProductContent
from app.ai.rules import build_meta_title
from app.database.models import ProductJob, ProductJobStatus


class ProductJobRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_generated_job(self, payload: ProductContent) -> ProductJob:
        job = ProductJob(
            product_name=payload.product_name,
            generated_content=payload.model_dump_json(),
            status=ProductJobStatus.GENERATED,
        )
        self.session.add(job)
        self.session.commit()
        self.session.refresh(job)
        return job

    def update_status(
        self,
        job_id: int,
        status: ProductJobStatus,
        error_message: str | None = None,
        generated_content: ProductContent | None = None,
    ) -> ProductJob | None:
        job = self.session.get(ProductJob, job_id)
        if not job:
            return None
        job.status = status
        job.error_message = error_message
        if generated_content is not None:
            job.generated_content = generated_content.model_dump_json()
        job.updated_at = datetime.now(UTC)
        self.session.add(job)
        self.session.commit()
        self.session.refresh(job)
        return job

    def find_latest_by_name(self, product_name: str) -> ProductJob | None:
        stmt = (
            select(ProductJob)
            .where(ProductJob.product_name == product_name)
            .order_by(desc(ProductJob.created_at))
            .limit(1)
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def find_latest_saved_by_name(self, product_name: str) -> ProductJob | None:
        stmt = (
            select(ProductJob)
            .where(ProductJob.product_name == product_name, ProductJob.status == ProductJobStatus.SAVED)
            .order_by(desc(ProductJob.created_at))
            .limit(1)
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def list_jobs(self, limit: int = 50) -> list[ProductJob]:
        stmt = select(ProductJob).order_by(
            desc(ProductJob.created_at)).limit(limit)
        return list(self.session.execute(stmt).scalars().all())


def deserialize_generated_content(raw_json: str) -> ProductContent:
    data = json.loads(raw_json)
    data.setdefault("model", "")
    data.setdefault("specifications", {})
    try:
        return ProductContent.model_validate(data)
    except Exception:
        # Legacy records may contain an older or malformed generated meta title.
        data["meta_title"] = build_meta_title(data["product_name"])
        return ProductContent.model_validate(data)
