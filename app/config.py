from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore")

    opencart_admin_url: str = Field(
        default="https://aknet.com.bd/admin/", alias="OPENCART_ADMIN_URL")
    opencart_username: str = Field(default="", alias="OPENCART_USERNAME")
    opencart_password: str = Field(default="", alias="OPENCART_PASSWORD")

    ai_provider: str = Field(default="openai", alias="AI_PROVIDER")
    ai_base_url: str = Field(
        default="https://api.openai.com/v1", alias="AI_BASE_URL")
    ai_api_key: str = Field(default="", alias="AI_API_KEY")
    ai_model: str = Field(default="", alias="AI_MODEL")
    ai_temperature: float = Field(default=0.3, ge=0, le=1, alias="AI_TEMPERATURE")
    ollama_timeout_seconds: float = Field(
        default=600.0, gt=0, alias="OLLAMA_TIMEOUT_SECONDS")
    ollama_base_url: str = Field(
        default="http://127.0.0.1:11434", alias="OLLAMA_BASE_URL")
    ollama_model: str = Field(default="", alias="OLLAMA_MODEL")
    ollama_num_ctx: int = Field(default=8192, ge=1024, alias="OLLAMA_NUM_CTX")
    ollama_num_predict: int = Field(
        default=512, ge=128, alias="OLLAMA_NUM_PREDICT")

    headless: bool = Field(default=False, alias="HEADLESS")
    browser_channel: str = Field(default="chrome", alias="BROWSER_CHANNEL")
    keep_browser_open: bool = Field(default=True, alias="KEEP_BROWSER_OPEN")
    dry_run: bool = Field(default=True, alias="DRY_RUN")
    auto_save: bool = Field(default=False, alias="AUTO_SAVE")
    browser_timeout: int = Field(default=30000, alias="BROWSER_TIMEOUT")
    automation_step_delay: float = Field(
        default=1.0, alias="AUTOMATION_STEP_DELAY")
    product_price: float = Field(default=0, alias="PRODUCT_PRICE")
    product_quantity: int = Field(default=10, alias="PRODUCT_QUANTITY")
    stock_status_option_index: int = Field(
        default=1, alias="STOCK_STATUS_OPTION_INDEX")
    navigation_retries: int = Field(default=3, alias="NAVIGATION_RETRIES")
    ai_retries: int = Field(default=2, alias="AI_RETRIES")
    mave_enabled: bool = Field(default=False, alias="MAVE_ENABLED")
    mave_index_path: str = Field(
        default="data/mave/processed/category_attributes.json",
        alias="MAVE_INDEX_PATH",
    )
    mave_max_candidates: int = Field(default=30, alias="MAVE_MAX_CANDIDATES")

    app_host: str = Field(default="127.0.0.1", alias="APP_HOST")
    app_port: int = Field(default=8000, alias="APP_PORT")
    sqlite_path: str = Field(
        default="data/opencart_uploader.db", alias="SQLITE_PATH")
    selectors_json_path: str = Field(
        default="app/automation/selectors.json", alias="SELECTORS_JSON_PATH")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    crawl_timeout_seconds: float = Field(default=45.0, gt=0, alias="CRAWL_TIMEOUT_SECONDS")
    crawl_retries: int = Field(default=2, ge=0, le=5, alias="CRAWL_RETRIES")
    catalog_url: str = Field(
        default="https://www.globalbrand.com.bd/products", alias="CATALOG_URL")
    catalog_max_pages: int = Field(default=300, ge=1, le=5000, alias="CATALOG_MAX_PAGES")
    catalog_max_products: int = Field(default=10000, ge=1, le=100000, alias="CATALOG_MAX_PRODUCTS")
    catalog_request_delay: float = Field(default=0.5, ge=0, le=60, alias="CATALOG_REQUEST_DELAY")
    globalbrand_max_concurrency: int = Field(
        default=5, ge=1, le=20, alias="GLOBALBRAND_MAX_CONCURRENCY")
    catalog_json_path: str = Field(
        default="data/globalbrand_product_urls.json", alias="CATALOG_JSON_PATH")

    @property
    def sqlite_file(self) -> Path:
        return Path(self.sqlite_path)

    @property
    def selectors_file(self) -> Path:
        return Path(self.selectors_json_path)

    @property
    def catalog_json_file(self) -> Path:
        return Path(self.catalog_json_path)


settings = Settings()
