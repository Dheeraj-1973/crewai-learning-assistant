/*
 * app.js - all page behaviour.
 *
 * The page has three "views" (sections of index.html), and only one is
 * visible at a time:
 *   home      - hero, topic form, teaching team, history
 *   progress  - live status while the agents work (or the error if it failed)
 *   result    - the finished learning notes
 *
 * The URL hash remembers which generation is open, e.g.
 *   http://127.0.0.1:8000/app/#/generation/3f2b9c...
 * so refreshing the page re-opens the same notes.
 *
 * Safety rule used everywhere: text from the server is written with
 * `textContent` (never innerHTML). Markdown is rendered only through
 * SafeMarkdown.toFragment(), which escapes and sanitizes it.
 */
(function () {
  "use strict";

  const CONFIG = window.APP_CONFIG;
  const Api = window.Api;
  const SafeMarkdown = window.SafeMarkdown;

  const ROLES = ["Learning Coordinator", "Content Teacher", "Q&A Specialist", "Summary Writer"];
  const NOT_COVERED = "The explanation does not cover this.";
  const MAX_POLL_FAILURES = 5;

  // Everything the page needs to remember while it runs.
  const state = {
    currentId: null,      // generation shown in the progress/result view
    current: null,        // its latest data from the server
    pollTimer: null,
    pollFailures: 0,
    elapsedTimer: null,
    sectionObserver: null,
  };

  // Short helper: find an element by id.
  const $ = function (id) { return document.getElementById(id); };

  // ------------------------------------------------------------------
  // Small utilities
  // ------------------------------------------------------------------

  const dateFormatter = new Intl.DateTimeFormat(undefined, {
    day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit",
  });

  function formatDate(isoString) {
    if (!isoString) return "";
    const date = new Date(isoString);
    return Number.isNaN(date.getTime()) ? "" : dateFormatter.format(date);
  }

  function formatDuration(totalSeconds) {
    const seconds = Math.max(0, Math.round(totalSeconds));
    const minutes = Math.floor(seconds / 60);
    return minutes + ":" + String(seconds % 60).padStart(2, "0");
  }

  function formatTook(totalSeconds) {
    const seconds = Math.max(1, Math.round(totalSeconds));
    if (seconds < 60) return seconds + " seconds";
    return Math.floor(seconds / 60) + " min " + (seconds % 60) + " s";
  }

  function secondsBetween(startIso, endIso) {
    const start = Date.parse(startIso);
    const end = endIso ? Date.parse(endIso) : Date.now();
    return Number.isNaN(start) || Number.isNaN(end) ? 0 : (end - start) / 1000;
  }

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function statusLabel(status) {
    return { pending: "Queued", processing: "In progress", completed: "Ready", failed: "Failed" }[status] || status;
  }

  let toastTimer = null;
  function showToast(message, isError) {
    const toast = $("toast");
    toast.textContent = message;
    toast.classList.toggle("is-error", Boolean(isError));
    toast.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { toast.hidden = true; }, 2600);
  }

  async function copyText(text) {
    try {
      await navigator.clipboard.writeText(text);
    } catch (_error) {
      // Fallback for browsers that block the Clipboard API.
      const area = document.createElement("textarea");
      area.value = text;
      area.setAttribute("readonly", "");
      area.className = "sprite";
      document.body.appendChild(area);
      area.select();
      const ok = document.execCommand("copy");
      area.remove();
      if (!ok) throw new Error("copy failed");
    }
  }

  // ------------------------------------------------------------------
  // Views and navigation
  // ------------------------------------------------------------------

  function showView(name) {
    ["home", "progress", "result"].forEach(function (view) {
      $("view-" + view).hidden = view !== name;
    });
    if (name === "home") document.title = "CrewAI Learning Assistant";
    window.scrollTo({ top: 0 });
  }

  function stopTimers() {
    clearTimeout(state.pollTimer);
    clearInterval(state.elapsedTimer);
    state.pollTimer = null;
    state.elapsedTimer = null;
  }

  function goHome() {
    stopTimers();
    state.currentId = null;
    state.current = null;
    if (window.location.hash) history.pushState(null, "", window.location.pathname);
    showView("home");
    loadHistory();
  }

  function openGenerationFromHash() {
    const match = window.location.hash.match(/^#\/generation\/([A-Za-z0-9]+)$/);
    if (match) {
      if (match[1] === state.currentId && state.current) return; // already open
      openGeneration(match[1]);
    } else {
      stopTimers();
      showView("home");
    }
  }

  // ------------------------------------------------------------------
  // Server status (top-right indicator + banner)
  // ------------------------------------------------------------------

  async function checkHealth() {
    const indicator = $("server-state");
    const label = indicator.querySelector(".server-label");
    try {
      const health = await Api.health();
      if (health.llm_configured) {
        indicator.dataset.state = "ok";
        label.textContent = "Server ready";
        $("banner").hidden = true;
      } else {
        indicator.dataset.state = "warning";
        label.textContent = "API key missing";
        showBanner("The backend is running, but it has no Groq API key. Add GROQ_API_KEY to the .env file in the project folder, then restart the backend.");
      }
    } catch (_error) {
      indicator.dataset.state = "down";
      label.textContent = "Server offline";
      showBanner("Can't reach the backend server. Start it from the backend folder with: uvicorn app.main:app --reload");
    }
  }

  function showBanner(message) {
    $("banner-text").textContent = message;
    $("banner").hidden = false;
  }

  // ------------------------------------------------------------------
  // Topic form
  // ------------------------------------------------------------------

  function validateTopic(raw) {
    const topic = raw.trim().replace(/\s+/g, " ");
    if (!topic) return { error: "Enter a topic to learn about." };
    if (topic.length < CONFIG.TOPIC_MIN_LENGTH) return { error: "The topic needs at least " + CONFIG.TOPIC_MIN_LENGTH + " characters." };
    if (topic.length > CONFIG.TOPIC_MAX_LENGTH) return { error: "Keep the topic under " + CONFIG.TOPIC_MAX_LENGTH + " characters." };
    return { topic: topic };
  }

  function setFormError(message) {
    const input = $("topic-input");
    $("topic-error").textContent = message || "";
    $("topic-error").hidden = !message;
    input.setAttribute("aria-invalid", message ? "true" : "false");
  }

  async function submitTopic(rawTopic) {
    const result = validateTopic(rawTopic);
    if (result.error) {
      setFormError(result.error);
      $("topic-input").focus();
      return;
    }
    setFormError("");

    const button = $("generate-button");
    button.disabled = true;
    button.textContent = "Starting...";
    try {
      const generation = await Api.createGeneration(result.topic);
      $("topic-input").value = "";
      updateCounter();
      // Changing the hash opens the progress view (see openGenerationFromHash).
      window.location.hash = "#/generation/" + generation.id;
    } catch (error) {
      setFormError(error.message);
      if (!$("view-progress").hidden) showFailure({ topic: result.topic }, error.message);
    } finally {
      button.disabled = false;
      button.textContent = "Generate notes";
    }
  }

  function updateCounter() {
    $("topic-count").textContent = $("topic-input").value.length;
  }

  // ------------------------------------------------------------------
  // Loading a generation and polling its status
  // ------------------------------------------------------------------

  async function openGeneration(id) {
    stopTimers();
    state.currentId = id;
    state.pollFailures = 0;

    // Show the progress view straight away so the click feels instant.
    showView("progress");
    $("progress-topic").textContent = "";
    $("progress-status").textContent = "Loading...";
    $("error-box").hidden = true;

    try {
      const generation = await Api.getGeneration(id);
      handleGeneration(generation);
    } catch (error) {
      showFailure({ topic: "" }, error.status === 404 ? "These notes no longer exist." : error.message);
    }
  }

  function handleGeneration(generation) {
    if (generation.id !== state.currentId) return; // user already moved on
    state.current = generation;

    if (generation.status === "completed") {
      stopTimers();
      renderResult(generation);
      loadHistory();
    } else if (generation.status === "failed") {
      renderProgress(generation);
      stopTimers(); // renderProgress starts the clock; a failed job is not running
      showFailure(generation, generation.error_message || "The generation failed.");
      loadHistory();
    } else {
      renderProgress(generation);
      schedulePoll();
    }
  }

  function schedulePoll() {
    clearTimeout(state.pollTimer);
    state.pollTimer = setTimeout(pollOnce, CONFIG.POLL_INTERVAL_MS);
  }

  async function pollOnce() {
    const id = state.currentId;
    if (!id) return;
    try {
      const generation = await Api.getGeneration(id);
      state.pollFailures = 0;
      handleGeneration(generation);
    } catch (error) {
      state.pollFailures += 1;
      if (state.pollFailures >= MAX_POLL_FAILURES) {
        stopTimers();
        showFailure(state.current || { topic: "" },
          "Lost contact with the server (" + error.message + "). The agents may still be working; open this topic from your history to check again.");
      } else {
        // Wait a little longer after each failure (simple back-off).
        clearTimeout(state.pollTimer);
        state.pollTimer = setTimeout(pollOnce, CONFIG.POLL_INTERVAL_MS * (state.pollFailures + 1));
      }
    }
  }

  // ------------------------------------------------------------------
  // Progress view
  // ------------------------------------------------------------------

  function renderProgress(generation) {
    showViewIfHidden("progress");
    document.title = generation.topic + " - generating";
    $("progress-topic").textContent = generation.topic;
    $("error-box").hidden = true;
    $("progress-foot").hidden = false;
    $("progress-kicker").textContent = "Preparing your notes on";

    const done = generation.progress.completed_steps;
    const isRunning = generation.status === "processing";

    // Each station's state comes ONLY from completed_steps reported by the server.
    document.querySelectorAll("#relay-live .station").forEach(function (station) {
      const step = Number(station.dataset.step);
      const number = station.querySelector(".station-num");
      const stateText = station.querySelector(".station-state");
      let stationState = "waiting";
      if (step <= done) stationState = "done";
      else if (isRunning && step === done + 1) stationState = "active";
      station.dataset.state = stationState;
      stateText.textContent = { done: "Finished", active: "Working now", waiting: "Waiting" }[stationState];
      number.replaceChildren();
      if (stationState === "done") {
        number.appendChild(svgIcon("i-check"));
      } else {
        number.textContent = String(step);
      }
    });

    let message;
    if (generation.status === "pending") {
      message = "Queued. The agents will start in a moment.";
    } else if (done >= 4) {
      message = "All four agents have finished. Checking and saving your notes.";
    } else {
      message = "Step " + (done + 1) + " of 4: the " + ROLES[done] + " is working.";
    }
    $("progress-status").textContent = message;
    startElapsedTimer(generation.created_at);
  }

  function showViewIfHidden(name) {
    if ($("view-" + name).hidden) showView(name);
  }

  function svgIcon(id) {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("class", "icon");
    svg.setAttribute("aria-hidden", "true");
    const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
    use.setAttribute("href", "#" + id);
    svg.appendChild(use);
    return svg;
  }

  function startElapsedTimer(createdAt) {
    if (state.elapsedTimer) return;
    const tick = function () { $("elapsed").textContent = formatDuration(secondsBetween(createdAt)); };
    tick();
    state.elapsedTimer = setInterval(tick, 1000);
  }

  function showFailure(generation, message) {
    showViewIfHidden("progress");
    if (generation.topic) $("progress-topic").textContent = generation.topic;
    $("progress-kicker").textContent = "Notes requested on";
    $("progress-status").textContent = "";
    $("progress-foot").hidden = true;
    $("error-text").textContent = message;
    $("error-box").hidden = false;
    $("retry-button").hidden = !generation.topic;
    $("retry-button").dataset.topic = generation.topic || "";

    // Mark the step that was running when it failed (only if it had started).
    if (generation.progress && generation.started_at && generation.progress.completed_steps < 4) {
      const failedStep = document.querySelector('#relay-live .station[data-step="' + (generation.progress.completed_steps + 1) + '"]');
      if (failedStep) {
        failedStep.dataset.state = "failed";
        failedStep.querySelector(".station-state").textContent = "Stopped here";
      }
    }
    document.title = (generation.topic || "Generation") + " - failed";
  }

  // ------------------------------------------------------------------
  // Result view
  // ------------------------------------------------------------------

  function renderResult(generation) {
    showView("result");
    document.title = generation.topic + " - learning notes";
    $("result-topic").textContent = generation.topic;

    const meta = $("result-meta");
    meta.replaceChildren(
      el("span", "", "Generated " + formatDate(generation.completed_at)),
      el("span", "", "Took " + formatTook(secondsBetween(generation.created_at, generation.completed_at)))
    );
    $("download-link").href = Api.downloadUrl(generation.id);

    const warnings = generation.warnings || [];
    $("result-warnings").hidden = warnings.length === 0;
    $("result-warnings-list").replaceChildren(
      ...warnings.map(function (warning) { return el("li", "", warning); })
    );

    $("plan-content").replaceChildren(SafeMarkdown.toFragment(generation.teaching_plan || ""));
    $("explanation-content").replaceChildren(SafeMarkdown.toFragment(generation.explanation || ""));

    const qaList = $("qa-list");
    qaList.replaceChildren();
    (generation.qa_pairs || []).forEach(function (pair) {
      const item = el("li", "qa-item");
      const body = el("div");
      body.appendChild(el("h3", "qa-question", pair.question));
      const answer = el("div", "prose qa-answer");
      if (pair.answer.indexOf(NOT_COVERED) === 0) answer.classList.add("qa-not-covered");
      answer.appendChild(SafeMarkdown.toFragment(pair.answer));
      body.appendChild(answer);
      item.appendChild(body);
      qaList.appendChild(item);
    });

    const summaryList = $("summary-list");
    summaryList.replaceChildren();
    (generation.summary_points || []).forEach(function (point) {
      const item = el("li");
      // Points are short Markdown lines (may contain `code` or **bold**).
      const fragment = SafeMarkdown.toFragment(point);
      const paragraph = fragment.querySelector("p");
      item.appendChild(paragraph || fragment);
      summaryList.appendChild(item);
    });

    $("notes-rendered").replaceChildren(
      SafeMarkdown.toFragment(generation.markdown || "", { headingOffset: 2 })
    );
    $("notes-raw").textContent = generation.markdown || "";
    setNotesView("rendered");
    watchSections();
  }

  function setNotesView(view) {
    document.querySelectorAll("[data-notes-view]").forEach(function (button) {
      button.setAttribute("aria-pressed", String(button.dataset.notesView === view));
    });
    $("notes-rendered").hidden = view !== "rendered";
    $("notes-raw").hidden = view !== "raw";
  }

  // Highlight the section-nav link for the section currently on screen.
  function watchSections() {
    if (!("IntersectionObserver" in window)) return;
    if (state.sectionObserver) state.sectionObserver.disconnect();
    const links = document.querySelectorAll(".toc a");
    state.sectionObserver = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        links.forEach(function (link) {
          link.setAttribute("aria-current", String(link.dataset.section === entry.target.id));
        });
      });
    }, { rootMargin: "-30% 0px -60% 0px" });
    document.querySelectorAll(".result-section").forEach(function (section) {
      state.sectionObserver.observe(section);
    });
  }

  function textForCopy(kind) {
    const g = state.current;
    if (!g) return "";
    if (kind === "all") return g.markdown || "";
    if (kind === "explanation") return g.explanation || "";
    if (kind === "qa") {
      return (g.qa_pairs || []).map(function (pair, i) {
        return "Q" + (i + 1) + ". " + pair.question + "\n" + pair.answer;
      }).join("\n\n");
    }
    if (kind === "summary") {
      return (g.summary_points || []).map(function (point, i) { return (i + 1) + ". " + point; }).join("\n");
    }
    return "";
  }

  // ------------------------------------------------------------------
  // History
  // ------------------------------------------------------------------

  async function loadHistory() {
    const list = $("history-list");
    const empty = $("history-empty");
    try {
      const data = await Api.listGenerations(CONFIG.HISTORY_LIMIT);
      list.replaceChildren();
      data.items.forEach(function (item) {
        const row = el("button", "history-row");
        row.type = "button";
        row.dataset.id = item.id;
        row.appendChild(el("span", "history-topic", item.topic));
        const date = el("time", "history-date", formatDate(item.created_at));
        date.dateTime = item.created_at;
        row.appendChild(date);
        row.appendChild(el("span", "status-pill status-" + item.status, statusLabel(item.status)));
        row.setAttribute("aria-label", "Open " + item.topic + ", " + statusLabel(item.status));
        const li = el("li", "history-item");
        li.appendChild(row);
        list.appendChild(li);
      });
      empty.textContent = "Your generated notes will appear here. Pick a topic above to create your first set.";
      empty.hidden = data.items.length > 0;
    } catch (error) {
      list.replaceChildren();
      empty.textContent = "History could not be loaded: " + error.message;
      empty.hidden = false;
    }
  }

  // ------------------------------------------------------------------
  // Event wiring
  // ------------------------------------------------------------------

  function bindEvents() {
    $("topic-form").addEventListener("submit", function (event) {
      event.preventDefault();
      submitTopic($("topic-input").value);
    });
    $("topic-input").addEventListener("input", function () {
      updateCounter();
      if ($("topic-input").getAttribute("aria-invalid") === "true") setFormError("");
    });

    $("example-topics").addEventListener("click", function (event) {
      const chip = event.target.closest(".chip");
      if (!chip) return;
      $("topic-input").value = chip.textContent;
      updateCounter();
      setFormError("");
      $("topic-input").focus();
    });

    $("history-list").addEventListener("click", function (event) {
      const row = event.target.closest(".history-row");
      if (row) window.location.hash = "#/generation/" + row.dataset.id;
    });
    $("history-refresh").addEventListener("click", function () {
      loadHistory().then(function () { showToast("History updated"); });
    });

    $("retry-button").addEventListener("click", function () {
      const topic = $("retry-button").dataset.topic;
      if (topic) submitTopic(topic);
    });

    document.querySelectorAll("[data-notes-view]").forEach(function (button) {
      button.addEventListener("click", function () { setNotesView(button.dataset.notesView); });
    });

    // One listener for every element with data-action / data-copy / section links.
    document.addEventListener("click", function (event) {
      const action = event.target.closest("[data-action]");
      if (action) {
        event.preventDefault();
        if (action.dataset.action === "go-home") {
          goHome();
        } else if (action.dataset.action === "go-section") {
          if ($("view-home").hidden) goHome();
          const target = $(action.dataset.target);
          if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
        }
        return;
      }

      const copyButton = event.target.closest("[data-copy]");
      if (copyButton) {
        const text = textForCopy(copyButton.dataset.copy);
        if (!text) return;
        copyText(text)
          .then(function () { showToast("Copied to clipboard"); })
          .catch(function () { showToast("Copy failed. Select the text and copy it manually.", true); });
        return;
      }

      const tocLink = event.target.closest(".toc a");
      if (tocLink) {
        // Scroll without changing the URL hash (the hash stores the open generation).
        event.preventDefault();
        const section = $(tocLink.dataset.section);
        if (section) section.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    });

    // Back/forward buttons and hash links both re-route.
    window.addEventListener("hashchange", openGenerationFromHash);
    window.addEventListener("popstate", openGenerationFromHash);
  }

  function init() {
    bindEvents();
    updateCounter();
    checkHealth();
    loadHistory();
    openGenerationFromHash();
  }

  // Expose a few pure helpers for automated tests; not used by the page itself.
  window.AppTestHooks = { validateTopic: validateTopic, formatDuration: formatDuration };

  document.addEventListener("DOMContentLoaded", init);
})();
