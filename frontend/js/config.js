(function () {
  "use strict";

  const PRODUCTION_API_URL =
    "https://crewai-learning-assistant.onrender.com";

  const LOCAL_API_URL = "http://127.0.0.1:8000";

  function resolveApiBaseUrl() {
    const servedByBackend =
      window.location.pathname.startsWith("/app");

    if (servedByBackend) return "";

    if (PRODUCTION_API_URL) {
      return PRODUCTION_API_URL.replace(/\/$/, "");
    }

    return LOCAL_API_URL;
  }

  window.APP_CONFIG = Object.freeze({
    API_BASE_URL: resolveApiBaseUrl(),
    TOPIC_MIN_LENGTH: 2,
    TOPIC_MAX_LENGTH: 120,
    POLL_INTERVAL_MS: 2000,
    HISTORY_LIMIT: 12,
  });
})();