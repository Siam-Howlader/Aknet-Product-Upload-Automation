from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.ai.generator import AIGenerationError, AIContentGenerator
from app.ai.models import ProductContent, ProductContentRequest
from app.database.repository import deserialize_generated_content
from app.dependencies import get_db
from app.services.job_service import ProductJobService
from app.services.schemas import GenerateRequest, GenerateResponse, ProductJobResponse

router = APIRouter()


def _map_job_to_response(job) -> ProductJobResponse:
    return ProductJobResponse(
        id=job.id,
        product_name=job.product_name,
        generated_content=deserialize_generated_content(job.generated_content),
        status=job.status.value,
        error_message=job.error_message,
        created_at=job.created_at.isoformat(),
        updated_at=job.updated_at.isoformat(),
    )


@router.post("/generate", response_model=GenerateResponse)
async def generate_product_content(payload: GenerateRequest, db: Session = Depends(get_db)) -> GenerateResponse:
    generator = AIContentGenerator()
    try:
        content = generator.generate(
            ProductContentRequest(
                product_name=payload.product_name,
                price=payload.price,
            ))
    except AIGenerationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    service = ProductJobService(db)
    job = service.create_generated_job(content)
    return GenerateResponse(job_id=job.id, content=content)


@router.get("/history", response_model=list[ProductJobResponse])
async def get_history(db: Session = Depends(get_db)) -> list[ProductJobResponse]:
    service = ProductJobService(db)
    jobs = service.list_jobs(limit=5)
    return [_map_job_to_response(job) for job in jobs]
