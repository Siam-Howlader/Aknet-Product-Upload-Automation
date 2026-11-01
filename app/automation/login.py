import logging
from typing import Any

from app.automation.errors import LoginFailedError, SelectorResolutionError
from app.automation.selectors import OpenCartSelectors
from app.config import settings

logger = logging.getLogger(__name__)


class OpenCartLoginService:
    """OpenCart login/session handling."""

    def __init__(self, selectors: OpenCartSelectors) -> None:
        self.selectors = selectors

    async def open_admin(self, page: Any) -> None:
        logger.info("Opening OpenCart")
        await page.goto(settings.opencart_admin_url, wait_until="domcontentloaded")
        await self._step_delay(page)

    async def login_if_required(self, page: Any) -> None:
        username_fields = page.locator(self.selectors.username_input)
        needs_login = await username_fields.count() > 0
        if not needs_login:
            logger.info("Existing authenticated session detected")
            return

        logger.info("OpenCart login page detected")
        if not settings.opencart_username or not settings.opencart_password:
            raise LoginFailedError(
                "OpenCart credentials are missing in environment variables.")

        password_fields = page.locator(self.selectors.password_input)
        login_buttons = page.locator(self.selectors.login_button)
        if await password_fields.count() == 0 or await login_buttons.count() == 0:
            raise SelectorResolutionError(
                "Login selectors not found. Verify selectors configuration.")

        await username_fields.first.fill(settings.opencart_username)
        await self._step_delay(page)
        await password_fields.first.fill(settings.opencart_password)
        await self._step_delay(page)
        await login_buttons.first.click()
        await self._step_delay(page)

        await page.wait_for_load_state("networkidle")
        if await page.locator(self.selectors.username_input).count() > 0:
            raise LoginFailedError(
                "OpenCart login failed. Please verify the admin credentials.")

        logger.info("Login successful")

    async def _step_delay(self, page: Any) -> None:
        await page.wait_for_timeout(round(settings.automation_step_delay * 1000))
