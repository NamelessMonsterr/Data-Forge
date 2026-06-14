/* DataForge multi-page frontend. One shared script; each page sets
   <body data-page="discover|forge|catalog"> and we initialize only that page. */
(function () {
  "use strict";

  var Api = window.DataForgeApi;
  var API_BASE = (window.DataForgeConfig && window.DataForgeConfig.apiBase) || "";
  var PAGE = document.body.dataset.page;

  /* ---------- intensity model (mirrors backend INTENSITY_PROFILES) ---------- */
  var INTENSITY = {
    easy:      { label: "Easy",      providers: 1, limit: 5,   passes: 1, hint: "Fastest. One provider, one query pass, ~5 candidates." },
    medium:    { label: "Medium",    providers: 2, limit: 12,  passes: 1, hint: "Balanced. Two providers, one query pass, ~12 candidates." },
    hard:      { label: "Hard",      providers: 3, limit: 25,  passes: 2, hint: "Thorough. Portal search plus generic web discovery and a broader second query pass." },
    very_hard: { label: "Very Hard", providers: 4, limit: 50,  passes: 3, hint: "Deep. HuggingFace, web, data.gov, and Kaggle with three query passes." },
    intense:   { label: "Intense",   providers: 4, limit: 100, passes: 4, hint: "Exhaustive. All providers plus generic web search, four broadened query passes - slowest and deepest." },
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
  function sourceUrl(item) { return item && (item.url || item.source_url || item.dataset_url || item.homepage || ""); }
  function safeHref(raw) {
    if (!raw) return "";
    try {
      var text = String(raw).trim();
      if (!text || /[\u0000-\u001f\u007f]/.test(text) || text.indexOf("//") === 0) return "";
      var url = new URL(text, window.location.origin);
      if (url.protocol !== "http:" && url.protocol !== "https:") return "";
      if (url.origin === window.location.origin && text.charAt(0) !== "/") return "";
      return url.href;
    } catch (err) {
      return "";
    }
  }
  function responseItems(body) {
    if (Array.isArray(body)) return body;
    if (!body || typeof body !== "object") return [];
    if (Array.isArray(body.results)) return body.results;
    if (Array.isArray(body.items)) return body.items;
    if (Array.isArray(body.datasets)) return body.datasets;
    if (body.data && Array.isArray(body.data.items)) return body.data.items;
    if (body.data && Array.isArray(body.data.results)) return body.data.results;
    return [];
  }
  function sourceLink(item, label) {
    var url = safeHref(sourceUrl(item));
    if (!url) return "";
    return "<a class='source-link' href='" + escapeHtml(url) + "' target='_blank' rel='noopener noreferrer'>" +
      escapeHtml(label || "Open source dataset") + "</a>";
  }

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

  function showApiBaseWarning() {
    var cfg = window.DataForgeConfig || {};
    if (!cfg.apiBase || !cfg.defaultApiBase) return;
    if (cfg.apiBase === cfg.defaultApiBase || cfg.apiBaseSource === "same-origin" || cfg.apiBaseSource === "meta") return;
    var banner = document.createElement("div");
    banner.className = "api-base-warning";
    banner.setAttribute("role", "status");
    banner.innerHTML =
      "<strong>External API target active</strong>" +
      "<span>Requests and session cookies are going to " + escapeHtml(cfg.apiBase) +
      " via " + escapeHtml(cfg.apiBaseSource || "override") + " configuration.</span>";
    document.body.insertBefore(banner, document.body.firstChild);
  }

  /* ---------- AI provider pill (all pages) ---------- */
  function loadProviderStatus() {
    var pill = $("#providerStatus");
    if (!pill || !Api) return;
    Api.llmStatus().then(function (status) {
      status = status || {};
      var active = String(
        status.active_provider ||
        status.provider ||
        status.name ||
        (status.provider_priority || [])[0] ||
        ""
      ).toLowerCase();
      var offline = !active ||
        active === "local-deterministic" ||
        active === "offline" ||
        active === "local" ||
        active.indexOf("determin") > -1;
      var live = status.live_llm === true ||
        status.mode === "live" ||
        status.status === "live" ||
        status.available === true ||
        !offline;
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
    var state = { results: [], active: null, tab: "overview", intensity: localStorage.getItem("df_intensity") || "medium", query: "" };
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

    function searchWarnings(body) {
      var warnings = [];
      if (body && Array.isArray(body.warnings)) warnings = warnings.concat(body.warnings);
      if (body && body.discovery && Array.isArray(body.discovery.errors)) {
        body.discovery.errors.forEach(function (warning) {
          if (warnings.indexOf(warning) === -1) warnings.push(warning);
        });
      }
      return warnings;
    }

    function renderSearchFailure(query, warnings, discovery) {
      var providerText = discovery && discovery.providers_used && discovery.providers_used.length
        ? "Providers tried: " + discovery.providers_used.join(", ")
        : "No provider returned usable results.";
      resultsList.innerHTML = "<div class='empty-state result-card search-warning'><h3>Search did not finish cleanly</h3>" +
        "<p>DataForge could not retrieve public datasets for \"" + escapeHtml(query) + "\". " + escapeHtml(providerText) + "</p>" +
        (warnings.length ? "<ul>" + warnings.slice(0, 4).map(function (warning) {
          return "<li>" + escapeHtml(warning) + "</li>";
        }).join("") + "</ul>" : "") +
        "<p class='muted'>Try a lower intensity, a broader query, or check live provider credentials/network.</p></div>";
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
      $all(".source-link", resultsList).forEach(function (link) {
        link.addEventListener("click", function (event) { event.stopPropagation(); });
      });
      $all(".save-public", resultsList).forEach(function (btn) {
        btn.addEventListener("click", function (event) {
          event.stopPropagation();
          savePublic(btn.dataset.id, btn);
        });
      });
    }

    function canSavePublic(item) {
      return !!(item && sourceUrl(item) && item.source !== "local_upload" && item.provider !== "local");
    }

    function savePublic(id, btn) {
      var item = state.results.find(function (r) { return String(r.id) === String(id); });
      if (!item || !Api.savePublicDataset) return;
      if (btn) {
        btn.disabled = true;
        btn.textContent = "Saving...";
      }
      Api.savePublicDataset(item, state.query).then(function (body) {
        var saved = body && body.dataset;
        toast("Saved to catalog.");
        if (saved) {
          item.saved_dataset_id = saved.id;
          item.saved = true;
          if (state.active && String(state.active.id) === String(item.id)) state.active = item;
        }
        renderResults();
        renderDetails();
      }).catch(function (err) {
        toast(err.message || "Could not save dataset.", true);
        if (btn) {
          btn.disabled = false;
          btn.textContent = "Save to catalog";
        }
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
        sourceLink(item, "Open dataset") +
        (canSavePublic(item) ? "<button class='button ghost save-public' type='button' data-id='" + escapeHtml(item.id) + "'>" + (item.saved ? "Saved" : "Save to catalog") + "</button>" : "") +
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
        sourceLink(item, "Open original source") +
        (canSavePublic(item) ? "<button class='button ghost save-public detail-save' type='button' data-id='" + escapeHtml(item.id) + "'>" + (item.saved ? "Saved to catalog" : "Save to catalog") + "</button>" : "") +
        "<div class='tabs'>" + tabs.map(function (t) { return "<button class='tab " + (state.tab === t ? "active" : "") + "' data-tab='" + t + "' type='button'>" + t + "</button>"; }).join("") + "</div>" +
        renderTab(item);
      $all(".tab", detailsPane).forEach(function (tab) {
        tab.addEventListener("click", function () { state.tab = tab.dataset.tab; renderDetails(); });
      });
      $all(".save-public", detailsPane).forEach(function (btn) {
        btn.addEventListener("click", function (event) {
          event.stopPropagation();
          savePublic(btn.dataset.id, btn);
        });
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
        var src = sourceLink(item, "Open source dataset");
        return "<div class='detail-section'><h4>Artifacts</h4><div class='artifact-links'>" +
          (dl ? "<a href='" + escapeHtml(dl) + "'>Download ZIP package</a>" : "") +
          (src || "") +
          (!dl && !src ? "<p>No artifact or source link available for this result.</p>" : "") +
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
      state.query = query;
      renderLoading();
      var prof = INTENSITY[state.intensity];
      setStatus("Searching at " + prof.label + " intensity... (" + prof.providers + " sources, " + prof.passes + " query pass" + (prof.passes === 1 ? "" : "es") + ", up to ~" + prof.limit + " returned)");
      Api.searchDatasets(query, { intensity: state.intensity, includePublic: true, limit: prof.limit }).then(function (body) {
        state.results = responseItems(body);
        state.active = state.results[0] || null;
        state.tab = "overview";
        var counts = (body && body.counts) || {};
        var warnings = searchWarnings(body);
        var status = (body && body.search_status) || (warnings.length ? "partial" : "complete");
        var prefix = status === "failed" ? "Search failed" :
          status === "partial" ? "Partial results" :
          status === "disabled" ? "Public discovery disabled" :
          status === "empty" ? "No matches" : "Search complete";
        setStatus(prefix + ": " + state.results.length + " results for \"" + query + "\" - " + prof.label + " intensity" +
          (counts.local != null ? " - local " + counts.local : "") +
          (counts.public != null ? " - public " + counts.public : "") +
          (counts.local == null && counts.public == null && body && body.total != null ? " - total " + body.total : "") +
          (warnings.length ? " - " + warnings.length + " provider warning" + (warnings.length === 1 ? "" : "s") : ""));
        if (status === "failed") {
          toast("Search failed at provider level.", true);
          renderSearchFailure(query, warnings, body && body.discovery);
        } else {
          toast(status === "partial" ? "Partial results: some providers failed." :
            status === "disabled" ? "Public discovery disabled; showing local results." :
            status === "empty" ? "No matching datasets found." : "Search complete.",
            status === "partial");
          renderResults();
        }
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
        var items = responseItems(body);
        setStatus((body && body.total != null ? body.total : items.length) + " indexed datasets.");
        render(items);
      }).catch(function (err) {
        setStatus(err.message || "Failed to load catalog.");
        grid.innerHTML = "<div class='catalog-card empty-state error'><h3>Failed to load</h3><p>" + escapeHtml(err.message || "") + "</p></div>";
      });
    }

    if (refreshBtn) refreshBtn.addEventListener("click", load);
    load();
  }

  /* ====================================================================== */
  /* SETTINGS PAGE (provider-key vault)                                     */
  /* ====================================================================== */
  function initSettings() {
    var listEl = $("#providerList");
    if (!listEl) return;

    function pill(p) {
      return p.configured
        ? "<span class='pill ok'>Configured</span>"
        : "<span class='pill'>Not configured</span>";
    }

    function cardHtml(p) {
      var keyPlaceholder = p.configured ? "Saved - enter a new value to replace" : "";
      var secretField = p.requires_secret
        ? "<div class='field'><label>" + escapeHtml(p.secret_label || "Secret") + "</label>" +
          "<input type='password' class='prov-secret' data-provider='" + escapeHtml(p.provider) +
          "' autocomplete='off' placeholder='" + (p.has_secret ? "Saved - enter to replace" : "") + "' /></div>"
        : "";
      return "<article class='panel provider-card'>" +
        "<div class='provider-head'><div><h3>" + escapeHtml(p.label) + "</h3>" +
        "<p class='provider-sub'>" + escapeHtml(p.provider) +
        (p.updated_at ? " - updated " + escapeHtml(String(p.updated_at).slice(0, 10)) : "") + "</p></div>" +
        pill(p) + "</div>" +
        "<div class='field'><label>" + escapeHtml(p.api_key_label || "API key") + "</label>" +
        "<input type='password' class='prov-key' data-provider='" + escapeHtml(p.provider) +
        "' autocomplete='off' placeholder='" + escapeHtml(keyPlaceholder) + "' /></div>" +
        secretField +
        "<div class='hero-actions'>" +
        "<button class='button primary prov-save' data-provider='" + escapeHtml(p.provider) + "' type='button'>Save</button>" +
        (p.configured ? "<button class='button ghost prov-remove' data-provider='" + escapeHtml(p.provider) + "' type='button'>Remove</button>" : "") +
        "</div></article>";
    }

    function fieldValue(cls, prov) {
      var el = listEl.querySelector("." + cls + "[data-provider='" + prov + "']");
      return el ? (el.value || "").trim() : "";
    }

    function wire() {
      $all(".prov-save", listEl).forEach(function (btn) {
        btn.addEventListener("click", function () {
          var prov = btn.dataset.provider;
          var apiKey = fieldValue("prov-key", prov);
          var secret = fieldValue("prov-secret", prov);
          if (!apiKey) { toast("Enter the key first.", true); return; }
          btn.disabled = true;
          Api.setProviderKey(prov, apiKey, secret).then(function () {
            toast(prov + " saved.");
            load();
          }).catch(function (err) {
            btn.disabled = false;
            toast((err && err.message) || "Save failed.", true);
          });
        });
      });
      $all(".prov-remove", listEl).forEach(function (btn) {
        btn.addEventListener("click", function () {
          var prov = btn.dataset.provider;
          btn.disabled = true;
          Api.deleteProviderKey(prov).then(function () {
            toast(prov + " removed.");
            load();
          }).catch(function (err) {
            btn.disabled = false;
            toast((err && err.message) || "Remove failed.", true);
          });
        });
      });
    }

    function render(providers) {
      if (!providers.length) {
        listEl.innerHTML = "<div class='panel empty-state'><h3>No providers available</h3></div>";
        return;
      }
      listEl.innerHTML = providers.map(cardHtml).join("");
      wire();
    }

    function load() {
      listEl.innerHTML = "<div class='skeleton'></div><div class='skeleton'></div>";
      setStatus("Loading provider settings...");
      Api.providerSettings().then(function (body) {
        var providers = (body && body.providers) || [];
        var configured = providers.filter(function (p) { return p.configured; }).length;
        setStatus(configured + " of " + providers.length + " providers configured.");
        render(providers);
      }).catch(function (err) {
        setStatus((err && err.message) || "Failed to load settings.");
        listEl.innerHTML = "<div class='panel empty-state error'><h3>Failed to load</h3><p>" + escapeHtml((err && err.message) || "") + "</p></div>";
      });
    }

    load();
  }

  /* ====================================================================== */
  /* TEAMS PAGE (teams, roles, resource sharing)                            */
  /* ====================================================================== */
  function initTeams() {
    var sidebar = $("#teamList");
    var detail = $("#teamDetail");
    var form = $("#newTeamForm");
    var nameInput = $("#newTeamName");
    if (!sidebar || !detail) return;

    var RESOURCE_TYPES = ["dataset", "project", "run"];
    var ASSIGNABLE_ROLES = ["viewer", "member", "admin"];
    var state = { teams: [], activeId: null, members: [], shares: [], myRole: null, sharesSupported: true };

    function errMsg(err, fallback) { return (err && err.message) || fallback; }
    function isGlobalAdmin() { return !!(AUTH.me && AUTH.me.role === "admin"); }
    function isManager() { return isGlobalAdmin() || state.myRole === "owner" || state.myRole === "admin"; }
    function activeTeam() { return state.teams.find(function (t) { return t.id === state.activeId; }) || null; }
    function initials(text) {
      var s = String(text == null ? "?" : text).trim();
      var parts = s.split(/\s+/).filter(Boolean);
      if (parts.length >= 2) return (parts[0].charAt(0) + parts[1].charAt(0)).toUpperCase();
      return (s.slice(0, 2) || "?").toUpperCase();
    }
    function roleBadge(role) {
      var r = role || "member";
      return "<span class='role-badge role-" + escapeHtml(r) + "'>" + escapeHtml(r) + "</span>";
    }

    /* ---- team sidebar ---- */
    function renderTeamList() {
      if (!state.teams.length) {
        sidebar.innerHTML = "<div class='team-empty'>No teams yet.<br/>Create one above to get started.</div>";
        return;
      }
      sidebar.innerHTML = state.teams.map(function (t) {
        var active = t.id === state.activeId;
        var mine = AUTH.me && t.owner_id === AUTH.me.id;
        return "<button type='button' class='team-item " + (active ? "active" : "") + "' data-id='" + escapeHtml(t.id) + "'>" +
          "<span class='team-avatar'>" + escapeHtml(initials(t.name)) + "</span>" +
          "<span class='team-item-main'><span class='team-item-name'>" + escapeHtml(t.name) + "</span>" +
          "<span class='team-item-sub'>" + (mine ? "You own this" : "Member") + "</span></span>" +
          (mine ? "<span class='team-dot' title='Owner'></span>" : "") +
          "</button>";
      }).join("");
      $all(".team-item", sidebar).forEach(function (btn) {
        btn.addEventListener("click", function () { selectTeam(btn.dataset.id); });
      });
    }

    /* ---- detail ---- */
    function renderDetail() {
      var team = activeTeam();
      if (!team) {
        detail.innerHTML = "<div class='empty-state'><h3>Select a team</h3><p>Pick a team on the left, or create one to manage members and shares.</p></div>";
        return;
      }
      var manager = isManager();
      var canDelete = isGlobalAdmin() || (AUTH.me && team.owner_id === AUTH.me.id);
      var count = state.members.length;
      detail.innerHTML =
        "<div class='team-detail-head'>" +
          "<span class='team-hero-avatar'>" + escapeHtml(initials(team.name)) + "</span>" +
          "<div class='team-detail-title'><h2>" + escapeHtml(team.name) + "</h2>" +
          "<div class='team-detail-meta'>" + roleBadge(state.myRole || (isGlobalAdmin() ? "admin" : "member")) +
          "<span class='muted-mono'>" + count + " member" + (count === 1 ? "" : "s") + "</span></div></div>" +
          (canDelete ? "<button type='button' class='button ghost danger' id='deleteTeamBtn'>Delete team</button>" : "") +
        "</div>" +
        renderMembersSection(manager) +
        renderSharesSection(manager);
      wireDetail();
    }

    function renderMembersSection(manager) {
      var rows = state.members.map(function (m) {
        var label = m.email || m.user_id;
        var isOwnerRow = m.team_role === "owner";
        var me = AUTH.me && m.user_id === AUTH.me.id;
        var controls;
        if (manager && !isOwnerRow) {
          controls = "<select class='role-select' data-user='" + escapeHtml(m.user_id) + "'>" +
            ASSIGNABLE_ROLES.map(function (r) {
              return "<option value='" + r + "'" + (m.team_role === r ? " selected" : "") + ">" + r + "</option>";
            }).join("") + "</select>" +
            "<button type='button' class='icon-btn remove-member' data-user='" + escapeHtml(m.user_id) + "' title='Remove member'>\u00d7</button>";
        } else {
          controls = roleBadge(m.team_role);
        }
        return "<div class='member-row'>" +
          "<span class='member-avatar'>" + escapeHtml(initials(label)) + "</span>" +
          "<span class='member-id'>" + escapeHtml(label) + (me ? " <span class='you-tag'>you</span>" : "") + "</span>" +
          "<span class='member-actions'>" + controls + "</span></div>";
      }).join("");
      var addForm = manager ?
        "<form class='member-add' id='addMemberForm' autocomplete='off'>" +
          "<input type='email' id='addMemberEmail' placeholder='teammate@email.com' />" +
          "<select id='addMemberRole'>" + ASSIGNABLE_ROLES.map(function (r) {
            return "<option value='" + r + "'" + (r === "member" ? " selected" : "") + ">" + r + "</option>";
          }).join("") + "</select>" +
          "<button type='submit' class='button primary'>Add</button>" +
        "</form>" : "";
      return "<section class='team-section'><div class='section-title'><h3>Members</h3>" +
        "<span class='muted-mono'>viewer &lt; member &lt; admin &lt; owner</span></div>" +
        "<div class='roster'>" + (rows || "<div class='share-empty'>No members yet.</div>") + "</div>" + addForm + "</section>";
    }

    function renderSharesSection(manager) {
      var composer = manager ?
        "<form class='share-composer' id='shareForm' autocomplete='off'>" +
          "<select id='shareType'>" + RESOURCE_TYPES.map(function (t) { return "<option value='" + t + "'>" + t + "</option>"; }).join("") + "</select>" +
          "<input type='text' id='shareId' placeholder='resource id (e.g. dataset-abc123)' />" +
          "<select id='sharePerm'><option value='view'>view</option><option value='edit'>edit</option></select>" +
          "<button type='submit' class='button primary'>Share</button>" +
        "</form>" :
        "<p class='muted'>Only team owners and admins can manage shares.</p>";
      var list;
      if (!state.sharesSupported) {
        list = "<p class='muted share-note'>Wire the optional <code>GET /teams/{id}/shares</code> endpoint to list active shares here. Sharing and revoking still work without it.</p>";
      } else if (!state.shares.length) {
        list = "<div class='share-empty'>Nothing shared with this team yet.</div>";
      } else {
        list = "<div class='share-list'>" + state.shares.map(function (s) {
          return "<div class='share-row'>" +
            "<span class='share-type share-" + escapeHtml(s.resource_type) + "'>" + escapeHtml(s.resource_type) + "</span>" +
            "<span class='share-id'>" + escapeHtml(s.resource_id) + "</span>" +
            "<span class='perm-badge perm-" + escapeHtml(s.permission) + "'>" + escapeHtml(s.permission) + "</span>" +
            (manager ? "<button type='button' class='icon-btn unshare' data-type='" + escapeHtml(s.resource_type) + "' data-rid='" + escapeHtml(s.resource_id) + "' title='Revoke share'>\u00d7</button>" : "") +
            "</div>";
        }).join("") + "</div>";
      }
      return "<section class='team-section'><div class='section-title'><h3>Shared resources</h3>" +
        "<span class='muted-mono'>datasets, projects, runs \u2014 keys never shared</span></div>" +
        composer + list + "</section>";
    }

    function wireDetail() {
      var del = $("#deleteTeamBtn");
      if (del) del.addEventListener("click", function () {
        var team = activeTeam();
        if (!team || !window.confirm("Delete team \u201c" + team.name + "\u201d? This removes all its members and shares.")) return;
        del.disabled = true;
        Api.deleteTeam(team.id).then(function () {
          toast("Team deleted.");
          state.activeId = null;
          loadTeams();
        }).catch(function (err) { del.disabled = false; toast(errMsg(err, "Delete failed."), true); });
      });

      var addForm = $("#addMemberForm");
      if (addForm) addForm.addEventListener("submit", function (e) {
        e.preventDefault();
        var email = ($("#addMemberEmail").value || "").trim();
        var role = $("#addMemberRole").value;
        if (!email) { toast("Enter an email.", true); return; }
        Api.addMember(state.activeId, { email: email, role: role }).then(function () {
          toast("Member added.");
          selectTeam(state.activeId);
        }).catch(function (err) { toast(errMsg(err, "Could not add member."), true); });
      });

      $all(".role-select", detail).forEach(function (sel) {
        sel.addEventListener("change", function () {
          var uid = sel.dataset.user;
          var member = state.members.find(function (m) { return m.user_id === uid; });
          Api.addMember(state.activeId, { userId: uid, email: member && member.email, role: sel.value }).then(function () {
            toast("Role updated.");
            selectTeam(state.activeId);
          }).catch(function (err) { toast(errMsg(err, "Could not update role."), true); selectTeam(state.activeId); });
        });
      });

      $all(".remove-member", detail).forEach(function (btn) {
        btn.addEventListener("click", function () {
          if (!window.confirm("Remove this member from the team?")) return;
          Api.removeMember(state.activeId, btn.dataset.user).then(function () {
            toast("Member removed.");
            selectTeam(state.activeId);
          }).catch(function (err) { toast(errMsg(err, "Could not remove member."), true); });
        });
      });

      var shareForm = $("#shareForm");
      if (shareForm) shareForm.addEventListener("submit", function (e) {
        e.preventDefault();
        var rid = ($("#shareId").value || "").trim();
        if (!rid) { toast("Enter a resource id.", true); return; }
        Api.shareResource(state.activeId, $("#shareType").value, rid, $("#sharePerm").value).then(function () {
          toast("Resource shared.");
          selectTeam(state.activeId);
        }).catch(function (err) { toast(errMsg(err, "Share failed."), true); });
      });

      $all(".unshare", detail).forEach(function (btn) {
        btn.addEventListener("click", function () {
          Api.unshareResource(state.activeId, btn.dataset.type, btn.dataset.rid).then(function () {
            toast("Share revoked.");
            selectTeam(state.activeId);
          }).catch(function (err) { toast(errMsg(err, "Revoke failed."), true); });
        });
      });
    }

    function loadShares(id) {
      if (!Api.listShares) { state.sharesSupported = false; state.shares = []; return Promise.resolve(); }
      return Api.listShares(id).then(function (body) {
        state.sharesSupported = true;
        state.shares = (body && (body.shares || body)) || [];
      }).catch(function (err) {
        if (err && (err.status === 404 || err.status === 405)) { state.sharesSupported = false; }
        state.shares = [];
      });
    }

    function selectTeam(id) {
      state.activeId = id;
      renderTeamList();
      detail.innerHTML = "<div class='skeleton'></div><div class='skeleton'></div>";
      Api.listMembers(id).then(function (body) {
        state.members = (body && (body.members || body)) || [];
        var mine = AUTH.me && state.members.find(function (m) { return m.user_id === AUTH.me.id; });
        state.myRole = mine ? mine.team_role : null;
        return loadShares(id);
      }).then(function () {
        renderDetail();
      }).catch(function (err) {
        detail.innerHTML = "<div class='empty-state error'><h3>Could not load team</h3><p>" + escapeHtml(errMsg(err, "")) + "</p></div>";
      });
    }

    function loadTeams() {
      sidebar.innerHTML = "<div class='skeleton'></div><div class='skeleton'></div>";
      setStatus("Loading your teams\u2026");
      Api.listTeams().then(function (body) {
        state.teams = (body && (body.teams || body)) || [];
        setStatus(state.teams.length + " team" + (state.teams.length === 1 ? "" : "s") + ".");
        renderTeamList();
        if (state.activeId && state.teams.some(function (t) { return t.id === state.activeId; })) {
          selectTeam(state.activeId);
        } else {
          state.activeId = null;
          renderDetail();
        }
      }).catch(function (err) {
        setStatus(errMsg(err, "Failed to load teams."));
        sidebar.innerHTML = "<div class='team-empty error'>" + escapeHtml(errMsg(err, "Failed to load.")) + "</div>";
      });
    }

    if (form) form.addEventListener("submit", function (e) {
      e.preventDefault();
      var name = (nameInput.value || "").trim();
      if (!name) { toast("Enter a team name.", true); return; }
      var btn = $("#createTeamBtn");
      if (btn) btn.disabled = true;
      Api.createTeam(name).then(function (team) {
        toast("Team created.");
        nameInput.value = "";
        if (btn) btn.disabled = false;
        state.activeId = (team && team.id) || null;
        loadTeams();
      }).catch(function (err) { if (btn) btn.disabled = false; toast(errMsg(err, "Could not create team."), true); });
    });

    loadTeams();
  }

  /* ====================================================================== */
  /* AUTH PAGE                                                              */
  /* ====================================================================== */
  function initAuth() {
    var tabLogin = $("#tabLogin");
    var tabRegister = $("#tabRegister");
    var form = $("#authForm");
    var emailInput = $("#authEmail");
    var passwordInput = $("#authPassword");
    var submitBtn = $("#authSubmit");
    var msg = $("#authMessage");
    var subtitle = $("#authSubtitle");
    var hint = $("#authHint");
    var mode = "login";

    var params = new URLSearchParams(location.search);
    var next = safeNext(params.get("next"));

    function setMsg(text, kind) {
      if (!msg) return;
      msg.textContent = text || "";
      msg.className = "auth-message" + (kind ? " " + kind : "");
    }
    function setMode(m) {
      mode = m;
      tabLogin.setAttribute("aria-pressed", m === "login" ? "true" : "false");
      tabRegister.setAttribute("aria-pressed", m === "register" ? "true" : "false");
      submitBtn.textContent = m === "login" ? "Log in" : "Create account";
      subtitle.textContent = m === "login"
        ? "Sign in to reach your datasets, catalog, and the forge."
        : "Create an account to start forging your own private datasets.";
      if (hint) hint.textContent = m === "register" ? "Use a real email and a password of at least 8 characters." : "";
      passwordInput.setAttribute("autocomplete", m === "login" ? "current-password" : "new-password");
      setMsg("");
    }
    tabLogin.addEventListener("click", function () { setMode("login"); });
    tabRegister.addEventListener("click", function () { setMode("register"); });

    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var email = (emailInput.value || "").trim();
      var password = passwordInput.value || "";
      if (!email || !password) { setMsg("Enter your email and password.", "error"); return; }
      if (mode === "register" && password.length < 8) {
        setMsg("Password must be at least 8 characters.", "error"); return;
      }
      submitBtn.disabled = true;
      if (mode === "login") {
        setMsg("Signing in\u2026");
        Api.login(email, password).then(function () {
          setMsg("Signed in. Redirecting\u2026", "ok");
          location.replace(next);
        }).catch(function (err) {
          submitBtn.disabled = false;
          setMsg(err && err.status === 401 ? "Invalid email or password." : ((err && err.message) || "Login failed."), "error");
        });
      } else {
        setMsg("Creating your account\u2026");
        Api.register(email, password).then(function () {
          // Register does not open a session; log in to set the cookie.
          return Api.login(email, password);
        }).then(function () {
          setMsg("Account created. Redirecting\u2026", "ok");
          location.replace(next);
        }).catch(function (err) {
          submitBtn.disabled = false;
          if (err && err.status === 409) setMsg("That email is already registered \u2014 try logging in.", "error");
          else if (err && err.status === 400) setMsg((err && err.message) || "Use a valid email and a stronger password.", "error");
          else setMsg((err && err.message) || "Registration failed.", "error");
        });
      }
    });

    setMode(params.get("mode") === "register" ? "register" : "login");

    // Already authenticated? Skip straight through to the destination.
    Api.me().then(function () { location.replace(next); }).catch(function () {
      if (emailInput) emailInput.focus();
    });
  }

  /* ---------- auth state + account control (non-auth pages) ---------- */
  /* ---------------------------------------------------------------------- */
  /* PIPELINE PAGE  (public) - shows the real execution flow + agent registry */
  /* ---------------------------------------------------------------------- */
  function initPipeline() {
    var STAGES = [
      { n: 1, key: "requirement", name: "Requirement Analyzer", cls: "engine-det", engineLabel: "Deterministic", does: "Parses the natural-language request and search intensity into a structured dataset spec." },
      { n: 2, key: "planner", name: "Planner", cls: "engine-det", engineLabel: "Deterministic", does: "Selects the workflow and which agents this run needs; stages that do not apply are skipped." },
      { n: 3, key: "discovery", name: "Discovery / Ingestion", cls: "engine-live", engineLabel: "Live provider APIs", does: "Searches real providers for public data or ingests uploaded rows, then normalizes metadata for the catalog." },
      { n: 4, key: "quality", name: "Quality Evaluator", cls: "engine-det", engineLabel: "Deterministic", does: "Scores quality dimensions computed from the actual rows and metadata." },
      { n: 5, key: "ai", name: "AI Skills - Generator + Critic", cls: "engine-nim", engineLabel: "NVIDIA NIM", does: "AI skills summarize, recommend, and review with NVIDIA NIM when configured, with a clearly labeled deterministic fallback." },
      { n: 6, key: "packaging", name: "Packaging", cls: "engine-det", engineLabel: "Deterministic", does: "Builds the manifest, checksums and a reproducible ZIP." },
      { n: 7, key: "explain", name: "Explainability", cls: "engine-nim", engineLabel: "NVIDIA NIM", does: "Writes the dataset card and quality narrative through NIM." }
    ];

    var AGENT_LABELS = {
      requirement_analyzer: "Requirement Analyzer",
      clarification: "Clarification Agent",
      discovery: "Discovery Agent",
      license: "License Agent",
      merge: "Merge Agent",
      cleaning: "Cleaning Agent",
      curator: "Curator Agent",
      translation: "Translation Agent",
      quality_evaluator: "Quality Evaluator",
      generator: "Generator Agent",
      critic: "Critic Agent",
      validator: "Validator Agent",
      bias: "Bias Agent",
      benchmark: "Benchmark Agent",
      formatter: "Formatter Agent",
      packaging: "Packaging Agent",
      explainability: "Explainability Agent"
    };
    var ACTIVE_AGENT_IDS = {
      requirement_analyzer: true,
      discovery: true,
      quality_evaluator: true,
      generator: true,
      critic: true,
      packaging: true,
      explainability: true
    };
    var FALLBACK_CARDS = {
      planner: { id: "planner", name: "Planner", registry_agent: false, category: "orchestration", mission: "Builds execution graphs and selects registry agents." },
      requirement_analyzer: { id: "requirement_analyzer", category: "orchestration_input", registry_agent: true, capabilities: ["analyze_requirements"], llm_required: true },
      clarification: { id: "clarification", category: "orchestration_input", registry_agent: true, capabilities: ["clarify"], llm_required: true },
      discovery: { id: "discovery", category: "discovery", registry_agent: true, capabilities: ["search"], llm_required: false },
      license: { id: "license", category: "governance", registry_agent: true, capabilities: ["license_check"], llm_required: false },
      merge: { id: "merge", category: "processing", registry_agent: true, capabilities: ["merge"], llm_required: false },
      cleaning: { id: "cleaning", category: "processing", registry_agent: true, capabilities: ["clean", "deduplicate", "pii_removal"], llm_required: false },
      curator: { id: "curator", category: "processing", registry_agent: true, capabilities: ["curation", "deduplication"], llm_required: false },
      translation: { id: "translation", category: "processing", registry_agent: true, capabilities: ["translate"], llm_required: true },
      quality_evaluator: { id: "quality_evaluator", category: "evaluation", registry_agent: true, capabilities: ["quality_score"], llm_required: true },
      generator: { id: "generator", category: "generation", registry_agent: true, capabilities: ["generate"], llm_required: true },
      critic: { id: "critic", category: "evaluation", registry_agent: true, capabilities: ["critique"], llm_required: true },
      validator: { id: "validator", category: "evaluation", registry_agent: true, capabilities: ["validate"], llm_required: true },
      bias: { id: "bias", category: "evaluation", registry_agent: true, capabilities: ["bias_analysis"], llm_required: false },
      benchmark: { id: "benchmark", category: "evaluation", registry_agent: true, capabilities: ["benchmark"], llm_required: false },
      formatter: { id: "formatter", category: "export", registry_agent: true, capabilities: ["format"], llm_required: false },
      packaging: { id: "packaging", category: "export", registry_agent: true, capabilities: ["package"], llm_required: false },
      explainability: { id: "explainability", category: "audit", registry_agent: true, capabilities: ["audit"], llm_required: true }
    };
    var CATEGORY_ORDER = ["orchestration_input", "discovery", "governance", "processing", "evaluation", "generation", "export", "audit"];

    function tagLabel(t) { return t === "active" ? "Live path" : (t === "llm" ? "LLM capable" : "Registered"); }
    function providerCls(p) {
      p = String(p || "").toLowerCase();
      if (p.indexOf("nim") > -1) return "engine-nim";
      if (p.indexOf("http") > -1 || p.indexOf("live") > -1) return "engine-live";
      return "engine-det";
    }

    var flow = $("#pipelineFlow");
    if (flow) {
      var fhtml = "";
      for (var i = 0; i < STAGES.length; i++) {
        var s = STAGES[i];
        if (i > 0) fhtml += "<div class='pipe-arrow' aria-hidden='true'>&rarr;</div>";
        fhtml += "<article class='pipe-stage' id='stage-" + s.key + "'>" +
          "<span class='num'>Stage " + s.n + "</span>" +
          "<h3>" + escapeHtml(s.name) + "</h3>" +
          "<p>" + escapeHtml(s.does) + "</p>" +
          "<span class='engine-pill " + s.cls + "'>" + escapeHtml(s.engineLabel) + "</span>" +
          "</article>";
      }
      flow.innerHTML = fhtml;
    }

    function cleanName(id, card) {
      return AGENT_LABELS[id] || (card && card.name ? String(card.name).replace(/_/g, " ") : id.replace(/_/g, " "));
    }
    function renderAgentCard(id, card) {
      var tag = ACTIVE_AGENT_IDS[id] ? "active" : (card.llm_required ? "llm" : "impl");
      var caps = (card.capabilities || []).slice(0, 3).join(", ");
      return "<div class='reg-agent'>" +
        "<span class='reg-name'>" + escapeHtml(cleanName(id, card)) +
          (caps ? " <span class='reg-sub'>" + escapeHtml(caps) + "</span>" : "") +
        "</span><span class='tag tag-" + tag + "'>" + escapeHtml(tagLabel(tag)) + "</span></div>";
    }
    function renderRegistry(cards) {
      var panel = $("#registryPanel");
      if (!panel) return;
      cards = cards || {};
      var planner = cards.planner || { name: "Planner", mission: "Registry unavailable; start the backend to inspect live capability cards." };
      var registryIds = Object.keys(cards).filter(function (id) {
        return id !== "planner" && cards[id] && cards[id].registry_agent !== false;
      });
      if (!registryIds.length) {
        panel.innerHTML = "<div class='run-empty'><strong>Agent registry unavailable.</strong><p>Start the backend and reload this page to inspect the live 17-agent registry. The seven-stage pipeline above is the real default execution path.</p></div>";
        return;
      }
      registryIds.sort(function (a, b) {
        var ac = CATEGORY_ORDER.indexOf(cards[a].category);
        var bc = CATEGORY_ORDER.indexOf(cards[b].category);
        if (ac === -1) ac = 99;
        if (bc === -1) bc = 99;
        return ac === bc ? a.localeCompare(b) : ac - bc;
      });
      var byCategory = {};
      registryIds.forEach(function (id) {
        var category = cards[id].category || "execution";
        if (!byCategory[category]) byCategory[category] = [];
        byCategory[category].push(id);
      });

      var activeCount = registryIds.filter(function (id) { return ACTIVE_AGENT_IDS[id]; }).length;
      var html = "<div class='reg-group reg-brain'><div class='reg-head'><h4>Planner brain</h4>" +
        "<span class='reg-note'>1 orchestrator, outside the registry. It plans; it does not transform data.</span></div>" +
        "<div class='reg-agents'><div class='reg-agent'><span class='reg-name'>" + escapeHtml(planner.name || "Planner") +
        " <span class='reg-sub'>" + escapeHtml(planner.mission || "Builds execution graphs from capability cards.") +
        "</span></span><span class='tag tag-brain'>Brain</span></div></div></div>";

      html += "<div class='reg-summary'><span>17 registry execution agents</span><span>" +
        activeCount + " shown in the default live path</span><span>" +
        (registryIds.length - activeCount) + " available for conditional workflows</span></div>";

      CATEGORY_ORDER.forEach(function (category) {
        var ids = byCategory[category] || [];
        if (!ids.length) return;
        html += "<div class='reg-group'><div class='reg-head'><h4>" + escapeHtml(category.replace(/_/g, " ")) +
          "</h4><span class='reg-note'>" + ids.length + " agent" + (ids.length === 1 ? "" : "s") +
          "</span></div><div class='reg-agents'>";
        ids.forEach(function (id) { html += renderAgentCard(id, cards[id]); });
        html += "</div></div>";
      });
      panel.innerHTML = html;
    }
    if (Api && Api.agentCards) {
      var registryPanel = $("#registryPanel");
      if (registryPanel) registryPanel.innerHTML = "<div class='run-empty'>Loading live agent registry...</div>";
      Api.agentCards().then(function (data) {
        renderRegistry(data && data.cards);
      }).catch(function () { renderRegistry({}); });
    } else {
      renderRegistry({});
    }

    var toggle = $("#registryToggle");
    var panel = $("#registryPanel");
    if (toggle && panel) {
      toggle.addEventListener("click", function () {
        var closed = panel.hasAttribute("hidden");
        if (closed) {
          panel.removeAttribute("hidden");
          toggle.setAttribute("aria-expanded", "true");
          toggle.textContent = "Hide full agent registry";
        } else {
          panel.setAttribute("hidden", "");
          toggle.setAttribute("aria-expanded", "false");
          toggle.textContent = "Show full agent registry (17)";
        }
      });
    }

    // Live AI engine on the AI Skills stage, from the real /ai/llm/status.
    if (Api && Api.llmStatus) {
      Api.llmStatus().then(function (data) {
        var p = "";
        if (data) p = String(data.provider || data.mode || data.name || "").toLowerCase();
        var avail = data && data.available !== undefined ? !!data.available : null;
        var text = null, cls = null;
        if (p.indexOf("nim") > -1) { text = "Live \u00b7 NVIDIA NIM"; cls = "engine-nim"; }
        else if (p.indexOf("http") > -1 || p.indexOf("live") > -1) { text = "Live \u00b7 HTTP model"; cls = "engine-live"; }
        else if (avail === false || p.indexOf("local") > -1 || p.indexOf("determin") > -1) { text = "Deterministic fallback"; cls = "engine-det"; }
        if (text) {
          var pills = $all("#stage-ai .engine-pill");
          if (pills[0]) { pills[0].textContent = text; pills[0].className = "engine-pill " + cls; }
        }
      }).catch(function () {});
    }

    // Latest real run from the catalog (auth required; degrade gracefully).
    var statusLine = $("#statusLine");
    var runBox = $("#latestRun");
    function emptyRun(msg) { return "<div class='run-empty'>" + escapeHtml(msg) + "</div>"; }
    function fact(k, v) { return "<span class='run-fact'><b>" + escapeHtml(k) + "</b>" + escapeHtml(String(v)) + "</span>"; }
    function renderRun(d) {
      var prov = d.ai_provider || "local";
      var q = (d.quality_metrics && typeof d.quality_metrics === "object") ? d.quality_metrics : {};
      var dims = ["completeness", "consistency", "diversity", "duplicate_ratio", "formatting", "readability", "model_compatibility"];
      var mhtml = "";
      for (var i = 0; i < dims.length; i++) {
        if (q[dims[i]] != null) {
          mhtml += "<span class='run-metric'><b>" + escapeHtml(dims[i].replace(/_/g, " ")) + "</b>" + escapeHtml(String(q[dims[i]])) + "</span>";
        }
      }
      return "<article class='run-card'>" +
        "<header class='run-top'><h3>" + escapeHtml(d.title || d.filename || "Untitled dataset") + "</h3>" +
        "<span class='engine-pill " + providerCls(prov) + "'>AI \u00b7 " + escapeHtml(prov) + "</span></header>" +
        "<div class='run-facts'>" +
          fact("Source", d.source || d.provider || "local") +
          fact("Rows", fmtInt(d.rows)) +
          fact("Columns", fmtInt(d.columns)) +
          fact("Quality", d.quality_score != null ? (d.quality_score + " / 100") : "n/a") +
        "</div>" +
        (mhtml ? "<div class='run-metrics'>" + mhtml + "</div>" : "") +
        (d.quality_narrative ? "<p class='run-narr'>" + escapeHtml(d.quality_narrative) + "</p>" : "") +
        "<p class='run-foot'>Rendered from a real stored run: discovery / ingestion &rarr; quality &rarr; AI skills &rarr; packaging &rarr; explainability.</p>" +
        "</article>";
    }
    function renderTraceRun(run, trace) {
      trace = trace || [];
      var steps = trace.map(function (step, i) {
        var output = step.output || {};
        var summary = Object.keys(output).slice(0, 4).map(function (k) {
          var v = output[k];
          if (v && typeof v === "object") v = Array.isArray(v) ? ("list(" + v.length + ")") : "object";
          return "<span class='run-metric'><b>" + escapeHtml(k.replace(/_/g, " ")) + "</b>" + escapeHtml(String(v)) + "</span>";
        }).join("");
        return "<div class='trace-step'>" +
          "<span class='num'>Stage " + (i + 1) + "</span>" +
          "<h4>" + escapeHtml(step.name || "Stage") + "</h4>" +
          "<span class='engine-pill " + providerCls(step.engine) + "'>" + escapeHtml(step.engine || "engine") + "</span>" +
          "<p>" + escapeHtml(step.status || "completed") + "</p>" +
          (summary ? "<div class='run-metrics'>" + summary + "</div>" : "") +
          "</div>";
      }).join("");
      return "<article class='run-card'>" +
        "<header class='run-top'><h3>" + escapeHtml(run.workflow || "Workflow run") + "</h3>" +
        "<span class='engine-pill " + providerCls(run.status) + "'>" + escapeHtml(run.status || "unknown") + "</span></header>" +
        "<div class='run-facts'>" +
          fact("Task", run.task_id || "n/a") +
          fact("Created", run.created_at || "n/a") +
          fact("Stages", trace.length || 0) +
        "</div>" +
        (steps ? "<div class='trace-list'>" + steps + "</div>" : "<p class='run-narr'>No stage trace was stored for this run.</p>") +
        "</article>";
    }
    function loadCatalogFallback() {
      return Api.catalog().then(function (data) {
        var items = responseItems(data);
        if (!items.length) {
          if (statusLine) statusLine.textContent = "";
          runBox.innerHTML = emptyRun("No forged datasets yet. Run a flow in Forge to see real pipeline output here.");
          return;
        }
        items.sort(function (x, y) { return String(y.created_at || "").localeCompare(String(x.created_at || "")); });
        if (statusLine) statusLine.textContent = "";
        runBox.innerHTML = renderRun(items[0]);
      });
    }
    if (runBox) {
      if (statusLine) statusLine.textContent = "Loading the most recent forge run\u2026";
      (Api.workflowRuns ? Api.workflowRuns().then(function (data) {
        var runs = (data && data.runs) || [];
        runs.sort(function (x, y) { return String(y.created_at || "").localeCompare(String(x.created_at || "")); });
        if (!runs.length || !Api.workflowRun) return loadCatalogFallback();
        return Api.workflowRun(runs[0].task_id).then(function (detail) {
          var run = (detail && detail.run) || runs[0];
          if (statusLine) statusLine.textContent = "";
          runBox.innerHTML = renderTraceRun(run, (detail && detail.stage_trace) || run.stage_trace || []);
        });
      }) : loadCatalogFallback()).catch(function (err) {
        if (statusLine) statusLine.textContent = "";
        if (err && err.status === 401) {
          runBox.innerHTML = emptyRun("Sign in and forge a dataset to see a real pipeline run here.");
        } else {
          loadCatalogFallback().catch(function () {
            runBox.innerHTML = emptyRun("Live run data is unavailable right now.");
          });
        }
      });
    }
  }

  var AUTH = { me: null };
  var PROTECTED = { forge: true, catalog: true, settings: true, teams: true };
  var accountBox = $("#accountBox");

  function currentPageFile() {
    return (location.pathname.split("/").pop() || "index.html") + location.search;
  }
  // Only allow same-site relative *.html targets as a post-login redirect.
  function safeNext(raw) {
    var v = raw || "";
    try { v = decodeURIComponent(v); } catch (e) {}
    if (!v) return "index.html";
    if (/^https?:/i.test(v) || v.indexOf("//") === 0 || v.charAt(0) === "/") return "index.html";
    if (!/^[\w.-]+\.html(\?[^#]*)?$/.test(v)) return "index.html";
    return v;
  }
  function gotoLogin() {
    location.replace("auth.html?next=" + encodeURIComponent(currentPageFile()));
  }
  function renderAccount() {
    if (!accountBox) return;
    if (AUTH.me) {
      accountBox.innerHTML =
        "<span class='account-email' title='" + escapeHtml(AUTH.me.email) + "'>" + escapeHtml(AUTH.me.email) + "</span>" +
        "<a class='account-link' href='settings.html'>Settings</a>" +
        "<button class='button ghost account-btn' id='logoutBtn' type='button'>Log out</button>";
      var lb = $("#logoutBtn");
      if (lb) lb.addEventListener("click", function () {
        lb.disabled = true;
        Api.logout().then(function () {
          AUTH.me = null;
          location.href = "auth.html";
        }).catch(function () {
          lb.disabled = false;
          toast("Sign out failed.", true);
        });
      });
    } else {
      accountBox.innerHTML =
        "<a class='button ghost account-btn' href='auth.html?next=" +
        encodeURIComponent(currentPageFile()) + "'>Sign in</a>";
    }
  }

  function bootPage() {
    if (PAGE === "discover") initDiscover();
    else if (PAGE === "forge") initForge();
    else if (PAGE === "catalog") initCatalog();
    else if (PAGE === "settings") initSettings();
    else if (PAGE === "teams") initTeams();
    else if (PAGE === "pipeline") initPipeline();
  }

  /* ---------- boot ---------- */
  showApiBaseWarning();
  loadProviderStatus();
  if (PAGE === "auth") {
    initAuth();
  } else {
    if (PROTECTED[PAGE]) {
      Api.me().then(function (user) {
        AUTH.me = user;
        renderAccount();
        bootPage();
      }).catch(function (err) {
        AUTH.me = null;
        renderAccount();
        if (err && err.status === 401) gotoLogin();
        else bootPage();
      });
    } else {
      bootPage();
      Api.me().then(function (user) {
        AUTH.me = user;
        renderAccount();
      }).catch(function () {
        AUTH.me = null;
        renderAccount();
      });
    }
  }
})();
