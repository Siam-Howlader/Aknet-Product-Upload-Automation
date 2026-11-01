"""
Run this script locally to inspect live OpenCart selectors before enabling automation.

Usage:
1) Set .env values.
2) python scripts/inspect_opencart.py
3) Use Playwright Inspector window and browser devtools to verify selectors.
4) Update app/automation/selectors.json with verified selectors.
"""

from app.config import settings
from app.automation.selectors import OpenCartSelectors, load_selectors
import json
from pathlib import Path
import sys

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

# Ensure project root is importable when running this script directly.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main() -> None:
    load_dotenv()
    selectors = load_selectors()
    print("Loaded selectors from:", settings.selectors_file)
    print(json.dumps(selectors.__dict__, indent=2))
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        page.goto(settings.opencart_admin_url, wait_until="domcontentloaded")
        page.pause()
        browser.close()


def write_template_if_missing() -> None:
    path = Path(settings.selectors_file)
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(OpenCartSelectors().__dict__,
                    indent=2), encoding="utf-8")


if __name__ == "__main__":
    write_template_if_missing()
    main()
