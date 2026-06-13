/* DataForge multi-page frontend. One shared script; each page sets
   <body data-page="discover|forge|catalog"> and we initialize only that page. */
(function () {
  "use strict";

  var Api = window.DataForgeApi;
  var API_BASE = (window.DataForgeConfig && window.DataForgeConfig.apiBase) || "";
  var PAGE = document.body.dataset.page;

  /* ---------- intensity model (mirrors backend INTENSITY_PROFILES) ---------- */
  var INTENSITY = {
    easy:      { label: "Easy",      providers: 1, limit: 5,   hint: "Fastest. One source, ~5 candidates - a quick look." },
    medium:    { label: "Medium",    providers: 2, limit: 12,  hint: "Balanced. Two sources, ~12 candidates - the sensible default." },
    hard:      { label: "Hard",      providers: 3, limit: 25,  hint: "Thorough. All sources, ~25 candidates - takes a little longer." },
    very_hard: { label: "Very Hard", providers: 3, limit: 50,  hint: "Deep. All sources, ~50 candidates - for serious sourcing." },
    intense:   { label: "Intense",   providers: 3, limit: 100, hint: "Exhaustive. All sources, ~100 candidates - slowest, widest net." },
  };
  var INTENSITY_KEYS = ["easy", "medium", "hard", "very_hard", "intense"];

  /* ---------- tiny helpers ---------- */
  function $(sel, root) { return (root || document).querySelector(sel); }
  function $all(sel, root) { return [].slice.call((root || document).querySelectorAll(sel)); }

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#039;");
  }
  function fmtInt(value) {
    var n = Number(value);
    return isFinite(n) ? n.toLocaleString() : (value == null ? "n/a" : value);
  }
  function metricValue(v) { return (v === undefined || v === null || v === "") ? "n/a" : v; }
  function sourceLabel(item) { return item.source || item.provider || "local"; }

  function pct(item) {
    var raw = item.relevance_score != null ? item.relevance_score
            : item.discovery_score != null ? item.discovery_score : item.quality_score;
    if (raw === undefined || raw === null || raw === "") return null;
    var n = Number(raw);
    if (!isFinite(n)) return null;
    if (n > 0 && n <= 1) n *= 100;
    return Math.max(0, Math.min(100, Math.round(n)));
  }

  // Map a 0-100 quality/relevance score to the Easy->Intense difficulty band.
  function difficulty(item) {
    var n = pct(item);
    if (n == null) return null;
    if (n >= 90) return "easy";
    if (n >= 75) return "medium";
    if (n >= 55) return "hard";
    if (n >= 35) return "very_hard";
    return "intense";
  }
  function difficultyBadge(item) {
    var d = difficulty(item);
    if (!d) return "";
    return '<span class="diff-badge diff-' + d + '">' + escapeHtml(INTENSITY[d].label) + ' to use</span>';
  }

  function zipUrl(item) {
    var taskId = item.task_id || item.taskId;
    return taskId ? API_BASE.replace(/\/$/, "") + "/artifacts/" + encodeURIComponent(taskId) + "/dataset.zip" : "";
  }

  /* ---------- toast ---------- */
  var toastEl = $("#toast");
  function toast(message, isError) {
    if (!toastEl) return;
    toastEl.textContent = message;
    toastEl.classList.toggle("error", !!isError);
    toastEl.classList.add("show");
    clearTimeout(toast._t);
    toast._t = setTimeout(function () { toastEl.classList.remove("show"); }, 2400);
  }
  function setStatus(text) { var el = $("#statusLine"); if (el) el.textContent = text; }

  /* ---------- AI provider pill (all pages) ---------- */
  function loadProviderStatus() {
    var pill = $("#providerStatus");
    if (!pill || !Api) return;
    Api.llmStatus().then(function (status) {
      var active = String((status && (status.active_provider || (status.provider_priority || [])[0])) || "").toLowerCase();
      var live = status && (status.live_llm === true || status.mode === "live" || (active && active !== "local-deterministic" && active !== "offline"));
      if (live && active) {
        pill.textContent = "AI - " + active.toUpperCase();
        pill.dataset.mode = "live";
      } else {
        pill.textContent = "AI - Offline";
        pill.dataset.mode = "offline";
      }
    }).catch(function () {
      pill.textContent = "AI - Offline";
      pill.dataset.mode = "offline";
    });
  }

  /* ====================================================================== */
  /* DISCOVER PAGE                                                          */
  /* ====================================================================== */
  function initDiscover() {
    var state = { results: [], active: null, tab: "overview", intensity: localStorage.getItem("df_intensity") || "medium" };
    if (INTENSITY_KEYS.indexOf(state.intensity) === -1) state.intensity = "medium";

    var form = $("#searchForm");
    var queryInput = $("#searchQuery");
    var resultsList = $("#resultsList");
    var detailsPane = $("#detailsPane");
    var track = $("#intensityTrack");
    var nameEl = $("#intensityName");
    var hintEl = $("#intensityHint");

    function paintIntensity() {
      $all(".intensity-step", track).forEach(function (btn) {
        btn.setAttribute("aria-pressed", btn.dataset.level === state.intensity ? "true" : "false");
      });
      var prof = INTENSITY[state.intensity];
      if (nameEl) nameEl.textContent = prof.label;
      if (hintEl) hintEl.innerHTML = "<b>" + escapeHtml(prof.label) + ":</b> " + escapeHtml(prof.hint);
    }

    track.addEventListener("click", function (e) {
      var btn = e.target.closest(".intensity-step");
      if (!btn) return;
      state.intensity = btn.dataset.level;
      localStorage.setItem("df_intensity", state.intensity);
      paintIntensity();
    });

    function renderLoading() {
      resultsList.innerHTML = "<div class='skeleton'></div><div class='skeleton'></div><div class='skeleton'></div>";
    }

    function renderResults() {
      if (!state.results.length) {
        resultsList.innerHTML = "<div class='empty-state result-card'><h3>No datasets found</h3><p>Try a broader query or raise the intensity.</p></div>";
        return;
      }
      resultsList.innerHTML = state.results.map(renderCard).join("");
      $all(".result-card[data-id]", resultsList).forEach(function (card) {
        card.addEventListener("click", function () {
          state.active = state.results.find(function (r) { return String(r.id) === card.dataset.id; });
          state.tab = "overview";
          renderResults();
          renderDetails();
        });
      });
    }

    function renderCard(item) {
      var active = state.active && String(state.active.id) === String(item.id);
      var tags = (item.tags || (item.metadata && item.metadata.tags) || []).slice(0, 4);
      var summary = item.ai_summary || item.description || item.snippet || "No summary available.";
      var score = pct(item);
      return "<article class='result-card " + (active ? "active" : "") + "' data-id='" + escapeHtml(item.id) + "'>" +
        "<div class='result-top'><div><h3>" + escapeHtml(item.title) + "</h3><p>" + escapeHtml(summary) + "</p></div>" +
        (score != null ? "<div class='score'>" + score + "%</div>" : "") + "</div>" +
        "<div class='meta-row'><span>" + escapeHtml(sourceLabel(item)) + "</span>" +
        "<span>" + escapeHtml(fmtInt(item.rows != null ? item.rows : (item.metadata && item.metadata.rows) || 0)) + " rows</span>" +
        "<span>quality " + escapeHtml(metricValue(item.quality_score)) + "</span>" + difficultyBadge(item) + "</div>" +
        (tags.length ? "<div class='meta-row'>" + tags.map(function (t) { return "<span class='tag'>" + escapeHtml(t) + "</span>"; }).join("") + "</div>" : "") +
        "</article>";
    }

    function renderDetails() {
      var item = state.active;
      if (!item) {
        detailsPane.innerHTML = "<div class='empty-state'><h3>Select a dataset</h3><p>Open a result to inspect summary, schema, quality, and artifacts.</p></div>";
        return;
      }
      var tabs = ["overview", "schema", "quality", "artifacts", "recommendations"];
      detailsPane.innerHTML = "<h3>" + escapeHtml(item.title) + "</h3>" +
        "<div class='meta-row'><span>" + escapeHtml(sourceLabel(item)) + "</span><span>" + escapeHtml(item.format || item.license || "dataset") + "</span>" + difficultyBadge(item) + "</div>" +
        "<div class='tabs'>" + tabs.map(function (t) { return "<button class='tab " + (state.tab === t ? "active" : "") + "' data-tab='" + t + "' type='button'>" + t + "</button>"; }).join("") + "</div>" +
        renderTab(item);
      $all(".tab", detailsPane).forEach(function (tab) {
        tab.addEventListener("click", function () { state.tab = tab.dataset.tab; renderDetails(); });
      });
    }

    function renderTab(item) {
      if (state.tab === "schema") {
        var rows = Object.entries(item.schema || {}).slice(0, 14);
        return "<div class='detail-section'><h4>Schema</h4><div class='schema-list'>" +
          (rows.length ? rows.map(function (e) { return "<div class='schema-row'><span>" + escapeHtml(e[0]) + "</span><strong>" + escapeHtml((e[1] && e[1].type) || "unknown") + "</strong></div>"; }).join("") : "<p>No schema available.</p>") +
          "</div></div>";
      }
      if (state.tab === "quality") {
        var s = item.stats || {};
        return "<div class='detail-section'><h4>Quality</h4><div class='metric-grid'>" +
          "<div class='metric'><span>Missing values</span><strong>" + escapeHtml(metricValue(s.missing_cells)) + "</strong></div>" +
          "<div class='metric'><span>Duplicates</span><strong>" + escapeHtml(metricValue(s.duplicate_rows)) + "</strong></div>" +
          "<div class='metric'><span>Overall quality</span><strong>" + escapeHtml(metricValue(item.quality_score)) + "</strong></div>" +
          "<div class='metric'><span>Semantic score</span><strong>" + escapeHtml(metricValue(item.semantic_relevance)) + "</strong></div>" +
          "</div></div>";
      }
      if (state.tab === "artifacts") {
        var dl = zipUrl(item);
        return "<div class='detail-section'><h4>Artifacts</h4><div class='artifact-links'>" +
          (dl ? "<a href='" + escapeHtml(dl) + "'>Download ZIP package</a>" : "<p>No artifact for public candidates - forge it first.</p>") +
          "</div></div>";
      }
      if (state.tab === "recommendations") {
        return "<div class='detail-section'><h4>Recommendation</h4><p>" + escapeHtml(item.recommendation || "Search to generate a recommendation.") + "</p></div>";
      }
      return "<div class='detail-section'><h4>Summary</h4><p>" + escapeHtml(item.ai_summary || item.description || item.snippet || "No summary available.") + "</p></div>" +
        "<div class='detail-section'><h4>Metadata</h4><div class='metric-grid'>" +
        "<div class='metric'><span>Rows</span><strong>" + escapeHtml(fmtInt(item.rows != null ? item.rows : (item.metadata && item.metadata.rows) || 0)) + "</strong></div>" +
        "<div class='metric'><span>Columns</span><strong>" + escapeHtml(metricValue(item.columns)) + "</strong></div>" +
        "<div class='metric'><span>Source</span><strong>" + escapeHtml(sourceLabel(item)) + "</strong></div>" +
        "<div class='metric'><span>Provider</span><strong>" + escapeHtml(item.provider || "local") + "</strong></div>" +
        "</div></div>";
    }

    function runSearch(query) {
      renderLoading();
      var prof = INTENSITY[state.intensity];
      setStatus("Searching at " + prof.label + " intensity\u2026 (up to " + prof.providers + " sources, ~" + prof.limit + " candidates)");
      Api.searchDatasets(query, { intensity: state.intensity, includePublic: true }).then(function (body) {
        state.results = (body && body.results) || [];
        state.active = state.results[0] || null;
        state.tab = "overview";
        var counts = (body && body.counts) || {};
        setStatus(state.results.length + " results for \"" + query + "\" - " + prof.label + " intensity" +
          (counts.local != null ? " - local " + counts.local : "") + (counts.public != null ? " - public " + counts.public : ""));
        toast("Search complete.");
        renderResults();
        renderDetails();
      }).catch(function (err) {
        setStatus(err.message || "Search failed.");
        toast(err.message || "Search failed.", true);
        resultsList.innerHTML = "<div class='empty-state result-card error'><h3>Search failed</h3><p>" + escapeHtml(err.message || "") + "</p></div>";
      });
    }

    form.addEventListener("submit", function (e) {
      e.preventDefault();
      runSearch(queryInput.value || "datasets");
    });
    $all("[data-prompt]").forEach(function (chip) {
      chip.addEventListener("click", function () { queryInput.value = chip.dataset.prompt; runSearch(chip.dataset.prompt); });
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "/" && document.activeElement.tagName !== "INPUT" && document.activeElement.tagName !== "TEXTAREA") {
        e.preventDefault(); queryInput.focus();
      }
    });

    paintIntensity();
    renderResults();
    renderDetails();
  }

  /* ====================================================================== */
  /* FORGE PAGE                                                             */
  /* ====================================================================== */
  function initForge() {
    var form = $("#uploadForm");
    var fileInput = $("#datasetFile");
    var dropZone = $("#dropZone");
    var dropHint = $("#dropHint");
    var requestInput = $("#uploadRequest");
    var stepper = $("#uploadStepper");
    var resultPane = $("#uploadResult");
    var btn = $("#processBtn");

    function setStepper(count) {
      $all("div", stepper).forEach(function (step, i) {
        step.classList.toggle("done", i < count);
        step.classList.toggle("active", i === count && count < 6);
      });
    }
    function wait(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

    fileInput.addEventListener("change", function () {
      if (fileInput.files[0]) dropHint.textContent = fileInput.files[0].name;
    });
    ["dragenter", "dragover"].forEach(function (ev) {
      dropZone.addEventListener(ev, function (e) { e.preventDefault(); dropZone.classList.add("dragover"); });
    });
    ["dragleave", "drop"].forEach(function (ev) {
      dropZone.addEventListener(ev, function (e) { e.preventDefault(); dropZone.classList.remove("dragover"); });
    });
    dropZone.addEventListener("drop", function (e) {
      var f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
      if (f) { fileInput.files = e.dataTransfer.files; dropHint.textContent = f.name; }
    });

    function fail(msg) {
      resultPane.innerHTML = "<h3 class='error'>Forge failed</h3><p>" + escapeHtml(msg) + "</p>";
      toast(msg, true);
      btn.disabled = false;
    }

    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var file = fileInput.files[0];
      if (!file) { fail("Choose a CSV, JSON, or JSONL file first."); return; }
      btn.disabled = true;
      setStepper(0);
      toast("Upload started.");
      file.text().then(function (content) {
        setStepper(1);
        return wait(180).then(function () {
          setStepper(2);
          return Api.processDataset({
            filename: file.name,
            content: content,
            request: requestInput.value || "Analyze this uploaded dataset.",
          });
        });
      }).then(function (result) {
        setStepper(4); return wait(220).then(function () { setStepper(6); return result; });
      }).then(function (result) {
        toast("Dataset forged and indexed.");
        var zip = zipUrl(result) || (result.task_id ? API_BASE.replace(/\/$/, "") + "/artifacts/" + encodeURIComponent(result.task_id) + "/dataset.zip" : "");
        var summary = result.summary || {};
        var quality = result.quality_report || {};
        var ingestion = result.ingestion || {};
        resultPane.innerHTML = "<h3>Dataset forged successfully</h3>" +
          "<div class='metric-grid'>" +
          "<div class='metric'><span>Rows</span><strong>" + escapeHtml(fmtInt(summary.rows)) + "</strong></div>" +
          "<div class='metric'><span>Columns</span><strong>" + escapeHtml(metricValue(summary.columns)) + "</strong></div>" +
          "<div class='metric'><span>Quality score</span><strong>" + escapeHtml(metricValue(quality.score)) + "</strong></div>" +
          "<div class='metric'><span>Duplicates</span><strong>" + escapeHtml(metricValue(summary.duplicate_rows)) + "</strong></div>" +
          "</div>" +
          "<div class='detail-section'><h4>Summary</h4><p>" + escapeHtml((ingestion.filename || file.name) + " was normalized, scored, packaged, and indexed.") + "</p></div>" +
          "<div class='hero-actions'>" +
          (zip ? "<a class='button primary' href='" + escapeHtml(zip) + "'>Download ZIP</a>" : "") +
          "<a class='button ghost' href='catalog.html'>View in catalog</a></div>";
        btn.disabled = false;
      }).catch(function (err) { fail(err.message || "Processing failed."); });
    });
  }

  /* ====================================================================== */
  /* CATALOG PAGE                                                           */
  /* ====================================================================== */
  function initCatalog() {
    var grid = $("#catalogGrid");
    var refreshBtn = $("#refreshCatalogButton");

    function render(items) {
      if (!items.length) {
        grid.innerHTML = "<div class='catalog-card empty-state'><h3>No datasets yet</h3><p>Forge a dataset to populate your catalog.</p></div>";
        return;
      }
      grid.innerHTML = items.map(function (item) {
        return "<article class='catalog-card'><h3>" + escapeHtml(item.title || "Untitled") + "</h3>" +
          "<p>" + escapeHtml(item.ai_summary || item.description || "No summary available.") + "</p>" +
          "<div class='meta-row'><span>" + escapeHtml(fmtInt(item.rows)) + " rows</span>" +
          "<span>quality " + escapeHtml(metricValue(item.quality_score)) + "</span>" + difficultyBadge(item) + "</div>" +
          (zipUrl(item) ? "<div class='hero-actions'><a class='button ghost' href='" + escapeHtml(zipUrl(item)) + "'>Download ZIP</a></div>" : "") +
          "</article>";
      }).join("");
    }

    function load() {
      grid.innerHTML = "<div class='skeleton'></div><div class='skeleton'></div><div class='skeleton'></div>";
      setStatus("Loading catalog\u2026");
      Api.catalog().then(function (body) {
        var items = (body && (body.datasets || body.results)) || [];
        setStatus(items.length + " indexed datasets.");
        render(items);
      }).catch(function (err) {
        setStatus(err.message || "Failed to load catalog.");
        grid.innerHTML = "<div class='catalog-card empty-state error'><h3>Failed to load</h3><p>" + escapeHtml(err.message || "") + "</p></div>";
      });
    }

    if (refreshBtn) refreshBtn.addEventListener("click", load);
    load();
  }

  /* ---------- boot ---------- */
  loadProviderStatus();
  if (PAGE === "discover") initDiscover();
  else if (PAGE === "forge") initForge();
  else if (PAGE === "catalog") initCatalog();
})();
