# AI-Powered OpenCart Product Upload Automation System

## Features

- FastAPI backend with secure `.env` based settings
- AI content generation with provider abstraction (OpenAI-compatible)
- Editable web UI for generated fields before upload
- Playwright automation for OpenCart admin workflow
- Dry-run by default (`DRY_RUN=true`) and save disabled by default (`AUTO_SAVE=false`)
- SQLite job history with statuses: `GENERATED`, `UPLOADING`, `FILLED`, `FAILED`, `SAVED`
- Duplicate protection for already-saved product names
- Selector overrides via `app/automation/selectors.json`
- Failure screenshots in `debug/screenshots/` (login screen intentionally excluded)

## Project Structure

```text
automation/
  app/
    ai/
      client.py
      generator.py
      models.py
      prompts.py
      rules.py
    automation/
      browser.py
      errors.py
      login.py
      products.py
      selectors.json
      selectors.py
      workflow.py
    database/
      db.py
      models.py
      repository.py
    routes/
      automation.py
      products.py
    services/
      job_service.py
      schemas.py
    static/
      app.js
      style.css
    templates/
      index.html
    config.py
    dependencies.py
    main.py
  scripts/
    inspect_opencart.py
  tests/
    test_ai.py
    test_automation.py
    test_duplicate_detection.py
    test_validation.py
  .env.example
  .gitignore
  requirements.txt
  run.py
```

## Windows Setup

1. Install Python 3.11 or 3.12 (recommended for best dependency compatibility).

2. Create and activate a Python 3.12 virtual environment:

```powershell
py -3.12 -m venv .venv312
.\.venv312\Scripts\Activate.ps1
```

3. Install dependencies and browser:

```powershell
pip install -r requirements.txt
playwright install chromium
```

4. Create `.env` from `.env.example` and fill OpenCart credentials. For free local AI, install Ollama and download a model:

```powershell
ollama pull llama3.2:3b
```

Keep `AI_PROVIDER=ollama`; no `AI_API_KEY` is required. Ollama must be running locally.

5. Run the app:

```powershell
python run.py
```

6. Open browser:

```text
http://127.0.0.1:8000
```

## Required `.env` Values

- `OPENCART_ADMIN_URL`
- `OPENCART_USERNAME`
- `OPENCART_PASSWORD`
- `AI_API_KEY`
- `AI_MODEL`
- `AI_TEMPERATURE` (default `0.3`; lower values favor more consistent factual output)
- `OLLAMA_TIMEOUT_SECONDS` (default `600`; increase it if local model generation takes longer)
- `OLLAMA_NUM_CTX` (default `8192`)
- `OLLAMA_NUM_PREDICT` (default `512`; the model returns plain description text, not a JSON object)

For no-cost local generation:

- Install Ollama from `https://ollama.com/download/windows`
- Run `ollama pull llama3.2:3b`
- Set `AI_PROVIDER=ollama`
- Set `AI_BASE_URL=http://127.0.0.1:11434`
- Set `AI_MODEL=llama3.2:3b`

Optional controls:

- `HEADLESS=false`
- `DRY_RUN=true`
- `AUTO_SAVE=false`
- `BROWSER_TIMEOUT=30000`
- `NAVIGATION_RETRIES=3`
- `AI_RETRIES=2`
- `MAVE_ENABLED=false`
- `MAVE_INDEX_PATH=data/mave/processed/category_attributes.json`
- `MAVE_MAX_CANDIDATES=30`

## MAVE Attribute Knowledge (Optional)

MAVE (Multi-source Attribute Value Extraction) is used only as statistical knowledge for selecting likely relevant attributes by product category. It is not treated as the current product's source of truth, and its attributes must still match the authoritative `attributes_extracted.txt` catalog.

Raw MAVE data is intentionally not downloaded or committed by this project. Obtain it from the dataset's official distribution and place JSON, JSONL, CSV, or TSV files in `data/mave/raw/`. Then build the compact local index:

```powershell
python scripts/build_mave_index.py
```

The output is `data/mave/processed/category_attributes.json`. Enable it with `MAVE_ENABLED=true`. If it is disabled, missing, malformed, or no category matches, generation automatically uses the existing AI-only specification pipeline. Review the MAVE dataset license and usage terms before downloading or redistributing raw data.

## Usage Flow

1. Enter product name.
2. Click `Generate Product`.
3. Review/edit generated fields.
4. Click `Upload to OpenCart`.
5. Automation logs in, opens Catalog -> Products -> Add Product, fills and verifies fields.
6. With defaults, it stops before save.

## Bulk Upload from CSV or XLSX

Use the **Bulk Upload from CSV or XLSX** section to select either a CSV or XLSX containing these columns: `Serial Number`, `Upload Status`, `Product Name`, `Model`, `Price`, `Quantity`, `Manufacturer`, `Categories`, and `Filters`. Additional columns are preserved. Rows marked `pending` are processed sequentially; rows marked `succeed` are skipped. AI-generated descriptions, specifications, and SEO content still use the regular generation pipeline.

The application saves a server-side copy under the SQLite data directory and atomically updates its `Upload Status` after each product attempt without converting file formats. XLSX updates preserve the workbook and change only the status cell value and its green/red style. Only products confirmed saved by OpenCart are marked `succeed`; failures and products blocked from saving by `DRY_RUN`/`AUTO_SAVE` remain `pending`. The UI shows live progress and provides a **Download Updated File** link. The saved queue can also be resumed after an application restart using **Resume Saved Queue**; download the updated copy when you need the changed file locally.

## Global Brand Product URL Index

Open **Global Brand Product URL Index** and click **Build / Refresh Product URL
JSON**. The backend uses one shared asynchronous Crawl4AI browser context,
discovers pagination dynamically, and processes listing pages concurrently.
The default worker limit is five. Each saved record contains only
`product_name` and `product_url`.

Configure the crawl limits in `.env`:

```env
CATALOG_URL=https://www.globalbrand.com.bd/products
CATALOG_MAX_PAGES=300
CATALOG_MAX_PRODUCTS=10000
CATALOG_REQUEST_DELAY=0.5
GLOBALBRAND_MAX_CONCURRENCY=5
CATALOG_JSON_PATH=data/globalbrand_product_urls.json
```

The final JSON is written atomically to `data/globalbrand_product_urls.json`.
Valid existing records are merged and updated by normalized URL. If a crawl
fails or is partial, the previous valid JSON remains intact and the UI reports
the number of failed pages. No catalog run, product cache, or enrichment job
is stored in SQLite.

## Updating a product CSV

The **Update Product CSV** section uses the existing
`data/globalbrand_product_urls.json` directory; it never rebuilds that file.
Choose a UTF-8 CSV, click **Update CSV**, and wait for the background job to
finish. Product names are matched conservatively, matched Global Brand pages
are crawled with Crawl4AI, and only mapped product fields are updated. Rows
that cannot be matched or verified remain unchanged and are listed in the
processing report. The output is validated and saved separately as
`data/csv_updates/<original-name>_updated.csv`; the **Download Updated CSV**
link is enabled only after validation succeeds.

If a matched Global Brand page has no usable product description, the
`Product Description` cell is filled with
`Buy <product name> from AKNET Innovations Ltd.`. Bulk upload continues to use
its existing CSV/XLSX workflow independently.

When a usable description is found, the updater captures the complete
description block, including paragraphs and lists, then sends that full source
to the configured local Ollama model for factual AKNET Innovations Ltd.
rewriting before writing it to `Product Description`. The rewrite is instructed
to preserve the source's supported features, specifications, model identifiers,
and compatibility details without inventing claims. If Ollama is unavailable,
the complete cleaned source description is retained and the row report records
the rewrite limitation.

## Selector Verification and Updates

Because OpenCart versions/themes can differ, validate selectors on your live admin:

```powershell
python scripts/inspect_opencart.py
```

Then update:

- `app/automation/selectors.json`

Selector keys to confirm:

- `catalog_menu_link`
- `products_link`
- `add_product_button`
- `product_name_input`
- `description_editor`
- `meta_title_input`
- `meta_description_input`
- `meta_keywords_input`
- `tags_input`
- `save_button`

## Testing

Run all tests:

```powershell
pytest
```

Non-destructive scope:

- Validation logic
- AI generation behavior (with stubbed provider)
- Selector loading
- Duplicate detection

## Troubleshooting

- `OpenCart login failed`: verify admin username/password in `.env`.
- `Selector not found`: inspect live page and update `app/automation/selectors.json`.
- `AI generation fallback used`: check `AI_API_KEY`, `AI_MODEL`, and provider endpoint.
- `AUTO_SAVE` is not running: ensure `DRY_RUN=false` and `AUTO_SAVE=true`.

## Security Notes

- Do not commit `.env`.
- Passwords/API keys are never returned to frontend.
- Session tokens/cookies are never logged.
# Aknet-Product-Upload-Automation
"# Aknet-Product-Upload-Automation" 
