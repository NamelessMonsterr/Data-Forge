// Runtime configuration for the DataForge frontend.
// Resolution order:
//   1. window.DATAFORGE_CONFIG (injected by the host page / deployment)
//   2. <meta name="dataforge-api-base" content="..."> tag
//   3. same-origin "/api" (works behind a reverse proxy)
// No hardcoded localhost in production builds.
(function (global) {
  function resolveApiBase() {
    if (global.DATAFORGE_CONFIG && global.DATAFORGE_CONFIG.apiBase) {
      return global.DATAFORGE_CONFIG.apiBase;
    }
    var meta = document.querySelector('meta[name="dataforge-api-base"]');
    if (meta && meta.content) return meta.content;
    return global.location.origin + "/api";
  }

  global.DataForgeConfig = {
    apiBase: resolveApiBase(),
    requestTimeoutMs: 30000,
    maxRetries: 2,
  };
})(window);
