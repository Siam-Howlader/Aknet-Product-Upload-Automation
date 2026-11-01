import asyncio
from crawl4ai import AsyncWebCrawler


async def main():
    # Define the target URL
    url = "https://www.globalbrand.com.bd/a4tech-4200n-wireless-keyboard-mouse-combo"

    # Initialize the AsyncWebCrawler
    async with AsyncWebCrawler() as crawler:
        # Run the crawler on the target URL
        result = await crawler.arun(url=url)

        # Check if the crawl was successful
        if result.success:
            print("--- Extracted Markdown Data ---")
            # Clear text data formatted as clean Markdown
            print(result.markdown)

            # Alternatively, if you want raw HTML content:
            # print(result.html)
        else:
            print(f"Crawl failed with error: {result.error_message}")

# Run the async main loop
if __name__ == "__main__":
    asyncio.run(main())
