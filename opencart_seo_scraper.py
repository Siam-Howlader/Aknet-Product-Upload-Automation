
import json
import re
from pathlib import Path
from urllib.parse import urlparse, parse_qs, urljoin

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


# ==========================================
# CONFIGURATION
# ==========================================

OUTPUT_FILE = "all_seo_urls.json"

# Your screenshot shows 20 records per page
EXPECTED_TOTAL = 1624


# ==========================================
# EXTRACT TABLE DATA
# ==========================================

def extract_page_data(page):

    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(500)

    result = page.evaluate("""
    () => {

        const tables = [...document.querySelectorAll('table')];

        let selectedTable = null;
        let headers = [];

        for (const table of tables) {

            const headerCells = [
                ...table.querySelectorAll('thead tr th, thead tr td')
            ];

            const currentHeaders = headerCells.map(
                cell => cell.innerText.trim().toLowerCase()
            );

            if (
                currentHeaders.includes('query') &&
                currentHeaders.includes('keyword') &&
                currentHeaders.includes('store') &&
                currentHeaders.includes('language')
            ) {
                selectedTable = table;
                headers = currentHeaders;
                break;
            }
        }

        if (!selectedTable) {
            return { error: 'SEO URL table not found' };
        }

        const rows = [
            ...selectedTable.querySelectorAll('tbody tr')
        ].map(tr => [
            ...tr.querySelectorAll('td')
        ].map(td => td.innerText.trim()));

        const paginationLinks = [
            ...document.querySelectorAll('.pagination a[href]')
        ].map(a => ({
            href: a.href,
            text: a.innerText.trim(),
            title: a.title || '',
            aria: a.getAttribute('aria-label') || '',
            disabled: !!a.closest('li.disabled')
        }));

        const activeElement = document.querySelector(
            '.pagination li.active'
        );

        return {
            headers: headers,
            rows: rows,
            pagination: paginationLinks,
            active_page: activeElement
                ? activeElement.innerText.trim()
                : ''
        };
    }
    """)

    if result.get("error"):
        raise RuntimeError(result["error"])

    headers = result["headers"]

    # Find exact column positions
    query_index = headers.index("query")
    keyword_index = headers.index("keyword")
    store_index = headers.index("store")
    language_index = headers.index("language")

    records = []

    for row in result["rows"]:

        if len(row) <= max(
            query_index,
            keyword_index,
            store_index,
            language_index
        ):
            continue

        record = {
            "seo_url": row[keyword_index]
        }

        if record["seo_url"]:
            records.append(record)

    return records, result


# ==========================================
# FIND NEXT PAGE
# ==========================================

def get_next_page_url(page_data, current_url):

    current_page_match = re.search(
        r"\d+",
        page_data["active_page"]
    )

    if current_page_match:
        current_page = int(current_page_match.group())
    else:
        params = parse_qs(urlparse(current_url).query)
        current_page = int(params.get("page", ["1"])[0])

    candidates = []

    for link in page_data["pagination"]:

        if link["disabled"]:
            continue

        href = link["href"]
        params = parse_qs(urlparse(href).query)

        if "page" in params:

            try:
                target_page = int(params["page"][0])
            except ValueError:
                continue

            if target_page > current_page:
                candidates.append((target_page, href))

    # Choose the immediately following page
    if candidates:
        candidates.sort(key=lambda item: item[0])

        next_page, next_url = candidates[0]

        return next_url

    # Fallback: Find Next button
    for link in page_data["pagination"]:

        if link["disabled"]:
            continue

        label = (
            link["text"] + " " +
            link["title"] + " " +
            link["aria"]
        ).lower().strip()

        if label in [">", "›", "»", "next"] or "next" in label:
            return link["href"]

    return None


# ==========================================
# MAIN
# ==========================================

def main():

    login_url = "https://aknet.com.bd/admin/"

    if not login_url.startswith(("http://", "https://")):
        print("Invalid login URL.")
        return

    all_records = []
    visited_urls = set()

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=False
        )

        context = browser.new_context()

        page = context.new_page()

        print("\nOpening Admin Panel...")

        page.goto(
            login_url,
            wait_until="domcontentloaded"
        )

        print("\n====================================")
        print("MANUAL LOGIN")
        print("====================================")

        print("1. Log in to OpenCart.")
        print("2. Navigate to Design > SEO URL.")
        print("3. Clear any active filters.")
        print("4. Make sure page 1 is displayed.")
        print("5. Return here and press ENTER.")

        input("\nPress ENTER to start scraping...")

        # ==================================
        # SCRAPE ALL 82 PAGES
        # ==================================

        page_number = 1

        while True:

            current_url = page.url

            if current_url in visited_urls:
                print("Duplicate page detected. Stopping.")
                break

            visited_urls.add(current_url)

            print(
                f"\nScraping page {page_number}..."
            )

            try:

                records, page_data = extract_page_data(page)

            except Exception as error:

                print(f"ERROR: {error}")
                break

            all_records.extend(records)

            print(
                f"Records on this page: {len(records)}"
            )

            print(
                f"Total collected: {len(all_records)}"
            )

            # Find next page URL
            next_url = get_next_page_url(
                page_data,
                current_url
            )

            if not next_url:

                print("\nLast page reached.")
                break

            try:

                page.goto(
                    next_url,
                    wait_until="domcontentloaded",
                    timeout=60000
                )

                page.wait_for_selector(
                    "table",
                    timeout=15000
                )

            except PlaywrightTimeoutError:

                print("Next page failed to load.")
                break

            page_number += 1

        # ==================================
        # SAVE ALL RECORDS
        # ==================================

        output_path = Path(OUTPUT_FILE)

        with output_path.open(
            "w",
            encoding="utf-8"
        ) as file:

            json.dump(
                all_records,
                file,
                ensure_ascii=False,
                indent=4
            )

        # ==================================
        # SUMMARY
        # ==================================

        print("\n====================================")
        print("SCRAPING COMPLETED")
        print("====================================")

        print(f"Pages scraped: {page_number}")
        print(f"Total records: {len(all_records)}")
        print(f"Expected records: {EXPECTED_TOTAL}")
        print(f"Difference: {EXPECTED_TOTAL - len(all_records)}")

        if len(all_records) == EXPECTED_TOTAL:
            print("SUCCESS: All records collected!")
        else:
            print("WARNING: Record count does not match.")

        print(f"\nJSON saved: {output_path.resolve()}")

        print("====================================")

        input("\nPress ENTER to close browser...")

        browser.close()


if __name__ == "__main__":
    main()
