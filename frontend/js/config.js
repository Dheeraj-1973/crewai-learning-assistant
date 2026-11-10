/*
 * config.js - where is the backend API?
 *
 * Two ways to run the frontend:
 *   1. Served BY the backend at http://127.0.0.1:8000/app/  (recommended)
 *      -> the API is on the same origin, so API_BASE_URL is "" (same server).
 *   2. Served separately, e.g. VS Code/Cursor Live Server on port 5500
 *      -> the API lives at http://127.0.0.1:8000.
 *
 * For a deployed frontend (e.g. Netlify) set PRODUCTION_API_URL below to
 * your backend's public URL.
 */
(function () {
  "use strict";

  const PRODUCTION_API_URL = ""; // e.g. "https://your-backend.onrender.com"
  const LOCAL_API_URL = "http://127.0.0.1:8000";

  function resolveApiBaseUrl() {
    const servedByBackend = window.location.pathname.startsWith("/app");
    if (servedByBackend) return "";
    if (PRODUCTION_API_URL) return PRODUCTION_API_URL.replace(/\/$/, "");
    return LOCAL_API_URL;
  }

  window.APP_CONFIG = Object.freeze({
    API_BASE_URL: resolveApiBaseUrl(),
    TOPIC_MIN_LENGTH: 2,      // keep in sync with backend/app/core/config.py
    TOPIC_MAX_LENGTH: 120,
    POLL_INTERVAL_MS: 2000,   // how often to ask the backend for status
    HISTORY_LIMIT: 12,
  });
})();
