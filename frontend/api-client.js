// Resilient API client: timeout, bounded retry with backoff, typed errors,
// API-key header, and helpers the UI uses to render loading/empty/error states.
(function (global) {
  var cfg = global.DataForgeConfig || { apiBase: "/api", requestTimeoutMs: 30000, maxRetries: 2 };

  function ApiError(message, status, detail) {
    this.name = "ApiError";
    this.message = message;
    this.status = status || 0;
    this.detail = detail || "";
  }
  ApiError.prototype = Object.create(Error.prototype);

  function sleep(ms) {
    return new Promise(function (r) { setTimeout(r, ms); });
  }

  function withTimeout(promise, ms, controller) {
    var timer = setTimeout(function () { controller.abort(); }, ms);
    return promise.finally(function () { clearTimeout(timer); });
  }

  async function request(path, options) {
    options = options || {};
    var url = cfg.apiBase.replace(/\/$/, "") + path;
    var headers = Object.assign({ "Content-Type": "application/json" }, options.headers || {});
    if (global.DATAFORGE_API_KEY) headers["x-api-key"] = global.DATAFORGE_API_KEY;

    var attempt = 0;
    var lastError;
    while (attempt <= cfg.maxRetries) {
      var controller = new AbortController();
      try {
        var resp = await withTimeout(
          fetch(url, {
            method: options.method || "GET",
            headers: headers,
            body: options.body ? JSON.stringify(options.body) : undefined,
            signal: controller.signal,
          }),
          cfg.requestTimeoutMs,
          controller
        );
        if (resp.status === 429 || resp.status >= 500) {
          lastError = new ApiError("Server busy", resp.status);
          await sleep(200 * Math.pow(2, attempt));
          attempt++;
          continue;
        }
        var text = await resp.text();
        var data = text ? JSON.parse(text) : null;
        if (!resp.ok) {
          throw new ApiError((data && data.error) || "Request failed", resp.status, text);
        }
        return data;
      } catch (err) {
        if (err instanceof ApiError && err.status && err.status < 500 && err.status !== 429) {
          throw err; // non-retryable client error
        }
        lastError = err;
        await sleep(200 * Math.pow(2, attempt));
        attempt++;
      }
    }
    throw lastError || new ApiError("Network error", 0);
  }

  global.DataForgeApi = {
    ApiError: ApiError,
    health: function () { return request("/health"); },
    searchDatasets: function (q, options) {
      options = options || {};
      return request("/datasets/search", {
        method: "POST",
        body: {
          query: q || "",
          include_public: Boolean(options.includePublic),
          limit: options.limit || 10,
        },
      });
    },
    processDataset: function (payload) {
      return request("/datasets/process", { method: "POST", body: payload });
    },
    catalog: function () { return request("/datasets/catalog"); },
    discovery: function (q) {
      return request("/discovery/search", {
        method: "POST",
        body: { request: q || "" },
      });
    },
  };
})(window);
