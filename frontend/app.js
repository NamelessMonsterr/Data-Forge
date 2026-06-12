const API_BASE = window.DATAFORGE_API_BASE || "http://127.0.0.1:8000";

const state = {
  results: [],
  activeFilter: "all",
  activeDataset: null,
  activeTab: "overview",
};

const elements = {
  providerStatus: document.querySelector("#providerStatus"),
  heroSearchForm: document.querySelector("#heroSearchForm"),
  heroQuery: document.querySelector("#heroQuery"),
  searchForm: document.querySelector("#searchForm"),
  searchQuery: document.querySelector("#searchQuery"),
  includePublic: document.querySelector("#includePublic"),
  searchStatus: document.querySelector("#searchStatus"),
  resultContext: document.querySelector("#resultContext"),
  resultsList: document.querySelector("#resultsList"),
  detailsPane: document.querySelector("#detailsPane"),
  uploadForm: document.querySelector("#uploadForm"),
  uploadResult: document.querySelector("#uploadResult"),
  uploadStepper: document.querySelector("#uploadStepper"),
  datasetFile: document.querySelector("#datasetFile"),
  uploadRequest: document.querySelector("#uploadRequest"),
  loadCatalogButton: document.querySelector("#loadCatalogButton"),
  refreshCatalogButton: document.querySelector("#refreshCatalogButton"),
  catalogGrid: document.querySelector("#catalogGrid"),
  filters: [...document.querySelectorAll(".filter")],
  promptButtons: [...document.querySelectorAll("[data-prompt]")],
  toast: document.querySelector("#toast"),
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function api(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(body.detail || `Request failed: ${response.status}`);
  }
  return body;
}

function scoreLabel(item) {
  const score = item.relevance_score ?? item.discovery_score ?? item.quality_score ?? 0;
  return `${Math.round(Number(score) * 100 || Number(score))}%`;
}

function sourceLabel(item) {
  return item.source || item.provider || "local";
}

function zipUrl(item) {
  const taskId = item.task_id || item.taskId;
  return taskId ? `${API_BASE}/artifacts/${taskId}/dataset.zip` : "";
}

function renderResults() {
  const filtered = state.results.filter((item) => {
    if (state.activeFilter === "all") return true;
    const source = sourceLabel(item).toLowerCase();
    const provider = String(item.provider || "").toLowerCase();
    const domain = String(item.domain || "").toLowerCase();
    return [source, provider, domain].includes(state.activeFilter);
  });

  elements.resultsList.innerHTML = filtered.length
    ? filtered.map(renderResultCard).join("")
    : `<div class="empty-state result-card"><h3>No datasets found</h3><p>Try a broader search or upload a dataset first.</p></div>`;

  document.querySelectorAll(".result-card[data-id]").forEach((card) => {
    card.addEventListener("click", () => {
      state.activeDataset = state.results.find((item) => String(item.id) === card.dataset.id);
      state.activeTab = "overview";
      renderDetails();
      renderResults();
    });
  });
}

function renderResultCard(item) {
  const active = state.activeDataset && String(state.activeDataset.id) === String(item.id);
  const tags = (item.tags || item.metadata?.tags || []).slice(0, 4);
  const summary = item.ai_summary || item.description || item.snippet || "No summary available.";
  return `
    <article class="result-card ${active ? "active" : ""}" data-id="${escapeHtml(item.id)}">
      <div class="result-top">
        <div>
          <h3>${escapeHtml(item.title)}</h3>
          <p>${escapeHtml(summary)}</p>
        </div>
        <div class="score">${escapeHtml(scoreLabel(item))}</div>
      </div>
      <div class="meta-row">
        <span>${escapeHtml(sourceLabel(item))}</span>
        <span>${escapeHtml(item.rows || item.metadata?.rows || 0)} rows</span>
        <span>${escapeHtml(item.columns || "n/a")} columns</span>
        <span>Quality ${escapeHtml(item.quality_score ?? "n/a")}</span>
        <span>Semantic ${escapeHtml(item.semantic_relevance ?? item.discovery_score ?? "n/a")}</span>
      </div>
      <div class="meta-row">${tags.map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`).join("")}</div>
    </article>
  `;
}

function renderDetails() {
  const item = state.activeDataset;
  if (!item) {
    elements.detailsPane.innerHTML = `
      <div class="empty-state">
        <h3>Select a dataset</h3>
        <p>Open a result to inspect summary, recommendation, schema, quality, and artifacts.</p>
      </div>
    `;
    return;
  }
  const tabs = ["overview", "schema", "quality", "artifacts", "recommendations"];
  elements.detailsPane.innerHTML = `
    <h3>${escapeHtml(item.title)}</h3>
    <div class="meta-row">
      <span>${escapeHtml(sourceLabel(item))}</span>
      <span>${escapeHtml(item.format || item.license || "dataset")}</span>
    </div>
    <div class="tabs">
      ${tabs.map((tab) => `<button class="tab ${state.activeTab === tab ? "active" : ""}" data-tab="${tab}" type="button">${tab}</button>`).join("")}
    </div>
    ${renderTab(item)}
  `;
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      state.activeTab = tab.dataset.tab;
      renderDetails();
    });
  });
}

function renderTab(item) {
  const schema = item.schema || {};
  if (state.activeTab === "schema") {
    const rows = Object.entries(schema).slice(0, 12);
    return `
      <div class="detail-section">
        <h4>Schema</h4>
        <div class="schema-list">
          ${rows.length ? rows.map(([name, meta]) => `
            <div class="schema-row">
              <span>${escapeHtml(name)}</span>
              <strong>${escapeHtml(meta.type || "unknown")}</strong>
            </div>
          `).join("") : "<p>No schema available.</p>"}
        </div>
      </div>
    `;
  }
  if (state.activeTab === "quality") {
    return `
      <div class="detail-section">
        <h4>Quality</h4>
        <div class="metric-grid">
          <div class="metric"><span>Missing Values</span><strong>${escapeHtml(item.stats?.missing_cells ?? "n/a")}</strong></div>
          <div class="metric"><span>Duplicates</span><strong>${escapeHtml(item.stats?.duplicate_rows ?? "n/a")}</strong></div>
          <div class="metric"><span>Overall Quality</span><strong>${escapeHtml(item.quality_score ?? "n/a")}</strong></div>
          <div class="metric"><span>Semantic Score</span><strong>${escapeHtml(item.semantic_relevance ?? "n/a")}</strong></div>
        </div>
      </div>
    `;
  }
  if (state.activeTab === "artifacts") {
    const download = zipUrl(item);
    const artifacts = item.artifacts || {};
    return `
      <div class="detail-section">
        <h4>Artifacts</h4>
        <div class="artifact-links">
          ${download ? `<a href="${download}">Download ZIP Package</a>` : ""}
          ${Object.entries(artifacts).map(([name, path]) => `<span>${escapeHtml(name)}: ${escapeHtml(path)}</span>`).join("") || "<p>No artifacts available for public candidates.</p>"}
        </div>
      </div>
    `;
  }
  if (state.activeTab === "recommendations") {
    return `
      <div class="detail-section">
        <h4>AI Recommendation</h4>
        <p>${escapeHtml(item.recommendation || "Search this dataset to generate a recommendation.")}</p>
      </div>
      <div class="detail-section">
        <h4>Suggested Use</h4>
        <p>Best for discovery, exploratory analysis, model prototyping, and dataset packaging.</p>
      </div>
    `;
  }
  return `
    <div class="detail-section">
      <h4>Dataset Summary</h4>
      <p>${escapeHtml(item.ai_summary || item.description || item.snippet || "No summary available.")}</p>
    </div>
    <div class="detail-section">
      <h4>Metadata</h4>
      <div class="metric-grid">
        <div class="metric"><span>Rows</span><strong>${escapeHtml(item.rows || item.metadata?.rows || 0)}</strong></div>
        <div class="metric"><span>Columns</span><strong>${escapeHtml(item.columns || "n/a")}</strong></div>
        <div class="metric"><span>Source</span><strong>${escapeHtml(sourceLabel(item))}</strong></div>
        <div class="metric"><span>Provider</span><strong>${escapeHtml(item.provider || "local")}</strong></div>
      </div>
    </div>
  `;
}

async function runSearch(query, includePublic = true) {
  elements.searchStatus.textContent = "Understanding query...";
  showToast("Understanding query...");
  await wait(180);
  elements.searchStatus.textContent = "Searching datasets...";
  const body = await api("/datasets/search", {
    method: "POST",
    body: JSON.stringify({ query, include_public: includePublic, limit: 12 }),
  });
  elements.searchStatus.textContent = "Ranking relevance and generating recommendations...";
  await wait(180);
  state.results = body.results || [];
  state.activeDataset = state.results[0] || null;
  state.activeTab = "overview";
  elements.resultContext.textContent = `Results for "${query}"`;
  elements.searchStatus.textContent = `${body.counts?.returned || 0} results returned. Local: ${body.counts?.local || 0}. Public: ${body.counts?.public || 0}.`;
  showToast("Search complete.");
  renderResults();
  renderDetails();
  location.hash = "search";
}

async function loadCatalog() {
  elements.searchStatus.textContent = "Loading local catalog...";
  const body = await api("/datasets/catalog");
  state.results = body.datasets || [];
  state.activeDataset = state.results[0] || null;
  state.activeTab = "overview";
  elements.resultContext.textContent = "Local catalog";
  elements.searchStatus.textContent = `${state.results.length} indexed datasets.`;
  showToast("Catalog refreshed.");
  renderResults();
  renderDetails();
  renderCatalogGrid();
  location.hash = "catalog";
}

function renderCatalogGrid() {
  const items = state.results.filter((item) => sourceLabel(item) === "local_upload");
  elements.catalogGrid.innerHTML = items.length
    ? items.map((item) => `
      <article class="catalog-card">
        <h3>${escapeHtml(item.title)}</h3>
        <p>${escapeHtml(item.ai_summary || item.description || "No summary available.")}</p>
        <div class="meta-row">
          <span>${escapeHtml(item.rows)} rows</span>
          <span>Quality ${escapeHtml(item.quality_score ?? "n/a")}</span>
        </div>
      </article>
    `).join("")
    : `<div class="catalog-card empty-state"><h3>No local datasets yet</h3><p>Upload and process a dataset to populate the catalog.</p></div>`;
}

async function processUpload(event) {
  event.preventDefault();
  const file = elements.datasetFile.files[0];
  if (!file) {
    renderUploadError("Choose a CSV, JSON, or JSONL file first.");
    return;
  }
  setStepper(0);
  showToast("Upload started.");
  elements.uploadResult.querySelector("p").textContent = "Uploading dataset...";
  const content = await file.text();
  setStepper(1);
  await wait(180);
  setStepper(2);
  const result = await api("/datasets/process", {
    method: "POST",
    body: JSON.stringify({
      filename: file.name,
      content,
      request: elements.uploadRequest.value || "Analyze this uploaded dataset.",
    }),
  });
  setStepper(6);
  showToast("Dataset processed and indexed.");
  const zip = `${API_BASE}/artifacts/${result.task_id}/dataset.zip`;
  elements.uploadResult.innerHTML = `
    <h3>Dataset Processed Successfully</h3>
    <div class="metric-grid">
      <div class="metric"><span>Rows</span><strong>${escapeHtml(result.summary.rows)}</strong></div>
      <div class="metric"><span>Columns</span><strong>${escapeHtml(result.summary.columns)}</strong></div>
      <div class="metric"><span>Quality Score</span><strong>${escapeHtml(result.quality_report.score)}</strong></div>
      <div class="metric"><span>Duplicates</span><strong>${escapeHtml(result.summary.duplicate_rows)}</strong></div>
    </div>
    <div class="detail-section">
      <h4>AI Summary</h4>
      <p>${escapeHtml(result.ingestion.filename)} was normalized, analyzed, packaged, and indexed into the catalog.</p>
    </div>
    <div class="hero-actions">
      <button class="button secondary" id="viewProcessed" type="button">View Dataset</button>
      <a class="button" href="${zip}">Download ZIP</a>
      <button class="button ghost" id="searchSimilar" type="button">Search Similar Datasets</button>
    </div>
  `;
  document.querySelector("#viewProcessed").addEventListener("click", loadCatalog);
  document.querySelector("#searchSimilar").addEventListener("click", () => runSearch(file.name.replace(/\.[^.]+$/, ""), true));
}

function setStepper(count) {
  [...elements.uploadStepper.querySelectorAll("div")].forEach((step, index) => {
    step.classList.toggle("done", index < count);
    step.classList.toggle("active", index === count && count < 6);
  });
}

function renderUploadError(message) {
  elements.uploadResult.innerHTML = `<h3 class="error">Upload failed</h3><p>${escapeHtml(message)}</p>`;
  showToast(message, true);
}

async function loadProviderStatus() {
  try {
    const status = await api("/ai/llm/status");
    const primary = status.provider_priority?.[0] || "nim";
    elements.providerStatus.textContent = `AI Status - ${primary.toUpperCase()}`;
    elements.providerStatus.title = `Retries: ${status.max_retries}. Cooldown: ${status.cooldown_seconds}s.`;
  } catch {
    elements.providerStatus.textContent = "AI Status - Offline";
  }
}

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function showToast(message, isError = false) {
  elements.toast.textContent = message;
  elements.toast.classList.toggle("error", isError);
  elements.toast.classList.add("show");
  window.clearTimeout(showToast.timeoutId);
  showToast.timeoutId = window.setTimeout(() => {
    elements.toast.classList.remove("show");
  }, 2200);
}

elements.heroSearchForm.addEventListener("submit", (event) => {
  event.preventDefault();
  elements.searchQuery.value = elements.heroQuery.value;
  runSearch(elements.heroQuery.value || "healthcare datasets", true).catch((error) => {
    elements.searchStatus.textContent = error.message;
  });
});

elements.searchForm.addEventListener("submit", (event) => {
  event.preventDefault();
  runSearch(elements.searchQuery.value || "datasets", elements.includePublic.checked).catch((error) => {
    elements.searchStatus.textContent = error.message;
  });
});

elements.filters.forEach((button) => {
  button.addEventListener("click", () => {
    state.activeFilter = button.dataset.filter;
    elements.filters.forEach((filter) => filter.classList.toggle("active", filter === button));
    renderResults();
  });
});

elements.promptButtons.forEach((button) => {
  button.addEventListener("click", () => {
    const prompt = button.dataset.prompt;
    elements.heroQuery.value = prompt;
    elements.searchQuery.value = prompt;
    runSearch(prompt, true).catch((error) => {
      elements.searchStatus.textContent = error.message;
      showToast(error.message, true);
    });
  });
});

elements.uploadForm.addEventListener("submit", (event) => {
  processUpload(event).catch((error) => renderUploadError(error.message));
});

elements.loadCatalogButton.addEventListener("click", () => {
  loadCatalog().catch((error) => {
    elements.searchStatus.textContent = error.message;
    location.hash = "search";
  });
});

elements.refreshCatalogButton.addEventListener("click", () => {
  loadCatalog().catch((error) => {
    elements.catalogGrid.innerHTML = `<div class="catalog-card error">${escapeHtml(error.message)}</div>`;
  });
});

loadProviderStatus();
renderResults();
renderDetails();
renderCatalogGrid();
