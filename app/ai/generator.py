import logging

from bs4 import BeautifulSoup

from app.ai.client import AIProvider, OllamaProvider, OpenAICompatibleProvider
from app.ai.specifications import (
    process_specifications,
    process_mave_specifications,
    select_key_attributes,
)
from app.ai.models import ProductContent, ProductContentRequest
from app.ai.mave.matcher import get_catalog_candidates
from app.ai.mave.repository import get_repository
from app.ai.prompts import SYSTEM_PROMPT, build_user_prompt
from app.ai.rules import (
    build_meta_title,
    heuristic_keywords,
    heuristic_tags,
)
from app.config import settings
from app.scraper.specification_scraper import (
    SpecificationScrapingError,
    scrape_product_content,
)

logger = logging.getLogger(__name__)


def _description_text(description: str) -> str:
    return " ".join(
        BeautifulSoup(description, "html.parser")
        .get_text(" ", strip=True)
        .split()
    ).casefold()


def _is_unusable_description(description: str, source_description: str) -> bool:
    normalized_description = _description_text(description)
    if not normalized_description:
        return True
    if (
        source_description
        and normalized_description == _description_text(source_description)
    ):
        return True
    return any(
        phrase in normalized_description
        for phrase in (
            "description not found",
            "no description found",
            "no usable retailer description was found",
        )
    )


class AIGenerationError(RuntimeError):
    """Raised when the configured AI provider cannot generate content."""


class AIContentGenerator:
    """Generate validated product content from an AI provider."""

    def __init__(self, provider: AIProvider | None = None) -> None:
        if provider:
            self.provider = provider
        elif settings.ai_provider.lower() == "ollama":
            self.provider = OllamaProvider(
                base_url=settings.ai_base_url,
                model=settings.ai_model,
                timeout_seconds=settings.ollama_timeout_seconds,
                temperature=settings.ai_temperature,
                num_ctx=settings.ollama_num_ctx,
                num_predict=settings.ollama_num_predict,
            )
        else:
            self.provider = OpenAICompatibleProvider(
                base_url=settings.ai_base_url,
                api_key=settings.ai_api_key,
                model=settings.ai_model,
                temperature=settings.ai_temperature,
            )
        self.retries = settings.ai_retries

    def generate(self, request: ProductContentRequest) -> ProductContent:
        last_error: Exception | None = None
        scraped_description: str | None = None
        scraped_specifications: dict[str, str] = {}
        try:
            scraped_content = scrape_product_content(request.product_name)
            if scraped_content is not None:
                scraped_description, scraped_specifications = scraped_content
        except SpecificationScrapingError as exc:
            logger.warning(
                "Product source scraping failed; generating from available product information: %s",
                exc,
            )
        source_description = (scraped_description or "").strip()
        if settings.mave_enabled:
            repository = get_repository(settings.mave_index_path)
            category, candidates = get_catalog_candidates(
                request.product_name,
                repository,
                settings.mave_max_candidates,
            )
            logger.info(
                "MAVE enabled: true; detected category: %s; catalog-matched candidates: %s",
                category or "none",
                len(candidates),
            )
        else:
            logger.info(
                "MAVE enabled: false; using existing specification pipeline")
        processed_specifications = (
            process_mave_specifications(
                scraped_specifications,
                product_name=request.product_name,
            ) if settings.mave_enabled and candidates else process_specifications(
                scraped_specifications,
                product_name=request.product_name,
            )
        )
        description: str | None = None
        for attempt in range(1, self.retries + 2):
            try:
                logger.info("Generating AI content attempt %s", attempt)
                generated_description = self.provider.generate(
                    system_prompt=SYSTEM_PROMPT,
                    user_prompt=build_user_prompt(
                        request.product_name,
                        source_description=source_description,
                        specifications=processed_specifications,
                        price=request.price,
                    ),
                ).strip()
                if _is_unusable_description(
                    generated_description, source_description
                ):
                    raise ValueError(
                        "AI returned an unusable product description")
                description = generated_description
                break
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "AI generation attempt %s failed: %s", attempt, str(exc))

        if description is None:
            if last_error:
                logger.error("AI generation failed after retries: %s",
                             str(last_error))
            description = (
                f"Buy {request.product_name} from AKNET Innovations Ltd. "
                "in Bangladesh"
            )

        # The entered product name is the source of truth for the generated record.
        scraped_key_features = {
            name: value
            for name, value in scraped_specifications.items()
            if name in {f"Key{index}" for index in range(1, 6)}
        }
        verified_keys = select_key_attributes(
            processed_specifications,
            scraped_key_features,
        )
        safe_name = request.product_name[:55].rstrip()
        return ProductContent(
            product_name=request.product_name,
            price=request.price,
            description=description,
            meta_title=build_meta_title(request.product_name),
            meta_description=(
                f"View {safe_name} product information and "
                "specifications at Aknet Innovations Ltd. in Bangladesh."
            ),
            meta_keywords=heuristic_keywords(request.product_name),
            product_tags=heuristic_tags(request.product_name),
            specifications=processed_specifications,
            key_attributes=verified_keys,
        )
