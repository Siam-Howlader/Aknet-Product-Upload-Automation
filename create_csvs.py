
import json
import csv
import os
import math

# ==========================================
# CONFIGURATION
# ==========================================

JSON_FILE = "data/globalbrand_product_urls.json"
TEMPLATE_FILE = "template.csv"
OUTPUT_FOLDER = "generated_csvs"

PRODUCTS_PER_CSV = 25

URL_PREFIX = "https://www.globalbrand.com.bd/"

# ==========================================
# LOAD JSON DATA
# ==========================================

with open(JSON_FILE, "r", encoding="utf-8") as file:
    products = json.load(file)

# ==========================================
# LOAD EXACT CSV HEADERS FROM TEMPLATE
# ==========================================

with open(TEMPLATE_FILE, "r", encoding="utf-8-sig", newline="") as file:
    reader = csv.reader(file)
    headers = next(reader)

# ==========================================
# CREATE OUTPUT DIRECTORY
# ==========================================

os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# ==========================================
# PROCESS PRODUCTS IN BATCHES
# ==========================================

total_products = len(products)

total_csvs = math.ceil(total_products / PRODUCTS_PER_CSV)

for batch_index in range(total_csvs):

    # Select 25 products for this CSV
    start_index = batch_index * PRODUCTS_PER_CSV
    end_index = start_index + PRODUCTS_PER_CSV

    batch = products[start_index:end_index]

    # Generate filename
    csv_number = batch_index + 1
    filename = f"csv_{csv_number:03d}.csv"

    filepath = os.path.join(OUTPUT_FOLDER, filename)

    rows = []

    for index, product in enumerate(batch):

        # Global serial number
        serial_number = start_index + index + 1

        # Product name
        product_name = product.get("product_name", "").strip()

        # Product URL
        product_url = product.get("product_url", "").strip()

        # Extract SEO URL
        if product_url.startswith(URL_PREFIX):
            seo_url = product_url[len(URL_PREFIX):]
        else:
            raise ValueError(
                f"Unexpected product URL: {product_url}"
            )

        # Manufacturer = First word of product name
        manufacturer = product_name.split()[0] if product_name else ""

        # Create empty row using exact template headers
        row = {column: "" for column in headers}

        # Populate required columns
        row["Serial Number"] = serial_number
        row["Upload Status"] = "pending"
        row["Product Name"] = product_name
        row["Quantity"] = 10
        row["Manufacturer"] = manufacturer
        row["Filters"] = f"in stock,{manufacturer}"
        row["SEO URL"] = seo_url

        rows.append(row)

    # ======================================
    # WRITE CSV FILE
    # ======================================

    with open(filepath, "w", encoding="utf-8-sig", newline="") as file:

        writer = csv.DictWriter(
            file,
            fieldnames=headers,
            extrasaction="ignore"
        )

        writer.writeheader()
        writer.writerows(rows)

    print(
        f"Created {filename} | "
        f"Serial: {start_index + 1}-{start_index + len(batch)} | "
        f"Products: {len(batch)}"
    )

# ==========================================
# FINAL SUMMARY
# ==========================================

print("\n===================================")
print("CSV GENERATION COMPLETED")
print("===================================")
print(f"Total products : {total_products}")
print(f"Products per CSV: {PRODUCTS_PER_CSV}")
print(f"Total CSV files : {total_csvs}")
print(f"Output folder   : {OUTPUT_FOLDER}")
print("===================================")
