from pathlib import Path
import logging
import importlib
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)


class BrowserManager:
    """Playwright browser lifecycle manager for automation sessions."""

    def __init__(self) -> None:
        self.headless = settings.headless
        self.browser_channel = settings.browser_channel
        self.timeout_ms = settings.browser_timeout
        self.screenshot_dir = Path("debug/screenshots")
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        self._playwright: Any = None
        self._browser: Any = None

    async def start(self) -> tuple[Any, Any]:
        logger.info("Starting browser")
        playwright_async = importlib.import_module("playwright.async_api")
        self._playwright = await playwright_async.async_playwright().start()
        launch_options = {"headless": self.headless}
        if self.browser_channel:
            launch_options["channel"] = self.browser_channel
        try:
            self._browser = await self._playwright.chromium.launch(**launch_options)
        except Exception as exc:
            if self.browser_channel:
                logger.warning(
                    "Could not launch browser channel '%s': %s. Falling back to bundled Chromium.",
                    self.browser_channel,
                    str(exc),
                )
                launch_options.pop("channel", None)
                self._browser = await self._playwright.chromium.launch(**launch_options)
            else:
                raise
        context = await self._browser.new_context()
        page = await context.new_page()
        page.set_default_timeout(self.timeout_ms)
        return context, page

    async def stop(self) -> None:
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

    async def safe_screenshot(self, page: Any, name: str) -> str:
        # Skip screenshot on login pages to avoid capturing password form contents.
        if "route=common/login" in page.url or page.url.rstrip("/").endswith("/admin"):
            return ""
        path = self.screenshot_dir / f"{name}.png"
        await page.screenshot(path=str(path), full_page=True)
        return str(path)
