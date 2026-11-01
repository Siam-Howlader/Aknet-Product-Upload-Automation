from app.scraper.specification_scraper import (
    SpecificationScrapingError,
    scrape_product_specifications_with_source,
)


if __name__ == "__main__":
    product_name = input("Enter product name: ").strip()
    try:
        source_url, specifications = scrape_product_specifications_with_source(
            product_name)
    except SpecificationScrapingError as exc:
        print(f"Specification scraping failed: {exc}")
        raise SystemExit(1) from exc

    print(f"Google first result: {source_url}")
    print(f"URL: {source_url}")
    print("\n=== PRODUCT SPECIFICATIONS ===")
    for name, value in specifications.items():
        print(f"{name} : {value}")
    print(f"\nTotal specifications: {len(specifications)}")
