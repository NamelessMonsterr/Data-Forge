// Runtime configuration for the DataForge frontend.
// Resolution order:
//   1. window.DATAFORGE_CONFIG (injected by the host page / deployment)
//   2. <meta name="dataforge-api-base" content="..."> tag
//   3. local dev backend on 127.0.0.1:8000 when served from localhost/5173
//   4. same-origin "/api" (works behind a reverse proxy)
// No hardcoded localhost in production builds.
(function (global) {
  function resolveApiBase() {
    if (global.DATAFORGE_CONFIG && global.DATAFORGE_CONFIG.apiBase) {
      return global.DATAFORGE_CONFIG.apiBase;
    }
    var meta = document.querySelector('meta[name="dataforge-api-base"]');
    if (meta && meta.content) return meta.content;
    if (global.location.hostname === "127.0.0.1" || global.location.hostname === "localhost") {
      return "http://127.0.0.1:8000";
    }
    return global.location.origin + "/api";
  }

  global.DataForgeConfig = {
    apiBase: resolveApiBase(),
    requestTimeoutMs: 30000,
    maxRetries: 2,
  };
})(window);
