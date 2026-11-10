# Learning Roadmap

Study the project in this order. Each stage lists what to learn, which real files to read, what you should be able to explain afterwards, small exercises, and a checkpoint. Don't move on until you can pass the checkpoint without looking.

A suggested pace is one stage every two or three days, but go at whatever speed lets you explain things in your own words.

Before stage 1, get the app running once (see [SETUP_AND_EXECUTION.md](SETUP_AND_EXECUTION.md)) and generate notes for a topic you know well. Seeing the result first makes the code easier to follow.

---

## Stage 1 — Python fundamentals used in this project

**Topics:** functions and type hints; `dict` and `list`; f-strings; `import` and packages (`__init__.py`); classes and `@dataclass`; `@property`; exceptions (`try/except/finally`, custom exception classes, `raise ... from`); `with` blocks; `enumerate`; list comprehensions; keyword-only arguments (`*`); closures and `nonlocal`; `lambda`; `Enum`; regular expressions (`re`); `pathlib.Path`; `os.getenv`.

**Files:** `backend/app/core/config.py`, `backend/app/services/markdown_builder.py`, `backend/app/services/output_parser.py`.

**Understand:** why `Settings` is frozen; what `@lru_cache` does; how `build_learning_notes` builds a list of lines and joins them; how a regex captures groups.

**Exercises:**
1. In a Python shell, run `from app.services.markdown_builder import make_download_filename` (from `backend/`) and try ten topics, including symbols and non-English text.
2. Write a regex that matches `Step 1: ...` lines and test it with `re.match`.
3. Write a function using `nonlocal` that counts how many times it was called.

**Checkpoint:** explain, line by line, `make_download_filename` and `parse_summary_output`.

---

## Stage 2 — Project architecture and folder structure

**Topics:** separation of concerns; layers (routes → services → database); packages; configuration via environment variables.

**Files:** `README.md`, `docs/ARCHITECTURE.md`, the folder tree, every `__init__.py`.

**Understand:** which folder you'd open to change (a) a URL, (b) a validation rule, (c) an agent prompt, (d) a database column.

**Exercises:**
1. Draw the folder tree from memory and label each folder's job.
2. Trace one request from `api.js` to SQLite on paper, naming each function.

**Checkpoint:** give the 60-second introduction from [INTERVIEW_PREPARATION.md](INTERVIEW_PREPARATION.md) in your own words.

---

## Stage 3 — CrewAI and LLM integration

**Topics:** LLM, prompt, token, temperature, reasoning model; CrewAI `LLM`, `Agent`, `Task`, `Crew`, `Process.sequential`; `context`; `kickoff(inputs=...)` and `{topic}` placeholders; `task_callback`; `CrewOutput.tasks_output`; why output validation is needed.

**Files:** `backend/app/services/crewai_service.py`, then `output_parser.py`, then `tests/fakes.py`.

**Understand:** why each task has its own `context`; why the summary writer only sees the explanation; why CrewAI is imported inside functions; what `after_each_task` does; why the explanation ends with a marker.

**Exercises:**
1. In a scratch script (outside the app), build a two-agent crew and run it once with your key. Print `result.tasks_output[0].raw`. (This makes real Groq calls; keep it small.)
2. Change `SUMMARY_TASK` to ask for 6 bullets *without* changing the parser, run the tests, and see which test protects you. Then undo it.
3. Write a fake coordinator output with only two questions and pass it to `parse_coordinator_output` to see the error.

**Checkpoint:** explain the four-agent sequence diagram in ARCHITECTURE.md section 5 without notes.

---

## Stage 4 — FastAPI fundamentals

**Topics:** the `FastAPI` app object; decorators (`@router.get`); path and query parameters; request bodies; `APIRouter` and `prefix`; `Depends`; `HTTPException`; `response_model`; `status_code`; `lifespan`; middleware; exception handlers; `StaticFiles`; Uvicorn.

**Files:** `backend/app/main.py`, `backend/app/api/routes/system.py`, `backend/app/api/routes/generations.py`.

**Understand:** how `uvicorn app.main:app` finds the app; the order of `create_app()`; why routes contain almost no logic.

**Exercises:**
1. Add a `GET /api/stats` endpoint that returns how many generations exist in each status. Write a test for it.
2. Open `/docs` and send every request from the browser.

**Checkpoint:** explain what happens between "request arrives" and "route function runs".

---

## Stage 5 — HTTP and REST APIs

**Topics:** methods (GET, POST); status codes (200, 202, 404, 409, 413, 422, 429, 500, 503); headers (`Content-Type`, `Content-Disposition`); REST resource naming; idempotency (GET can be repeated safely; POST creates something new each time).

**Files:** `docs/API_REFERENCE.md`, `routes/generations.py`.

**Understand:** why POST returns 202; when 409 is used; why download uses `Content-Disposition: attachment`.

**Exercises:**
1. Use `curl.exe` (PowerShell) or `curl` (Git Bash) to call every endpoint, including error cases.
2. Open your browser's DevTools → *Network* tab while generating notes. Watch the POST and the repeated GETs.

**Checkpoint:** for each status code the API uses, describe the situation that produces it.

---

## Stage 6 — JSON and Pydantic

**Topics:** JSON types; `BaseModel`; `Field` constraints; `ConfigDict` (`str_strip_whitespace`, `extra="forbid"`, `from_attributes`); `field_validator` (`mode="before"` vs `"after"`); serialization of datetimes.

**Files:** `backend/app/schemas/generation.py`, `tests/test_schemas.py`.

**Understand:** the exact order of the topic checks; why `from_attributes=True` is needed for SQLAlchemy objects; why timestamps get UTC attached.

**Exercises:**
1. In a Python shell, create `GenerationCreate(topic=...)` with ten different inputs and read the errors.
2. Add a rule rejecting topics that are only digits; add a test.

**Checkpoint:** explain what happens to `"  Python \t decorators "` (hint: one rule rejects it).

---

## Stage 7 — SQLite and SQLAlchemy

**Topics:** tables, rows, primary keys, indexes; engine, session, `add`, `commit`, `refresh`, `get`; `select`, `update`, `func.count`; `Mapped` and `mapped_column`; JSON columns; sessions per thread.

**Files:** `backend/app/database/database.py`, `backend/app/database/models.py`, `backend/app/services/generation_service.py` (top half), `tests/test_database.py`.

**Understand:** why `get_db` uses `yield`; why the background job opens its own session; what `fail_interrupted_generations` does.

**Exercises:**
1. Open `backend/data/learning_assistant.db` with "DB Browser for SQLite" and look at your rows.
2. Add a `duration_seconds` property to `Generation` (computed, not a column) and print it for each row.

**Checkpoint:** write, from memory, the code that inserts a pending generation.

---

## Stage 8 — Background job processing

**Topics:** synchronous vs asynchronous work; threads; FastAPI `BackgroundTasks`; job states; polling; what happens on restart.

**Files:** `generation_service.run_generation`, `routes/generations.submit_generation`, ARCHITECTURE.md section 8.

**Understand:** each status transition and which line causes it; why sessions are short; the restart limitation.

**Exercises:**
1. Start a generation and stop the server with Ctrl+C mid-run. Restart and check the row's error message.
2. Set `MAX_ACTIVE_GENERATIONS=1`, start two topics quickly, and observe the 429.

**Checkpoint:** explain the state diagram in ARCHITECTURE.md and the restart limitation.

---

## Stage 9 — HTML and CSS

**Topics:** semantic elements (`header`, `main`, `section`, `nav`, `article`); forms; `hidden`; ARIA basics; SVG sprites; CSS custom properties; flexbox; grid; `position: sticky`; media queries; `prefers-reduced-motion`.

**Files:** `frontend/index.html`, `frontend/css/styles.css`.

**Understand:** how the three views are laid out; how the relay rail is drawn with `::after`; what changes at 1024 px and 640 px.

**Exercises:**
1. Change `--teal` to another colour and see everything that updates.
2. Use DevTools' device toolbar to view the page at 390, 768 and 1440 px.

**Checkpoint:** explain how `.history-row` rearranges on a phone.

---

## Stage 10 — JavaScript and `fetch`

**Topics:** `const`/`let`; functions and closures; IIFEs; DOM (`getElementById`, `createElement`, `textContent`, `replaceChildren`); events and delegation; `async`/`await`; `fetch`; `AbortController`; timers (`setTimeout`, `setInterval`); classes (`ApiError`).

**Files:** `frontend/js/config.js`, `frontend/js/api.js`, then `frontend/js/app.js`.

**Understand:** how `request()` turns HTTP errors into messages; how `handleGeneration` chooses what to show; why `textContent` is used.

**Exercises:**
1. In DevTools' Console, call `await Api.health()` and `await Api.listGenerations(3)`.
2. Change `POLL_INTERVAL_MS` to 5000 and watch the Network tab.

**Checkpoint:** explain `pollOnce` including its failure handling.

---

## Stage 11 — Frontend/backend integration

**Topics:** origins and CORS; same-origin serving at `/app`; the URL hash; Content-Security-Policy; safe rendering of untrusted text.

**Files:** `config.js` (`resolveApiBaseUrl`), `main.py` (CORS, CSP, `StaticFiles`), `markdown.js`.

**Understand:** why no CORS is needed at `/app`; why port 5500 needs it; how the hash makes refresh work; both safety layers of `markdown.js`.

**Exercises:**
1. Serve the frontend with `python -m http.server 5500` and remove port 5500 from `CORS_ORIGINS`; read the browser error, then restore it.
2. Run `node --test frontend/tests/markdown.test.js` and add one more XSS test.

**Checkpoint:** explain what would happen if `renderResult` used `innerHTML = generation.explanation`.

---

## Stage 12 — Error handling

**Topics:** exceptions vs HTTP errors; custom exception types; catch-specific-first; never leaking internals; user-facing messages.

**Files:** `main.py` handlers, `crewai_service.safe_error_message`, `generation_service.run_generation`, `api.js`, `app.js` (`showFailure`).

**Understand:** the error map in ARCHITECTURE.md section 9.

**Exercises:**
1. Remove your key from `.env`, restart, and follow the 503 from server to banner.
2. Write a test for a new failure case (e.g., the coordinator returns empty text).

**Checkpoint:** for any row in the error map, point to the exact line that handles it.

---

## Stage 13 — Testing

**Topics:** pytest discovery; fixtures and `autouse`; `monkeypatch`; `parametrize`; `tmp_path`; `importorskip`; FastAPI `TestClient`; mocking external services; Node's `node:test`.

**Files:** `backend/tests/conftest.py`, `fakes.py`, `test_api.py`, then the other test files; `frontend/tests/markdown.test.js`.

**Understand:** why no test can reach Groq; how each API test gets a clean database.

**Exercises:**
1. Run `pytest -v`, then break one line in `output_parser.py` and see which tests fail.
2. Write a test that submits two topics and checks `count_active_generations` returns 0 afterwards.

**Checkpoint:** explain `block_live_llm_calls` and `fake_crew`.

---

## Stage 14 — Deployment

**Topics:** environment variables in hosting; build and start commands; `--host 0.0.0.0` and `$PORT`; ephemeral vs persistent disks; secrets; rate limiting and auth for public apps.

**Files:** `docs/SETUP_AND_EXECUTION.md` (Deploying online), `.env.example`, `config.py`.

**Understand:** why one service is simplest; what happens to SQLite on a free host; what to add before going public.

**Exercises:**
1. Run locally with `APP_ENV=production` and confirm `/docs` disappears.
2. Write down a deployment plan for your chosen host, including every environment variable.

**Checkpoint:** explain your deployment plan and its costs and limitations to a friend.

---

## Final check

You're done when you can, without notes:

- Demo the app and narrate what each agent is doing.
- Draw the architecture and the job lifecycle.
- Answer the 35 questions in INTERVIEW_PREPARATION.md.
- Add a small feature (for example, deleting a history item) with a test.
