from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.ai.models import ProductContent
from app.database.db import Base
from app.database.models import ProductJobStatus
from app.services.job_service import DuplicateSavedProductError, ProductJobService


def _sample_content() -> ProductContent:
    return ProductContent(
        product_name="A4TECH OP-730D",
        description="<p>Reliable wired optical mouse for everyday use in Bangladesh market.</p><p>Order from AKNET Innovations Ltd.</p>",
        meta_title="A4TECH OP-730D Price in Bangladesh",
        meta_description="Buy A4TECH OP-730D in Bangladesh for stable everyday performance from AKNET Innovations Ltd.",
        meta_keywords="A4TECH OP-730D price in Bangladesh, wired mouse BD",
        product_tags="A4TECH Mouse, Wired Mouse",
    )


def test_duplicate_detection_blocks_saved_products() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)

    with Session() as session:
        service = ProductJobService(session)
        job = service.create_generated_job(_sample_content())
        service.mark_saved(job.id)

        blocked = False
        try:
            service.ensure_not_duplicate_saved(
                "A4TECH OP-730D", force_duplicate=False)
        except DuplicateSavedProductError:
            blocked = True

        assert blocked


def test_duplicate_detection_allows_override() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)

    with Session() as session:
        service = ProductJobService(session)
        job = service.create_generated_job(_sample_content())
        service.mark_saved(job.id)
        service.ensure_not_duplicate_saved(
            "A4TECH OP-730D", force_duplicate=True)
