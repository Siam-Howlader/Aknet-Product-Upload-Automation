let currentJobId = null;

const statusBox = document.getElementById("statusBox");
const historyList = document.getElementById("historyList");
const bulkRows = document.getElementById("bulkRows");
const bulkProgressText = document.getElementById("bulkProgressText");
const bulkCurrentProduct = document.getElementById("bulkCurrentProduct");
const bulkSuccessful = document.getElementById("bulkSuccessful");
const bulkPending = document.getElementById("bulkPending");
const bulkCsvFile = document.getElementById("bulkCsvFile");
const bulkUploadBtn = document.getElementById("bulkUploadBtn");
const resumeBulkBtn = document.getElementById("resumeBulkBtn");
const downloadBulkCsv = document.getElementById("downloadBulkCsv");
let bulkRunning = false;
const buildCatalogIndexBtn = document.getElementById("buildCatalogIndexBtn");
const catalogIndexProgress = document.getElementById("catalogIndexProgress");
const catalogIndexStatus = document.getElementById("catalogIndexStatus");
let catalogIndexPoll = null;
const csvUpdateFile = document.getElementById("csvUpdateFile");
const csvUpdateFileStatus = document.getElementById("csvUpdateFileStatus");
const startCsvUpdateBtn = document.getElementById("startCsvUpdateBtn");
const downloadCsvUpdate = document.getElementById("downloadCsvUpdate");
const csvUpdateProgress = document.getElementById("csvUpdateProgress");
const csvUpdateStatus = document.getElementById("csvUpdateStatus");
let csvUpdatePoll = null;

const productNameInput = document.getElementById("productName");
const genProductNameInput = document.getElementById("genProductName");
const descriptionInput = document.getElementById("description");
const metaTitleInput = document.getElementById("metaTitle");
const metaDescriptionInput = document.getElementById("metaDescription");
const metaKeywordsInput = document.getElementById("metaKeywords");
const productTagsInput = document.getElementById("productTags");
const priceInput = document.getElementById("price");
const modelInput = document.getElementById("model");
const manufacturerInput = document.getElementById("manufacturer");
const categoriesInput = document.getElementById("categories");
const filtersInput = document.getElementById("filters");
const specificationsList = document.getElementById("specifications");
const keyAttributesList = document.getElementById("keyAttributes");

function setStatus(message, isError = false) {
    statusBox.textContent = message;
    statusBox.style.borderLeftColor = isError ? "#dc2626" : "#0f766e";
}

function renderCatalogIndex(data) {
    const statusLabels = {
        idle: "Ready",
        queued: "Running",
        running: "Running",
        completed: "Completed",
        partial: "Partially completed",
        failed: "Failed",
        cancelled: "Failed",
    };
    const statusLabel = statusLabels[data.status] || "Failed";
    const percent = data.total_pages
        ? Math.min(100, Math.round((data.pages_processed / data.total_pages) * 100))
        : 0;
    catalogIndexProgress.value = percent;
    catalogIndexStatus.textContent =
        `Status: ${statusLabel} | Pages scheduled/discovered: ${data.total_pages} | ` +
        `Processed: ${data.pages_processed} | Remaining: ${Math.max(0, data.total_pages - data.pages_processed)} | ` +
        `Products: ${data.products_discovered} | ` +
        `New: ${data.products_added} | Updated: ${data.products_updated} | ` +
        `Failed pages: ${data.failed_pages}` +
        (data.current_page ? ` | Current: ${data.current_page}` : "") +
        (data.completed_at ? ` | Last refresh: ${data.completed_at}` : "");
    if (data.status === "completed") {
        setStatus(`Completed: ${data.products_discovered} unique products saved.`);
    } else if (data.status === "partial") {
        setStatus(`Partially completed: ${data.products_discovered} products found; ${data.failed_pages} pages failed${data.error ? `: ${data.error}` : "."}`, true);
    } else if (data.error) {
        setStatus(`Catalog indexing failed: ${data.error}`, true);
    }
}

async function pollCatalogIndex() {
    try {
        const response = await fetch("/api/automation/catalog-index/status");
        const data = await readResponse(response);
        if (!response.ok) throw new Error(data.detail || "Could not read catalog index status.");
        renderCatalogIndex(data);
        if (data.status !== "queued" && data.status !== "running") {
            clearInterval(catalogIndexPoll);
            catalogIndexPoll = null;
            buildCatalogIndexBtn.disabled = false;
        }
    } catch (error) {
        clearInterval(catalogIndexPoll);
        catalogIndexPoll = null;
        buildCatalogIndexBtn.disabled = false;
        setStatus(`Catalog index status error: ${error.message}`, true);
    }
}

async function buildCatalogIndex() {
    buildCatalogIndexBtn.disabled = true;
    try {
        const response = await fetch("/api/automation/catalog-index/start", { method: "POST" });
        const data = await readResponse(response);
        if (!response.ok) throw new Error(data.detail || "Could not start catalog indexing.");
        renderCatalogIndex(data);
        if (!catalogIndexPoll) catalogIndexPoll = setInterval(pollCatalogIndex, 1500);
        await pollCatalogIndex();
    } catch (error) {
        buildCatalogIndexBtn.disabled = false;
        setStatus(`Catalog indexing error: ${error.message}`, true);
    }
}

async function readResponse(response) {
    const text = await response.text();
    if (!text) {
        return {};
    }

    try {
        return JSON.parse(text);
    } catch (_error) {
        const plainText = text.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();
        return {
            detail: plainText || `${response.status} ${response.statusText}`,
        };
    }
}

csvUpdateFile.addEventListener("change", () => {
    const file = csvUpdateFile.files[0];
    startCsvUpdateBtn.disabled = !file;
    downloadCsvUpdate.hidden = true;
    csvUpdateFileStatus.textContent = file ? `${file.name} (${file.size} bytes)` : "No file selected.";
});

async function startCsvUpdate() {
    const file = csvUpdateFile.files[0];
    if (!file) return;
    startCsvUpdateBtn.disabled = true;
    const form = new FormData();
    form.append("file", file);
    try {
        const response = await fetch("/api/automation/csv-update/start", { method: "POST", body: form });
        const data = await readResponse(response);
        if (!response.ok) throw new Error(data.detail || "Could not start CSV update.");
        csvUpdateStatus.textContent = "Running";
        pollCsvUpdate(data.job_id);
    } catch (error) {
        startCsvUpdateBtn.disabled = false;
        csvUpdateStatus.textContent = `Failed: ${error.message}`;
        setStatus(`CSV update error: ${error.message}`, true);
    }
}

function pollCsvUpdate(jobId) {
    if (csvUpdatePoll) clearInterval(csvUpdatePoll);
    const update = async () => {
        try {
            const response = await fetch(`/api/automation/csv-update/${encodeURIComponent(jobId)}`);
            const data = await readResponse(response);
            if (!response.ok) throw new Error(data.detail || "Could not read CSV update status.");
            const percent = data.total_rows
                ? Math.round((data.processed_rows / data.total_rows) * 100)
                : 0;
            csvUpdateProgress.value = percent;
            csvUpdateStatus.textContent =
                `${data.status}: ${data.processed_rows}/${data.total_rows} (${percent}%) | ` +
                `updated ${data.successful_rows}, review ${data.review_rows}, failed ${data.failed_rows}` +
                (data.current_product ? ` | ${data.current_product}` : "");
            if (data.download_ready) {
                clearInterval(csvUpdatePoll);
                csvUpdatePoll = null;
                downloadCsvUpdate.href = `/api/automation/csv-update/${encodeURIComponent(jobId)}/download`;
                downloadCsvUpdate.hidden = false;
                startCsvUpdateBtn.disabled = false;
                setStatus("Updated CSV is ready to download.");
            } else if (data.status === "failed") {
                clearInterval(csvUpdatePoll);
                csvUpdatePoll = null;
                startCsvUpdateBtn.disabled = false;
                setStatus(data.error || "CSV update failed.", true);
            }
        } catch (error) {
            clearInterval(csvUpdatePoll);
            csvUpdatePoll = null;
            startCsvUpdateBtn.disabled = false;
            csvUpdateStatus.textContent = `Failed: ${error.message}`;
            setStatus(`CSV update status error: ${error.message}`, true);
        }
    };
    update();
    csvUpdatePoll = setInterval(update, 1500);
}

function getCurrentContent() {
    return {
        product_name: genProductNameInput.value.trim(),
        description: descriptionInput.value.trim(),
        meta_title: metaTitleInput.value.trim(),
        meta_description: metaDescriptionInput.value.trim(),
        meta_keywords: metaKeywordsInput.value.trim(),
        product_tags: productTagsInput.value.trim(),
        price: Number(priceInput.value || 0),
        model: modelInput.value.trim() || null,
        manufacturer: manufacturerInput.value.trim(),
        categories: categoriesInput.value.trim(),
        filters: filtersInput.value.trim(),
        specifications: readSpecifications(),
        key_attributes: readSpecificationsFrom(keyAttributesList),
        job_id: currentJobId,
        force_duplicate: false,
    };
}

function readSpecifications() {
    return readSpecificationsFrom(specificationsList);
}

function readSpecificationsFrom(list) {
    const specifications = {};
    list.querySelectorAll(".specification-row").forEach((row) => {
        const name = row.querySelector(".specification-name").value.trim();
        const result = row.querySelector(".specification-result").value.trim();
        if (name && result) {
            specifications[name] = result;
        }
    });
    return specifications;
}

function renderSpecifications(specifications) {
    renderSpecificationList(specificationsList, specifications);
}

function renderKeyAttributes(attributes) {
    renderSpecificationList(keyAttributesList, attributes);
}

function renderSpecificationList(list, specifications) {
    list.innerHTML = "";
    Object.entries(specifications || {}).forEach(([name, result]) => {
        const row = document.createElement("div");
        row.className = "specification-row";
        row.innerHTML = `
            <input class="specification-name" type="text" aria-label="Attribute Name" placeholder="Attribute Name" value="${escapeHtml(name)}" />
            <input class="specification-result" type="text" aria-label="Attribute Result" placeholder="Attribute Result" value="${escapeHtml(result)}" />`;
        list.appendChild(row);
    });
}

function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, (character) => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        "\"": "&quot;",
        "'": "&#039;"
    })[character]);
}

function fillGenerated(content) {
    if (!content) {
        throw new Error("AI did not return product content. Please click Generate Product again.");
    }
    genProductNameInput.value = content.product_name || "";
    descriptionInput.value = content.description || "";
    metaTitleInput.value = content.meta_title || "";
    metaDescriptionInput.value = content.meta_description || "";
    metaKeywordsInput.value = content.meta_keywords || "";
    productTagsInput.value = content.product_tags || "";
    priceInput.value = content.price ?? priceInput.value ?? "0";
    modelInput.value = content.model || "";
    manufacturerInput.value = content.manufacturer || "";
    categoriesInput.value = content.categories || "";
    filtersInput.value = content.filters || "";
    renderKeyAttributes(content.key_attributes);
    renderSpecifications(content.specifications);
}


async function generateProduct() {
    const productName = productNameInput.value.trim();
    if (!productName) {
        setStatus("Product name is required.", true);
        return;
    }

    setStatus("Generating content...");
    try {
        const response = await fetch("/api/products/generate", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                product_name: productName,
                price: Number(priceInput.value || 0),
            }),
        });
        const data = await readResponse(response);
        if (!response.ok) {
            setStatus(data.detail || "Generation failed.", true);
            return;
        }

        currentJobId = data.job_id;
        fillGenerated(data.content);
        setStatus("Generated successfully. Review fields before upload.");
    } catch (error) {
        setStatus(`Generation error: ${error.message}`, true);
    }
}

async function uploadProduct() {
    const payload = getCurrentContent();
    if (!payload.product_name) {
        setStatus("Generated product name is required.", true);
        return;
    }

    setStatus("Uploading to OpenCart...");
    try {
        let response = await fetch("/api/automation/upload", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify(payload),
        });
        let data = await readResponse(response);

        if (response.status === 409) {
            const proceed = confirm(`${data.detail} Proceed anyway?`);
            if (!proceed) {
                setStatus("Upload canceled due to duplicate protection.", true);
                return;
            }
            payload.force_duplicate = true;
            response = await fetch("/api/automation/upload", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify(payload),
            });
            data = await readResponse(response);
        }

        if (!response.ok) {
            setStatus(data.detail || "Upload failed.", true);
            return;
        }

        setStatus(`${data.message} Current page: ${data.current_url}`);
        await loadHistory();
    } catch (error) {
        setStatus(`Upload error: ${error.message}`, true);
    }
}

async function loadHistory() {
    try {
        const response = await fetch("/api/products/history");
        const data = await readResponse(response);
        if (!response.ok) {
            return;
        }
        historyList.innerHTML = "";
        data.forEach((job) => {
            const div = document.createElement("div");
            div.className = "history-item";
            div.textContent = `#${job.id} | ${job.product_name} | ${job.status} | ${job.created_at}`;
            historyList.appendChild(div);
        });
    } catch (_err) {
        // Ignore history rendering errors.
    }
}

function renderBulkRows(rows) {
    bulkRows.innerHTML = "";
    rows.forEach((row) => updateBulkRow(row));
}

function updateBulkRow(row) {
    const key = String(row.row_number);
    let element = bulkRows.querySelector(`[data-row-number="${key}"]`);
    if (!element) {
        element = document.createElement("div");
        element.dataset.rowNumber = key;
        bulkRows.appendChild(element);
    }
    const status = row.upload_status === "succeed" ? "succeed" : "pending";
    element.className = `bulk-row ${status}`;
    element.textContent = `${row.serial_number} | ${row.product_name} | ${status}`;
    if (row.error) {
        element.title = row.error;
    }
}

function showBulkDownload(batchId) {
    const extension = localStorage.getItem("bulkUploadFileExtension") || ".csv";
    downloadBulkCsv.href = `/api/automation/bulk-upload/${encodeURIComponent(batchId)}/file`;
    downloadBulkCsv.download = `bulk-upload-${batchId}${extension}`;
    downloadBulkCsv.hidden = false;
}

async function consumeBulkStream(response) {
    if (!response.ok) {
        const data = await readResponse(response);
        throw new Error(data.detail || "Bulk upload could not be started.");
    }
    if (!response.body) {
        throw new Error("Bulk upload progress stream is unavailable.");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffered = "";
    while (true) {
        const { value, done } = await reader.read();
        buffered += decoder.decode(value || new Uint8Array(), { stream: !done });
        const events = buffered.split("\n\n");
        buffered = events.pop() || "";
        for (const item of events) {
            const line = item.split("\n").find((part) => part.startsWith("data: "));
            if (line) {
                handleBulkEvent(JSON.parse(line.slice(6)));
            }
        }
        if (done) {
            break;
        }
    }
}

function handleBulkEvent(event) {
    if (event.batch_id) {
        localStorage.setItem("bulkUploadBatchId", event.batch_id);
        if (event.file_extension) {
            localStorage.setItem("bulkUploadFileExtension", event.file_extension);
        }
        showBulkDownload(event.batch_id);
        resumeBulkBtn.hidden = false;
    }
    if (event.type === "started") {
        renderBulkRows(event.rows);
        bulkSuccessful.textContent = event.successful;
        bulkPending.textContent = event.pending;
        bulkProgressText.textContent = `Starting ${event.total} pending product(s).`;
        bulkCurrentProduct.textContent = "—";
    } else if (event.type === "product_started") {
        bulkCurrentProduct.textContent = event.product_name;
        bulkProgressText.textContent = `Uploading ${event.completed + 1} of ${event.total}...`;
    } else if (event.type === "product_finished") {
        updateBulkRow(event);
        bulkSuccessful.textContent = event.successful;
        bulkPending.textContent = event.pending;
        if (event.error) {
            setStatus(`${event.product_name}: ${event.error}`, true);
        } else {
            setStatus(`${event.product_name}: ${event.message}`);
        }
        loadHistory();
    } else if (event.type === "completed") {
        bulkProgressText.textContent = event.total === 0
            ? `No pending products to process. ${event.successful} already successful.`
            : `Finished ${event.completed} of ${event.total} pending product(s).`;
        bulkCurrentProduct.textContent = "—";
        bulkSuccessful.textContent = event.successful;
        bulkPending.textContent = event.pending;
    } else if (event.type === "batch_error") {
        bulkProgressText.textContent = `Bulk upload stopped: ${event.error}`;
        setStatus(`Bulk upload stopped: ${event.error}`, true);
    }
}

async function runBulkUpload(url, options) {
    if (bulkRunning) {
        return;
    }
    bulkRunning = true;
    bulkUploadBtn.disabled = true;
    resumeBulkBtn.disabled = true;
    bulkProgressText.textContent = "Connecting to bulk upload...";
    try {
        await consumeBulkStream(await fetch(url, options));
    } catch (error) {
        bulkProgressText.textContent = `Bulk upload error: ${error.message}`;
        setStatus(`Bulk upload error: ${error.message}`, true);
    } finally {
        bulkRunning = false;
        bulkUploadBtn.disabled = false;
        resumeBulkBtn.disabled = false;
    }
}

async function startBulkUpload() {
    const file = bulkCsvFile.files[0];
    if (!file) {
        setStatus("Select a CSV or XLSX file to start bulk upload.", true);
        return;
    }
    const form = new FormData();
    form.append("file", file);
    await runBulkUpload("/api/automation/bulk-upload", {
        method: "POST",
        body: form,
    });
}

async function resumeBulkUpload() {
    const batchId = localStorage.getItem("bulkUploadBatchId");
    if (!batchId) {
        setStatus("No saved bulk queue is available to resume.", true);
        return;
    }
    await runBulkUpload(`/api/automation/bulk-upload/${encodeURIComponent(batchId)}/resume`, {
        method: "POST",
    });
}

document.getElementById("generateBtn").addEventListener("click", generateProduct);
document.getElementById("regenerateBtn").addEventListener("click", generateProduct);
document.getElementById("uploadBtn").addEventListener("click", uploadProduct);
document.getElementById("refreshHistoryBtn").addEventListener("click", loadHistory);
bulkUploadBtn.addEventListener("click", startBulkUpload);
resumeBulkBtn.addEventListener("click", resumeBulkUpload);
buildCatalogIndexBtn.addEventListener("click", buildCatalogIndex);
startCsvUpdateBtn.addEventListener("click", startCsvUpdate);

const savedBatchId = localStorage.getItem("bulkUploadBatchId");
if (savedBatchId) {
    resumeBulkBtn.hidden = false;
    showBulkDownload(savedBatchId);
}
loadHistory();
pollCatalogIndex();