from sqlalchemy.orm import Session

from app.ai.models import ProductContent
from app.database.models import ProductJob, ProductJobStatus
from app.database.repository import ProductJobRepository


class DuplicateSavedProductError(Exception):
    pass


class ProductJobService:
    def __init__(self, session: Session) -> None:
        self.repo = ProductJobRepository(session)

    def create_generated_job(self, content: ProductContent) -> ProductJob:
        return self.repo.create_generated_job(content)

    def ensure_not_duplicate_saved(self, product_name: str, force_duplicate: bool) -> None:
        duplicate = self.repo.find_latest_saved_by_name(product_name)
        if duplicate and not force_duplicate:
            raise DuplicateSavedProductError(
                "This product has already been uploaded.")

    def mark_uploading(self, job_id: int) -> ProductJob | None:
        return self.repo.update_status(job_id=job_id, status=ProductJobStatus.UPLOADING)

    def mark_filled(self, job_id: int) -> ProductJob | None:
        return self.repo.update_status(job_id=job_id, status=ProductJobStatus.FILLED)

    def mark_saved(self, job_id: int) -> ProductJob | None:
        return self.repo.update_status(job_id=job_id, status=ProductJobStatus.SAVED)

    def mark_failed(self, job_id: int, error_message: str) -> ProductJob | None:
        return self.repo.update_status(job_id=job_id, status=ProductJobStatus.FAILED, error_message=error_message)

    def list_jobs(self, limit: int = 50) -> list[ProductJob]:
        return self.repo.list_jobs(limit=limit)
