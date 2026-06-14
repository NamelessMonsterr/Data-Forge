// Runtime configuration for the DataForge frontend.
// Resolution order:
//   1. window.DATAFORGE_CONFIG (injected by the host page / deployment)
//   2. ?api=... query parameter, persisted for forwarded-port demos
//   3. <meta name="dataforge-api-base" content="..."> tag
//   4. same-origin "/api" (works behind a reverse proxy)
// No hardcoded localhost in production builds.
(function (global) {
  function isLoopback(hostname) {
    return hostname === "localhost" || hostname === "127.0.0.1" || hostname === "::1";
  }

  function devTunnelParts(hostname) {
    return String(hostname || "").match(/^(.+)-(\d+)(\.[^.]+\.devtunnels\.ms)$/i);
  }

  function isPairedDevTunnel(apiHost) {
    var current = devTunnelParts(global.location.hostname);
    var target = devTunnelParts(apiHost);
    return !!(current && target && current[1] === target[1] && current[3].toLowerCase() === target[3].toLowerCase());
  }

  function forwardedBackendFrom(localApiBase) {
    try {
      var api = new URL(localApiBase);
      if (!isLoopback(api.hostname) || isLoopback(global.location.hostname)) return localApiBase;
      if (/-\d+\.[^.]+\.devtunnels\.ms$/i.test(global.location.hostname)) {
        var devTunnelHost = global.location.hostname.replace(/-\d+(\.[^.]+\.devtunnels\.ms)$/i, "-" + api.port + "$1");
        return global.location.protocol + "//" + devTunnelHost;
      }
      api.hostname = global.location.hostname;
      api.protocol = global.location.protocol === "https:" ? "https:" : api.protocol;
      return api.toString().replace(/\/$/, "");
    } catch (err) {
      return localApiBase;
    }
  }

  function isAllowedApiBase(value) {
    try {
      var url = new URL(value, global.location.origin);
      if (url.protocol !== "http:" && url.protocol !== "https:") return false;
      if (url.hostname === global.location.hostname) return true;
      if (isLoopback(url.hostname)) return isLoopback(global.location.hostname);
      if (isPairedDevTunnel(url.hostname)) return true;
      return false;
    } catch (err) {
      return false;
    }
  }

  function normalizeAllowedApiBase(value) {
    if (!value || !isAllowedApiBase(value)) return "";
    return new URL(value, global.location.origin).toString().replace(/\/$/, "");
  }

  function resolveApiBase() {
    if (global.DATAFORGE_CONFIG && global.DATAFORGE_CONFIG.apiBase) {
      global.DATAFORGE_API_BASE_SOURCE = "injected";
      return global.DATAFORGE_CONFIG.apiBase;
    }
    var params = new URLSearchParams(global.location.search || "");
    var apiParam = params.get("api") || params.get("apiBase");
    if (apiParam) {
      var allowedParam = normalizeAllowedApiBase(apiParam);
      if (allowedParam) {
        global.DATAFORGE_API_BASE_SOURCE = "query";
        return allowedParam;
      }
    }
    try {
      var stored = global.localStorage.getItem("dataforge_api_base");
      var allowedStored = normalizeAllowedApiBase(stored);
      if (allowedStored) {
        global.DATAFORGE_API_BASE_SOURCE = "stored";
        return allowedStored;
      }
      if (stored) global.localStorage.removeItem("dataforge_api_base");
    } catch (err) {}
    var meta = document.querySelector('meta[name="dataforge-api-base"]');
    if (meta && meta.content) {
      global.DATAFORGE_API_BASE_SOURCE = "meta";
      return forwardedBackendFrom(meta.content);
    }
    global.DATAFORGE_API_BASE_SOURCE = "same-origin";
    return global.location.origin + "/api";
  }

  var resolvedApiBase = resolveApiBase();
  global.DataForgeConfig = {
    apiBase: resolvedApiBase,
    apiBaseSource: global.DATAFORGE_API_BASE_SOURCE || "unknown",
    defaultApiBase: global.location.origin + "/api",
    requestTimeoutMs: 120000,
    maxRetries: 2,
  };
})(window);
