/*
 * api.js - every call from the browser to the FastAPI backend lives here.
 *
 * Each function returns a Promise with the parsed JSON response, or throws
 * an ApiError whose `message` is safe to show to the user.
 */
(function () {
  "use strict";

  const BASE = window.APP_CONFIG.API_BASE_URL;
  const REQUEST_TIMEOUT_MS = 15000;

  class ApiError extends Error {
    constructor(message, status) {
      super(message);
      this.name = "ApiError";
      this.status = status; // HTTP status code, or 0 for network problems
    }
  }

  async function request(path, options) {
    const controller = new AbortController();
    const timer = setTimeout(function () { controller.abort(); }, REQUEST_TIMEOUT_MS);
    let response;
    try {
      response = await fetch(BASE + path, Object.assign({ signal: controller.signal }, options));
    } catch (error) {
      const message = error.name === "AbortError"
        ? "The server took too long to answer. Please try again."
        : "Can't reach the backend server. Make sure it is running.";
      throw new ApiError(message, 0);
    } finally {
      clearTimeout(timer);
    }

    let body = null;
    try {
      body = await response.json();
    } catch (_error) {
      body = null;
    }

    if (!response.ok) {
      const detail = body && typeof body.detail === "string" ? body.detail : "Request failed.";
      throw new ApiError(detail, response.status);
    }
    return body;
  }

  window.Api = {
    ApiError: ApiError,

    health: function () {
      return request("/health");
    },

    createGeneration: function (topic) {
      return request("/api/generations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ topic: topic }),
      });
    },

    getGeneration: function (id) {
      return request("/api/generations/" + encodeURIComponent(id));
    },

    listGenerations: function (limit) {
      return request("/api/generations?limit=" + encodeURIComponent(limit));
    },

    downloadUrl: function (id) {
      return BASE + "/api/generations/" + encodeURIComponent(id) + "/download";
    },
  };
})();
