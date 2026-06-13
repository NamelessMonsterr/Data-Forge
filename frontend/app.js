const API_BASE =
  window.DATAFORGE_API_BASE ||
  window.DataForgeConfig?.apiBase ||
  "http://127.0.0.1:8000";

const state = {
  results: [],
  activeFilter: "all",
  activeDataset: null,
  activeTab: "overview",
};

const els = {
  page: document.body.dataset.page || "discover",
  providerStatus: document.querySelector("#providerStatus"),
  heroLlmMode: document.querySelector("#heroLlmMode"),
  heroSearchForm: document.querySelector("#heroSearchForm"),
  heroQuery: document.querySelector("#heroQuery"),
  searchForm: document.querySelector("#searchForm"),
  searchQuery: document.querySelector("#searchQuery"),
  searchIntensity: document.querySelector("#searchIntensity"),
  includePublic: document.querySelector("#includePublic"),
  searchStatus: document.querySelector("#searchStatus"),
  resultContext: document.querySelector("#resultContext"),
  resultsList: document.querySelector("#resultsList"),
  detailsPane: document.querySelector("#detailsPane"),
  uploadForm: document.querySelector("#uploadForm"),
  uploadResult: document.querySelector("#uploadResult"),
  uploadStepper: document.querySelector("#uploadStepper"),
  dropZone: document.querySelector("#dropZone"),
  datasetFile: document.querySelector("#datasetFile"),
  uploadRequest: document.querySelector("#uploadRequest"),
  qualityProfile: document.querySelector("#qualityProfile"),
  refreshCatalogButton: document.querySelector("#refreshCatalogButton"),
  catalogGrid: document.querySelector("#catalogGrid"),
  filters: [...document.querySelectorAll(".filter")],
  promptButtons: [...document.querySelectorAll("[data-prompt]")],
  navLinks: [...document.querySelectorAll("[data-nav]")],
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
  const raw = item.relevance_score ?? item.discovery_score ?? item.quality_score;
  if (raw === undefined || raw === null || raw === "") return "-";
  let n = Number(raw);
  if (!Number.isFinite(n)) return "-";
  if (n > 0 && n <= 1) n *= 100;
  n = Math.max(0, Math.min(100, Math.round(n)));
  return `${n}%`;
}

function fmtInt(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n.toLocaleString() : value ?? "n/a";
}

function metricValue(value) {
  if (value === undefined || value === null || value === "") return "n/a";
  return value;
}

function sourceLabel(item) {
  return item.source || item.provider || "local";
}

function intensityConfig(value) {
  return {
    easy: { label: "Easy", limit: 5, description: "fast local-first scan" },
    medium: { label: "Medium", limit: 8, description: "balanced relevance scan" },
    hard: { label: "Hard", limit: 12, description: "broader source and quality scan" },
    very_hard: { label: "Very hard", limit: 16, description: "deep candidate review" },
    intense: { label: "Intense", limit: 24, description: "maximum recall search pass" },
  }[value || "medium"];
}

function difficultyLabel(item) {
  const quality = Number(item.quality_score ?? item.metadata?.quality_score);
  const rows = Number(item.rows ?? item.metadata?.rows ?? 0);
  if (Number.isFinite(quality)) {
    if (quality >= 95) return "Easy";
    if (quality >= 88) return "Medium";
    if (quality >= 78) return "Hard";
    if (quality >= 65) return "Very hard";
    return "Intense";
  }
  if (rows > 100000) return "Very hard";
  if (rows > 25000) return "Hard";
  return "Medium";
}

function zipUrl(item) {
  const taskId = item.task_id || item.taskId;
  return taskId ? `${API_BASE}/artifacts/${encodeURIComponent(taskId)}/dataset.zip` : "";
}

function showToast(message, isError = false) {
  if (!els.toast) return;
  els.toast.textContent = message;
  els.toast.classList.toggle("error", isError);
  els.toast.classList.add("show");
  window.clearTimeout(showToast.timeoutId);
  showToast.timeoutId = window.setTimeout(() => els.toast.classList.remove("show"), 2200);
}

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function setActiveNav() {
  els.navLinks.forEach((link) => link.classList.toggle("active", link.dataset.nav === els.page));
}

function renderLoadingResults() {
  if (!els.resultsList) return;
  els.resultsList.innerHTML = Array.from({ length: 4 })
    .map(() => `<div class="skeleton"></div>`)
    .join("");
}

function renderResults() {
  if (!els.resultsList) return;
  const filtered = state.results.filter((item) => {
    if (state.activeFilter === "all") return true;
    const source = sourceLabel(item).toLowerCase();
    const provider = String(item.provider || "").toLowerCase();
    const domain = String(item.domain || "").toLowerCase();
    return [source, provider, domain].includes(state.activeFilter);
  });

  els.resultsList.innerHTML = filtered.length
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
  const score = scoreLabel(item);
  const difficulty = difficultyLabel(item);
  return `
    <article class="result-card ${active ? "active" : ""}" data-id="${escapeHtml(item.id)}">
      <div class="result-top">
        <div>
          <h3>${escapeHtml(item.title)}</h3>
          <p>${escapeHtml(summary)}</p>
        </div>
        ${score !== "-" ? `<div class="score">${escapeHtml(score)}</div>` : ""}
      </div>
      <div class="meta-row">
        <span>${escapeHtml(sourceLabel(item))}</span>
        <span>${escapeHtml(fmtInt(item.rows ?? item.metadata?.rows ?? 0))} rows</span>
        <span>${escapeHtml(metricValue(item.columns))} cols</span>
        <span>quality ${escapeHtml(metricValue(item.quality_score))}</span>
        <span class="difficulty ${escapeHtml(difficulty.toLowerCase().replaceAll(" ", "-"))}">${escapeHtml(difficulty)}</span>
      </div>
      ${tags.length ? `<div class="meta-row">${tags.map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`).join("")}</div>` : ""}
    </article>
  `;
}

function renderDetails() {
  const item = state.activeDataset;
  if (!els.detailsPane) return;
  if (!item) {
    els.detailsPane.innerHTML = `
      <div class="empty-state">
        <h3>Select a dataset</h3>
        <p>Open a result to inspect summary, schema, quality, and artifacts.</p>
      </div>
    `;
    return;
  }
  const tabs = ["overview", "card", "schema", "quality", "artifacts", "recommendations"];
  els.detailsPane.innerHTML = `
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
  if (state.activeTab === "card") {
    return `
      <div class="detail-section">
        <h4>Dataset card</h4>
        ${item.dataset_card ? `<pre class="dataset-card">${escapeHtml(item.dataset_card)}</pre>` : "<p>No dataset card yet. Upload and process a dataset to generate one.</p>"}
      </div>
    `;
  }
  if (state.activeTab === "schema") {
    const rows = Object.entries(schema).slice(0, 12);
    return `
      <div class="detail-section">
        <h4>Schema</h4>
        <div class="schema-list">
          ${
            rows.length
              ? rows
                  .map(
                    ([name, meta]) => `
            <div class="schema-row">
              <span>${escapeHtml(name)}</span>
              <strong>${escapeHtml(meta.type || "unknown")}</strong>
            </div>`,
                  )
                  .join("")
              : "<p>No schema available.</p>"
          }
        </div>
      </div>
    `;
  }
  if (state.activeTab === "quality") {
    const metrics = item.quality_metrics || {};
    const dimensionCards = Object.entries(metrics)
      .map(([name, value]) => `<div class="metric"><span>${escapeHtml(name.replaceAll("_", " "))}</span><strong>${escapeHtml(metricValue(value))}</strong></div>`)
      .join("");
    return `
      <div class="detail-section">
        <h4>Quality</h4>
        <div class="metric-grid">
          <div class="metric"><span>Missing values</span><strong>${escapeHtml(metricValue(item.stats?.missing_cells))}</strong></div>
          <div class="metric"><span>Duplicates</span><strong>${escapeHtml(metricValue(item.stats?.duplicate_rows))}</strong></div>
          <div class="metric"><span>Overall quality</span><strong>${escapeHtml(metricValue(item.quality_score))}</strong></div>
          <div class="metric"><span>Semantic score</span><strong>${escapeHtml(metricValue(item.semantic_relevance))}</strong></div>
        </div>
        ${item.quality_narrative ? `<p class="ai-narrative">${escapeHtml(item.quality_narrative)}</p>` : ""}
        ${dimensionCards ? `<h4>Dimension breakdown</h4><div class="metric-grid">${dimensionCards}</div>` : ""}
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
          ${download ? `<a href="${escapeHtml(download)}">Download ZIP package</a>` : ""}
          ${Object.entries(artifacts).map(([name, path]) => `<span>${escapeHtml(name)}: ${escapeHtml(path)}</span>`).join("") || "<p>No artifacts available for public candidates.</p>"}
        </div>
      </div>
    `;
  }
  if (state.activeTab === "recommendations") {
    return `
      <div class="detail-section">
        <h4>Recommendation</h4>
        <p>${escapeHtml(item.recommendation || "Search this dataset to generate a recommendation.")}</p>
      </div>
      ${item.gap_analysis ? `<div class="detail-section"><h4>What's missing / next best action</h4><p>${escapeHtml(item.gap_analysis)}</p></div>` : ""}
    `;
  }
  return `
    <div class="detail-section">
      <h4>Dataset summary</h4>
      <p>${escapeHtml(item.ai_summary || item.description || item.snippet || "No summary available.")}</p>
    </div>
    <div class="detail-section">
      <h4>Metadata</h4>
      <div class="metric-grid">
        <div class="metric"><span>Rows</span><strong>${escapeHtml(fmtInt(item.rows ?? item.metadata?.rows ?? 0))}</strong></div>
        <div class="metric"><span>Columns</span><strong>${escapeHtml(metricValue(item.columns))}</strong></div>
        <div class="metric"><span>Source</span><strong>${escapeHtml(sourceLabel(item))}</strong></div>
        <div class="metric"><span>Provider</span><strong>${escapeHtml(item.provider || "local")}</strong></div>
      </div>
    </div>
  `;
}

async function runSearch(query, includePublic = true, intensity = els.searchIntensity?.value || "medium") {
  const config = intensityConfig(intensity);
  renderLoadingResults();
  if (els.searchStatus) els.searchStatus.textContent = `Understanding query - ${config.label} intensity`;
  showToast(`Understanding query - ${config.label}`);
  await wait(160);
  if (els.searchStatus) els.searchStatus.textContent = `Searching datasets - ${config.description}`;
  const body = await api("/datasets/search", {
    method: "POST",
    body: JSON.stringify({
      query,
      include_public: includePublic,
      limit: config.limit,
      search_intensity: intensity,
    }),
  });
  await wait(160);
  state.results = body.results || [];
  state.activeDataset = state.results[0] || null;
  state.activeTab = "overview";
  if (els.resultContext) els.resultContext.textContent = `Results for "${query}"`;
  if (els.searchStatus) {
    els.searchStatus.textContent = `${body.counts?.returned || 0} results - ${config.label} intensity - local ${body.counts?.local || 0} - public ${body.counts?.public || 0}`;
  }
  showToast("Search complete.");
  renderResults();
  renderDetails();
}

async function loadCatalog() {
  if (els.searchStatus) els.searchStatus.textContent = "Loading local catalog...";
  const body = await api("/datasets/catalog");
  state.results = body.datasets || [];
  state.activeDataset = state.results[0] || null;
  state.activeTab = "overview";
  if (els.resultContext) els.resultContext.textContent = "Local catalog";
  if (els.searchStatus) els.searchStatus.textContent = `${state.results.length} indexed datasets.`;
  renderResults();
  renderDetails();
  renderCatalogGrid();
  showToast("Catalog refreshed.");
}

function renderCatalogGrid() {
  if (!els.catalogGrid) return;
  const items = state.results.filter((item) => sourceLabel(item) === "local_upload");
  els.catalogGrid.innerHTML = items.length
    ? items
        .map(
          (item) => `
      <article class="catalog-card">
        <h3>${escapeHtml(item.title)}</h3>
        <p>${escapeHtml(item.ai_summary || item.description || "No summary available.")}</p>
        <div class="meta-row">
          <span>${escapeHtml(fmtInt(item.rows))} rows</span>
          <span>quality ${escapeHtml(metricValue(item.quality_score))}</span>
          <span class="difficulty ${escapeHtml(difficultyLabel(item).toLowerCase().replaceAll(" ", "-"))}">${escapeHtml(difficultyLabel(item))}</span>
        </div>
      </article>`,
        )
        .join("")
    : `<div class="catalog-card empty-state"><h3>No local datasets yet</h3><p>Upload and process a dataset to populate the catalog.</p></div>`;
}

async function processUpload(event) {
  event.preventDefault();
  const file = els.datasetFile?.files?.[0];
  if (!file) {
    renderUploadError("Choose a CSV, JSON, or JSONL file first.");
    return;
  }
  setStepper(0);
  showToast("Upload started.");
  els.uploadResult?.querySelector("p")?.replaceChildren(document.createTextNode("Uploading dataset..."));
  const content = await file.text();
  setStepper(1);
  await wait(220);
  setStepper(2);
  await wait(220);
  const result = await api("/datasets/process", {
    method: "POST",
    body: JSON.stringify({
      filename: file.name,
      content,
      request: els.uploadRequest?.value || "Analyze this uploaded dataset.",
      quality_profile: els.qualityProfile?.value || "production",
    }),
  });
  setStepper(3);
  await wait(200);
  setStepper(4);
  await wait(200);
  setStepper(5);
  await wait(160);
  setStepper(6);
  showToast("Dataset processed and indexed.");
  const zip = zipUrl(result) || `${API_BASE}/artifacts/${encodeURIComponent(result.task_id)}/dataset.zip`;
  if (!els.uploadResult) return;
  els.uploadResult.innerHTML = `
    <h3>Dataset processed successfully</h3>
    <div class="metric-grid">
      <div class="metric"><span>Rows</span><strong>${escapeHtml(fmtInt(result.summary.rows))}</strong></div>
      <div class="metric"><span>Columns</span><strong>${escapeHtml(metricValue(result.summary.columns))}</strong></div>
      <div class="metric"><span>Quality score</span><strong>${escapeHtml(metricValue(result.quality_report.score))}</strong></div>
      <div class="metric"><span>Target</span><strong>${escapeHtml(result.quality_report.profile || els.qualityProfile?.value || "production")}</strong></div>
      <div class="metric"><span>Duplicates</span><strong>${escapeHtml(metricValue(result.summary.duplicate_rows))}</strong></div>
    </div>
    ${result.quality_report?.narrative ? `<div class="detail-section"><h4>Quality assessment</h4><p class="ai-narrative">${escapeHtml(result.quality_report.narrative)}</p></div>` : ""}
    <div class="hero-actions">
      <a class="button secondary" href="catalog.html">View catalog</a>
      <a class="button primary" href="${escapeHtml(zip)}">Download ZIP</a>
      <a class="button ghost" href="index.html?q=${encodeURIComponent(file.name.replace(/\.[^.]+$/, ""))}">Search similar</a>
    </div>
  `;
}

function setStepper(count) {
  if (!els.uploadStepper) return;
  [...els.uploadStepper.querySelectorAll("div")].forEach((step, index) => {
    step.classList.toggle("done", index < count);
    step.classList.toggle("active", index === count && count < 6);
  });
}

function renderUploadError(message) {
  if (els.uploadResult) els.uploadResult.innerHTML = `<h3 class="error">Upload failed</h3><p>${escapeHtml(message)}</p>`;
  showToast(message, true);
}

async function loadProviderStatus() {
  if (!els.providerStatus) return;
  try {
    const status = await api("/ai/llm/status");
    const active = String(status.active_provider || "").toLowerCase();
    const mode = String(status.mode || "").toLowerCase();
    const live = status.live_llm === true || mode === "live" || mode === "live_provider";
    if (live && active) {
      els.providerStatus.textContent = `AI Status - ${active.toUpperCase()}`;
      els.providerStatus.dataset.mode = "live";
      if (els.heroLlmMode) {
        els.heroLlmMode.textContent = `Live - ${active}`;
        els.heroLlmMode.className = "ok";
      }
    } else {
      els.providerStatus.textContent = "AI Status - Offline Mode";
      els.providerStatus.dataset.mode = "offline";
    }
    els.providerStatus.title = `Retries: ${status.max_retries ?? "n/a"} - Cooldown: ${status.cooldown_seconds ?? "n/a"}s`;
  } catch {
    els.providerStatus.textContent = "AI Status - Offline Mode";
    els.providerStatus.dataset.mode = "offline";
  }
}

function bindDiscoverPage() {
  els.heroSearchForm?.addEventListener("submit", (event) => {
    event.preventDefault();
    if (els.searchQuery) els.searchQuery.value = els.heroQuery?.value || "";
    runSearch(els.heroQuery?.value || "healthcare datasets", true, els.searchIntensity?.value).catch((error) => {
      if (els.searchStatus) els.searchStatus.textContent = error.message;
      showToast(error.message, true);
    });
  });

  els.searchForm?.addEventListener("submit", (event) => {
    event.preventDefault();
    runSearch(els.searchQuery?.value || "datasets", Boolean(els.includePublic?.checked), els.searchIntensity?.value).catch((error) => {
      if (els.searchStatus) els.searchStatus.textContent = error.message;
      showToast(error.message, true);
    });
  });

  els.promptButtons.forEach((button) => {
    button.addEventListener("click", () => {
      const prompt = button.dataset.prompt;
      if (els.heroQuery) els.heroQuery.value = prompt;
      if (els.searchQuery) els.searchQuery.value = prompt;
      runSearch(prompt, true, els.searchIntensity?.value).catch((error) => {
        if (els.searchStatus) els.searchStatus.textContent = error.message;
        showToast(error.message, true);
      });
    });
  });

  els.filters.forEach((button) => {
    button.addEventListener("click", () => {
      state.activeFilter = button.dataset.filter;
      els.filters.forEach((filter) => filter.classList.toggle("active", filter === button));
      renderResults();
    });
  });

  const query = new URLSearchParams(location.search).get("q");
  if (query) {
    if (els.heroQuery) els.heroQuery.value = query;
    if (els.searchQuery) els.searchQuery.value = query;
    runSearch(query, true, els.searchIntensity?.value).catch((error) => showToast(error.message, true));
  } else {
    renderResults();
    renderDetails();
  }
}

function bindUploadPage() {
  els.uploadForm?.addEventListener("submit", (event) => {
    processUpload(event).catch((error) => renderUploadError(error.message));
  });
  if (els.dropZone) {
    ["dragenter", "dragover"].forEach((eventName) =>
      els.dropZone.addEventListener(eventName, (event) => {
        event.preventDefault();
        els.dropZone.classList.add("dragover");
      }),
    );
    ["dragleave", "drop"].forEach((eventName) =>
      els.dropZone.addEventListener(eventName, (event) => {
        event.preventDefault();
        els.dropZone.classList.remove("dragover");
      }),
    );
    els.dropZone.addEventListener("drop", (event) => {
      const file = event.dataTransfer?.files?.[0];
      if (file && els.datasetFile) els.datasetFile.files = event.dataTransfer.files;
    });
  }
}

function bindCatalogPage() {
  els.refreshCatalogButton?.addEventListener("click", () => {
    loadCatalog().catch((error) => {
      if (els.catalogGrid) els.catalogGrid.innerHTML = `<div class="catalog-card error">${escapeHtml(error.message)}</div>`;
    });
  });
  loadCatalog().catch((error) => {
    if (els.catalogGrid) els.catalogGrid.innerHTML = `<div class="catalog-card error">${escapeHtml(error.message)}</div>`;
  });
}

document.addEventListener("keydown", (event) => {
  if (event.key === "/" && document.activeElement?.tagName !== "INPUT" && document.activeElement?.tagName !== "TEXTAREA") {
    event.preventDefault();
    els.searchQuery?.focus();
  }
});

setActiveNav();
loadProviderStatus();
if (els.page === "discover") bindDiscoverPage();
if (els.page === "upload") bindUploadPage();
if (els.page === "catalog") bindCatalogPage();
