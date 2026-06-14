// Resilient API client: timeout, bounded retry with backoff, typed errors,
// API-key header, and helpers the UI uses to render loading/empty/error states.
// Search + discovery accept a `intensity` (easy|medium|hard|very_hard|intense)
// that tells the backend how hard to work.
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
    var method = (options.method || "GET").toUpperCase();
    var canRetry = method === "GET" || method === "HEAD";
    var maxAttempts = canRetry ? cfg.maxRetries : 0;
    var headers = Object.assign({ "Content-Type": "application/json" }, options.headers || {});
    if (global.DATAFORGE_API_KEY) headers["x-api-key"] = global.DATAFORGE_API_KEY;

    var attempt = 0;
    var lastError;
    while (attempt <= maxAttempts) {
      var controller = new AbortController();
      try {
        var resp = await withTimeout(
          fetch(url, {
            method: method,
            credentials: "include",
            headers: headers,
            body: options.body ? JSON.stringify(options.body) : undefined,
            signal: controller.signal,
          }),
          cfg.requestTimeoutMs,
          controller
        );
        if (resp.status === 429 || resp.status >= 500) {
          lastError = new ApiError("Server busy", resp.status);
          if (attempt >= maxAttempts) break;
          await sleep(200 * Math.pow(2, attempt));
          attempt++;
          continue;
        }
        var text = await resp.text();
        var data = text ? JSON.parse(text) : null;
        if (!resp.ok) {
          throw new ApiError((data && (data.detail || data.error)) || "Request failed", resp.status, text);
        }
        return data;
      } catch (err) {
        if (err instanceof ApiError) throw err;
        lastError = err;
        if (!canRetry || attempt >= maxAttempts) throw err;
        await sleep(200 * Math.pow(2, attempt));
        attempt++;
      }
    }
    throw lastError || new ApiError("Network error", 0);
  }

  global.DataForgeApi = {
    ApiError: ApiError,
    health: function () { return request("/health"); },
    ready: function () { return request("/ready"); },
    llmStatus: function () { return request("/ai/llm/status"); },
    agentCards: function () { return request("/agents/cards"); },
    // POST /datasets/search { query, include_public, limit, intensity }
    searchDatasets: function (query, opts) {
      opts = (opts && typeof opts === "object") ? opts : {};
      var body = {
        query: query || "",
        include_public: opts.includePublic !== false,
        intensity: opts.intensity || "medium",
      };
      if (opts.limit != null) body.limit = opts.limit;
      return request("/datasets/search", {
        method: "POST",
        body: body,
      });
    },
    processDataset: function (payload) {
      return request("/datasets/process", { method: "POST", body: payload });
    },
    savePublicDataset: function (candidate, query) {
      return request("/datasets/save-public", {
        method: "POST",
        body: { candidate: candidate || {}, query: query || "" },
      });
    },
    catalog: function () { return request("/datasets/catalog"); },
    workflowRuns: function () { return request("/workflow/runs"); },
    workflowRun: function (taskId) { return request("/workflow/runs/" + encodeURIComponent(taskId)); },
    // GET /discovery/search?q=&intensity=
    discovery: function (query, opts) {
      opts = (opts && typeof opts === "object") ? opts : {};
      var qs = "?q=" + encodeURIComponent(query || "") +
               "&intensity=" + encodeURIComponent(opts.intensity || "medium");
      return request("/discovery/search" + qs);
    },
    // ---- auth (cookie session) ----
    // POST /auth/register { email, password } -> 201 user (no session set)
    register: function (email, password) {
      return request("/auth/register", { method: "POST", body: { email: email, password: password } });
    },
    // POST /auth/login { email, password } -> 200 user + sets HTTP-only cookie
    login: function (email, password) {
      return request("/auth/login", { method: "POST", body: { email: email, password: password } });
    },
    // POST /auth/logout -> clears the session cookie
    logout: function () { return request("/auth/logout", { method: "POST" }); },
    // GET /auth/me -> 200 user when authenticated, 401 otherwise
    me: function () { return request("/auth/me"); },

    // ---- provider-key vault (Settings) ----
    // GET /settings/providers -> { providers: [{ provider, configured, ... }] }
    providerSettings: function () { return request("/settings/providers"); },
    // POST /settings/providers/{provider} { api_key, secret? }
    setProviderKey: function (provider, apiKey, secret) {
      return request("/settings/providers/" + encodeURIComponent(provider), {
        method: "POST",
        body: { api_key: apiKey, secret: (secret == null || secret === "") ? null : secret },
      });
    },
    // DELETE /settings/providers/{provider}
    deleteProviderKey: function (provider) {
      return request("/settings/providers/" + encodeURIComponent(provider), { method: "DELETE" });
    },

    // ---- teams + RBAC (resource sharing; provider keys are never shared) ----
    // GET /teams -> { teams: [{ id, name, owner_id, created_at }] }
    listTeams: function () { return request("/teams"); },
    // POST /teams { name } -> created team
    createTeam: function (name) { return request("/teams", { method: "POST", body: { name: name } }); },
    // DELETE /teams/{id}
    deleteTeam: function (teamId) { return request("/teams/" + encodeURIComponent(teamId), { method: "DELETE" }); },
    // GET /teams/{id}/members -> { members: [{ user_id, team_role, email? }] }
    listMembers: function (teamId) { return request("/teams/" + encodeURIComponent(teamId) + "/members"); },
    // POST /teams/{id}/members { email?, user_id?, role } -> upsert membership (also used to change a role)
    addMember: function (teamId, opts) {
      opts = opts || {};
      var body = { role: opts.role };
      if (opts.email) body.email = opts.email;
      if (opts.userId) body.user_id = opts.userId;
      return request("/teams/" + encodeURIComponent(teamId) + "/members", { method: "POST", body: body });
    },
    // DELETE /teams/{id}/members/{userId}
    removeMember: function (teamId, userId) {
      return request("/teams/" + encodeURIComponent(teamId) + "/members/" + encodeURIComponent(userId), { method: "DELETE" });
    },
    // GET /teams/{id}/shares -> { shares: [{ resource_type, resource_id, permission }] } (optional endpoint)
    listShares: function (teamId) { return request("/teams/" + encodeURIComponent(teamId) + "/shares"); },
    // POST /teams/{id}/shares { resource_type, resource_id, permission }
    shareResource: function (teamId, resourceType, resourceId, permission) {
      return request("/teams/" + encodeURIComponent(teamId) + "/shares", {
        method: "POST",
        body: { resource_type: resourceType, resource_id: resourceId, permission: permission },
      });
    },
    // DELETE /teams/{id}/shares?resource_type=&resource_id=
    unshareResource: function (teamId, resourceType, resourceId) {
      return request("/teams/" + encodeURIComponent(teamId) + "/shares?resource_type=" +
        encodeURIComponent(resourceType) + "&resource_id=" + encodeURIComponent(resourceId), { method: "DELETE" });
    },
  };
})(window);
