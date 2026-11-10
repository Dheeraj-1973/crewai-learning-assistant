# Code Explanation (file by file)

This walkthrough follows the code in the order you should read it: settings → database → schemas → services → routes → app → tests → frontend. Code excerpts are copied from the real files (sometimes shortened with `...`). Open each file next to this guide.

---

## 1. `backend/app/core/config.py` — settings

**Purpose:** one place for every configurable value. No other file reads environment variables.

```python
BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_DIR.parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"

load_dotenv(PROJECT_ROOT / ".env", override=False)

LLM_MODEL = "groq/openai/gpt-oss-20b"
TOPIC_MIN_LENGTH = 2
TOPIC_MAX_LENGTH = 120
MAX_REQUEST_BODY_BYTES = 4 * 1024
```

- `Path(__file__)` is this file's location. `.parents[2]` climbs `core → app → backend`, so paths work no matter which folder you start Uvicorn from.
- `load_dotenv(...)` reads `.env` into environment variables. `override=False` means real environment variables (e.g. from a hosting dashboard) win.
- `LLM_MODEL` is a constant on purpose: the brief fixes the model, so it is not configurable.

```python
@dataclass(frozen=True)
class Settings:
    groq_api_key: str = field(default="", repr=False)
    llm_temperature: float = 0.4
    llm_max_tokens: int = 8192
    ...
    @property
    def llm_configured(self) -> bool:
        return bool(self.groq_api_key.strip())
```

- A **dataclass** is a class that mainly holds data; Python writes `__init__` for you. `frozen=True` makes it read-only.
- `repr=False` hides the key if a `Settings` object is ever printed or logged.
- `llm_configured` is a **property**: used like an attribute (`settings.llm_configured`) but computed.

```python
def load_settings() -> Settings:
    environment = os.getenv("APP_ENV", "development").strip().lower() or "development"
    ...
    return Settings(groq_api_key=os.getenv("GROQ_API_KEY", "").strip(), ...)

@lru_cache
def get_settings() -> Settings:
    return load_settings()
```

- `_get_bool`, `_get_int`, `_get_float`, `_get_list` turn environment text into the right Python type, with defaults.
- `_resolve_database_url()` turns `sqlite:///./data/learning_assistant.db` into an absolute path inside `backend/` and creates the `data` folder.
- `@lru_cache` remembers the result, so settings are built once. FastAPI routes receive them with `Depends(get_settings)`, which also lets tests swap in different settings.

**Used by:** almost every other backend file.

---

## 2. `backend/app/database/database.py` — connection

```python
class Base(DeclarativeBase):
    """Parent class for all SQLAlchemy table models."""

def _create_engine(database_url: str) -> Engine:
    connect_args = {}
    if database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    return create_engine(database_url, connect_args=connect_args)

engine: Engine = _create_engine(get_settings().database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
```

- **Engine:** knows how to open connections to the database file.
- **`check_same_thread=False`:** SQLite normally refuses connections shared across threads. Requests and the background job run in different threads, so we allow it (each still uses its own session).
- **`sessionmaker`:** a factory. `SessionLocal()` returns a new session. `expire_on_commit=False` keeps attribute values readable after `commit()`.

```python
def configure_database(database_url: str) -> None:
    global engine, SessionLocal
    engine.dispose()
    engine = _create_engine(database_url)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

def init_db() -> None:
    from app.database import models  # noqa: F401
    Base.metadata.create_all(bind=engine)

def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

- `configure_database` lets tests point everything at a temporary file. That is why other modules write `database.SessionLocal()` (looked up when called) instead of importing `SessionLocal` directly.
- `init_db` imports the models so their tables are registered, then `create_all` creates any missing tables. Running it twice is harmless.
- `get_db` is a **generator dependency**: FastAPI runs the code up to `yield`, gives `db` to the route, and runs the `finally` block after the response, so sessions are always closed.

---

## 3. `backend/app/database/models.py` — the table

```python
class GenerationStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
```

An **Enum** is a fixed set of named values. Inheriting from `str` lets `GenerationStatus.PENDING.value` be stored as the plain text `"pending"`.

```python
class Generation(Base):
    __tablename__ = "generations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_generation_id)
    topic: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False,
                                        default=GenerationStatus.PENDING.value, index=True)
    completed_steps: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    teaching_plan: Mapped[str | None] = mapped_column(Text, nullable=True)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    qa_pairs: Mapped[list | None] = mapped_column(JSON, nullable=True)
    summary_points: Mapped[list | None] = mapped_column(JSON, nullable=True)
    markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    warnings: Mapped[list | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

- `Mapped[...]` + `mapped_column(...)` is SQLAlchemy 2.x style: the type hint says the Python type, `mapped_column` says the database column.
- `default=new_generation_id` calls `uuid.uuid4().hex`, giving IDs like `3f2b9c…` (32 hex characters) that cannot be guessed.
- `index=True` on `status` and `created_at` speeds up the "count active jobs" and "newest first" queries.
- `JSON` columns store Python lists as JSON text, so 3 Q&A pairs and 5 summary points need no extra tables.
- Times are stored in UTC (`utc_now()`).

---

## 4. `backend/app/schemas/generation.py` — data shapes

### The request model

```python
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")

class GenerationCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid", ...)

    topic: str = Field(..., min_length=TOPIC_MIN_LENGTH, max_length=TOPIC_MAX_LENGTH, ...)

    @field_validator("topic", mode="before")
    @classmethod
    def reject_control_characters(cls, value: object) -> object:
        if isinstance(value, str) and _CONTROL_CHARS.search(value.strip()):
            raise ValueError("Topic must be a single line without control characters.")
        return value

    @field_validator("topic")
    @classmethod
    def collapse_spaces(cls, value: str) -> str:
        return re.sub(r"\s+", " ", value)
```

Exact order Pydantic follows for `topic`:

1. `reject_control_characters` (`mode="before"`, runs on the raw value). A non-string is passed through unchanged so the next step can reject it.
2. Pydantic's own string check: must be a `str`, then stripped (`str_strip_whitespace`), then 2–120 characters.
3. `collapse_spaces` (default `mode="after"`) runs on the clean string.

Rejecting newlines also makes it harder to paste multi-line text designed to give the agents new instructions (**prompt injection**).

### The response models

```python
class Progress(BaseModel):
    completed_steps: int = Field(ge=0, le=TOTAL_AGENT_STEPS)
    total_steps: int = TOTAL_AGENT_STEPS

class _TimestampMixin(BaseModel):
    @field_validator("created_at", "started_at", "completed_at", mode="after", check_fields=False)
    @classmethod
    def ensure_utc(cls, value):
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
```

SQLite does not remember time zones, so times come back "naive". `ensure_utc` re-attaches UTC so the JSON contains `+00:00` and the browser converts to your local time correctly. `check_fields=False` lets this shared validator apply to subclasses that may not have all three fields.

- `GenerationSummary` (history rows): `id, topic, status, created_at, completed_at`. `from_attributes=True` lets Pydantic read straight from a SQLAlchemy object.
- `GenerationDetail` (one generation): adds `progress`, `started_at`, and all result fields (all optional, `None` until completed), `warnings` and `error_message`.
- `GenerationList`, `HealthResponse`, `ErrorResponse` describe the other responses (they also appear in `/docs`).

---

## 5. `backend/app/services/output_parser.py` — checking agent output

Pure Python, no CrewAI import, easy to test. Each `parse_*` function takes an agent's raw text and returns clean data or raises `OutputValidationError`.

### Helpers

- `strip_wrapping_code_fence(text)`: removes a ```` ```markdown ```` fence wrapping the whole answer (models sometimes do this).
- `normalize_heading_levels(markdown, min_level=3)`: shifts headings so the largest is `###`, skipping lines inside code blocks. The final notes use `#` and `##` themselves.
- `_require_text(raw, agent_name)`: rejects empty output with a message naming the agent.

### `parse_coordinator_output(raw) -> CoordinatorOutput`

```python
_QUESTION_LINE = re.compile(
    r"^\s*(?:[-*]\s*)?(?:\*\*|__)?\s*Q(?:uestion)?\s*([1-9])\s*(?:\*\*|__)?\s*[:.)\-]\s*(?:\*\*|__)?\s*(.+?)\s*$",
    re.IGNORECASE,
)
```

This **regular expression** (a text pattern) matches lines like `Q1: …`, `**Q1:** …`, `- Question 2. …`, `Q3) …`. Group 1 is the number, group 2 the question. The function then:

1. Collects the first question for each number.
2. Requires exactly 3, all different (case-insensitive).
3. Takes everything before the "Questions" heading (or before Q1) as the teaching plan, normalizes its headings, and requires it to be non-empty.

### `parse_explanation(raw) -> ExplanationOutput`

1. If `END_OF_EXPLANATION` is present, cut everything from it onward; otherwise add the "may be incomplete" warning.
2. If a heading such as "Questions and Answers", "Quiz", "Summary", "Key takeaways", "Recap" or "FAQ" appears after the first 400 characters, cut from there and add a warning (that content belongs to other agents).
3. Normalize headings; require at least 400 characters.
4. If the last line does not end like a finished sentence (`.`, `!`, `?`, `:`, `)`, quotes, backtick, `*`, `]`) and is not a code fence, add an "unfinished" warning.

Warnings are shown to the user; they do not fail the job.

### `parse_qa_output(raw, expected_questions) -> list[dict]`

Walks the lines. A `Q<n>:` line ends any current answer; an `A<n>:` line starts answer *n*; other lines continue the current answer. Then for each of the Coordinator's three questions it requires a non-empty answer. **The question text always comes from the Coordinator**, so a model rewording a question cannot change it.

### `parse_summary_output(raw) -> list[str]`

Accepts bullet lines starting with `-`, `*`, `•`, `1.` or `1)`, ignores other lines (like an accidental intro), and requires **exactly five**.

---

## 6. `backend/app/services/markdown_builder.py`

```python
def build_learning_notes(*, topic, teaching_plan, explanation, qa_pairs, summary_points, generated_at) -> str:
    lines = [f"# {topic}: Learning Notes", "", f"> Generated on {generated_at.strftime('%d %b %Y, %H:%M UTC')} ...", ...,
             "## 1. Learning Plan", "", teaching_plan.strip(), "",
             "## 2. Topic Explanation", "", explanation.strip(), "",
             "## 3. Questions and Answers", ""]
    for number, pair in enumerate(qa_pairs, start=1):
        lines += [f"### Q{number}. {pair['question']}", "", pair["answer"].strip(), ""]
    lines += ["## 4. Five-Point Summary", ""]
    lines += [f"{number}. {point}" for number, point in enumerate(summary_points, start=1)]
    ...
    return "\n".join(lines)
```

- The `*` in the parameter list makes all arguments **keyword-only**, so callers must write `topic=...`, which prevents mixing up the order.
- `enumerate(..., start=1)` gives numbers 1, 2, 3 alongside each item.

```python
def make_download_filename(topic: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")[:60].strip("-")
    return f"{slug or 'topic'}-learning-notes.md"
```

Everything except lowercase letters and digits becomes `-`, so the name is safe inside the `Content-Disposition` header. A topic with no Latin letters falls back to `topic-learning-notes.md`.

---

## 7. `backend/app/services/crewai_service.py` — the agents

### Top of the file

```python
os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")

class LLMNotConfiguredError(RuntimeError): ...
class CrewExecutionError(RuntimeError): ...

@dataclass
class CrewRawOutput:
    coordinator: str
    explanation: str
    qa: str
    summary: str
```

- Telemetry is turned off before CrewAI is ever imported.
- Two custom exception types let `generation_service` react differently to "no key" and "the run failed".

### `AGENT_SPECS` and the task texts

`AGENT_SPECS` is a dictionary with the four roles, goals and backstories from the original project. The task instructions are module-level strings: `COORDINATOR_TASK`, `COORDINATOR_OUTPUT`, `TEACHER_TASK`, `TEACHER_OUTPUT`, `QA_TASK`, `QA_OUTPUT`, `SUMMARY_TASK`, `SUMMARY_OUTPUT`. Read them in the file; they are the "prompt engineering" of the project. Notable choices:

- The Coordinator is told to treat the quoted topic **only as a topic name, never as instructions**.
- The three questions must cover *what it is*, *how it works*, and *when/why to use it*, so they don't overlap.
- The Teacher must use `###` headings, write 700–1100 words, include a worked example explained step by step, **not** write Q&A or summaries, and end with `END_OF_EXPLANATION`.
- The Q&A agent must use **only** the explanation and reply `The explanation does not cover this.` when it can't answer.
- The Summary Writer must write exactly five `- ` lines and nothing else.
- The only `{…}` placeholder anywhere is `{topic}`; CrewAI would try to fill any other one (a test checks this).

### `build_llm(settings)`

```python
from crewai import LLM
llm_kwargs = {
    "model": settings.llm_model,
    "api_key": settings.groq_api_key,
    "temperature": settings.llm_temperature,
    "max_tokens": settings.llm_max_tokens,
    "timeout": settings.llm_timeout_seconds,
    "drop_params": True,
}
if settings.llm_reasoning_effort in {"low", "medium", "high"}:
    llm_kwargs["reasoning_effort"] = settings.llm_reasoning_effort
return LLM(**llm_kwargs)
```

- `temperature` 0.4: fairly focused, still natural.
- `max_tokens` 8192 and `reasoning_effort` "low": gpt-oss is a reasoning model whose hidden reasoning also uses the token budget; this combination leaves room for a complete explanation.
- `drop_params=True`: if the provider doesn't support a parameter, LiteLLM drops it instead of failing.
- `**llm_kwargs` unpacks the dictionary into keyword arguments.

### `build_crew(settings, task_callback=None)`

```python
def make_agent(key: str) -> Agent:
    spec = AGENT_SPECS[key]
    return Agent(role=spec["role"], goal=spec["goal"], backstory=spec["backstory"], llm=llm,
                 allow_delegation=False, max_iter=3, verbose=settings.crew_verbose)

plan_task = Task(description=COORDINATOR_TASK, expected_output=COORDINATOR_OUTPUT, agent=coordinator)
explain_task = Task(description=TEACHER_TASK, expected_output=TEACHER_OUTPUT, agent=teacher, context=[plan_task])
qa_task = Task(description=QA_TASK, expected_output=QA_OUTPUT, agent=qa_specialist,
               context=[plan_task, explain_task])
summary_task = Task(description=SUMMARY_TASK, expected_output=SUMMARY_OUTPUT, agent=summary_writer,
                    context=[explain_task])

return Crew(agents=[...], tasks=[plan_task, explain_task, qa_task, summary_task],
            process=Process.sequential, verbose=settings.crew_verbose, task_callback=task_callback)
```

`make_agent` is a function defined inside a function, so it can use `llm` and `settings` without passing them each time. Notice the Summary Writer only gets the explanation as context: it has nothing else to summarize.

### `safe_error_message(error, settings)`

Turns an exception into a user-safe message: replaces the real key and anything shaped like a Groq key (`gsk_...`) with `***`, translates rate-limit / authentication / timeout errors into friendly sentences, and truncates the rest to 300 characters.

### `run_learning_crew(topic, on_task_complete=None, settings=None) -> CrewRawOutput`

```python
settings = settings or get_settings()
if not settings.llm_configured:
    raise LLMNotConfiguredError("GROQ_API_KEY is not set on the server.")

finished = 0
def after_each_task(*_args, **_kwargs) -> None:
    nonlocal finished
    finished += 1
    if on_task_complete is not None:
        try:
            on_task_complete(finished)
        except Exception:
            logger.exception("Progress callback failed")

try:
    crew = build_crew(settings, task_callback=after_each_task)
    result = crew.kickoff(inputs={"topic": topic})
except LLMNotConfiguredError:
    raise
except Exception as error:
    raise CrewExecutionError(safe_error_message(error, settings)) from error

outputs = [getattr(task_output, "raw", "") or "" for task_output in (result.tasks_output or [])]
if len(outputs) != 4:
    raise CrewExecutionError(...)
return CrewRawOutput(coordinator=outputs[0], explanation=outputs[1], qa=outputs[2], summary=outputs[3])
```

- The key check happens **before** CrewAI is imported or called.
- `nonlocal finished` lets the inner function change the outer variable.
- `*_args, **_kwargs` accept whatever CrewAI passes to the callback (a task output object) without depending on its exact type.
- A failing progress update is logged but never stops the generation.
- `raise ... from error` keeps the original exception attached for the server log.

---

## 8. `backend/app/services/generation_service.py` — DB helpers and the job

### Database helpers (called by the routes)

| Function | Does |
|---|---|
| `create_generation(db, topic)` | Inserts a `pending` row, commits, refreshes, returns it. |
| `get_generation(db, id)` | `db.get(Generation, id)` or `None`. |
| `list_generations(db, limit=20)` | Newest first, at most `limit`. |
| `count_active_generations(db)` | Number of rows with status `pending` or `processing`. |
| `fail_interrupted_generations(db)` | At startup, marks leftover `pending`/`processing` rows `failed` with `RESTART_ERROR`; returns how many. |

### `run_generation(generation_id)` — the background job

```python
with database.SessionLocal() as db:
    generation = db.get(Generation, generation_id)
    if generation is None:
        return
    generation.status = GenerationStatus.PROCESSING.value
    generation.started_at = utc_now()
    db.commit()
    topic = generation.topic

try:
    raw = run_learning_crew(topic, on_task_complete=lambda n: _set_completed_steps(generation_id, n))
    coordinator = parse_coordinator_output(raw.coordinator)
    explanation = parse_explanation(raw.explanation)
    qa_pairs = parse_qa_output(raw.qa, coordinator.questions)
    summary_points = parse_summary_output(raw.summary)
    finished_at = utc_now()
    markdown = build_learning_notes(...)
except LLMNotConfiguredError:
    _mark_failed(generation_id, "GROQ_API_KEY is not configured on the server."); return
except CrewExecutionError as error:
    _mark_failed(generation_id, f"The AI agents could not finish: {error}"); return
except OutputValidationError as error:
    _mark_failed(generation_id, f"The agents' output did not pass validation: {error} Please try again."); return
except Exception:
    logger.exception(...)
    _mark_failed(generation_id, "An unexpected server error occurred. Please try again."); return

with database.SessionLocal() as db:
    generation = db.get(Generation, generation_id)
    generation.status = GenerationStatus.COMPLETED.value
    ... save every result field ...
    db.commit()
```

Execution order:

1. Open a **short** session, mark `processing`, close it. (No session is held open during the slow AI calls.)
2. Run the crew. The `lambda` is a tiny inline function: each time a task finishes, `_set_completed_steps` opens its own session and saves the step number.
3. Validate each output in order. The first problem raises an exception.
4. Specific `except` blocks turn each failure type into a clear message. The final `except Exception` catches anything else.
5. Only if everything passed, open a new session and save all results with `completed`.

---

## 9. `backend/app/api/routes/system.py`

```python
@router.get("/", summary="API welcome information")
def home(settings: Settings = Depends(get_settings)) -> dict:
    return {"name": settings.app_name, "version": ..., "message": "...",
            "frontend": "/app/" if settings.serve_frontend else None,
            "docs": "/docs" if settings.enable_api_docs else None, "health": "/health"}

@router.get("/health", response_model=HealthResponse, summary="Backend health check")
def health(db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> HealthResponse:
    try:
        db.execute(text("SELECT 1"))
        database_status = "ok"
    except Exception:
        database_status = "unavailable"
    return HealthResponse(status="ok" if database_status == "ok" else "degraded",
                          database=database_status, llm_configured=settings.llm_configured,
                          model=settings.llm_model, version=settings.app_version)
```

`SELECT 1` is the cheapest possible query: if it works, the database is reachable. `/health` reports **whether** a key exists, never the key.

---

## 10. `backend/app/api/routes/generations.py`

```python
router = APIRouter(prefix="/api/generations", tags=["generations"])
```

All paths below are relative to `/api/generations`; `tags` groups them in `/docs`.

- **`to_detail(generation)`** builds a `GenerationDetail` from a database row, including `Progress(completed_steps=...)` and `warnings or []`.
- **`get_generation_or_404(db, id)`** raises `HTTPException(404, "Generation not found.")` if the row is missing. Raising `HTTPException` stops the route and FastAPI sends that error.

### `submit_generation` — `POST /api/generations` (202)

```python
def submit_generation(payload: GenerationCreate, background_tasks: BackgroundTasks,
                      db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    if not settings.llm_configured:
        raise HTTPException(status_code=503, detail="The server has no GROQ_API_KEY configured, ...")
    if generation_service.count_active_generations(db) >= settings.max_active_generations:
        raise HTTPException(status_code=429, detail="Other generations are still running. ...")
    generation = generation_service.create_generation(db, payload.topic)
    background_tasks.add_task(generation_service.run_generation, generation.id)
    return to_detail(generation)
```

- `payload` is already validated when the function starts.
- `BackgroundTasks` is provided by FastAPI. `add_task` only *schedules*; the job starts after the response is sent.
- Status **202 Accepted** means "received, still working on it".

### `list_history` — `GET /api/generations`

`limit: int = Query(20, ge=1, le=100)` reads `?limit=` from the URL with a default of 20 and bounds 1–100. Rows are converted with `GenerationSummary.model_validate(row)`.

### `read_generation` — `GET /api/generations/{generation_id}`

One line: `return to_detail(get_generation_or_404(db, generation_id))`.

### `download_markdown` — `GET /api/generations/{generation_id}/download`

```python
generation = get_generation_or_404(db, generation_id)
if generation.status != GenerationStatus.COMPLETED.value or not generation.markdown:
    raise HTTPException(status_code=409, detail="This generation has not completed, ...")
filename = make_download_filename(generation.topic)
return Response(content=generation.markdown, media_type="text/markdown; charset=utf-8",
                headers={"Content-Disposition": f'attachment; filename="{filename}"'})
```

**409 Conflict** means "the request is valid, but the resource is not in the right state".

---

## 11. `backend/app/main.py` — putting it together

```python
@asynccontextmanager
async def lifespan(_app: FastAPI):
    database.init_db()
    with database.SessionLocal() as db:
        interrupted = fail_interrupted_generations(db)
    ...
    if not get_settings().llm_configured:
        logger.warning("GROQ_API_KEY is not set: the API will run, but generations are disabled.")
    yield
```

Code before `yield` runs once at **startup**: create tables, clean up interrupted jobs, warn about a missing key. (Code after `yield` would run at shutdown; there is none.)

`create_app()` then:

1. Creates `FastAPI(...)`, turning `/docs`, `/redoc` and `/openapi.json` off when `enable_api_docs` is false.
2. Adds **CORS** for the configured origins, only `GET`/`POST` and the `Content-Type` header, without cookies.
3. Adds the `limit_body_size_and_add_headers` middleware:

```python
@app.middleware("http")
async def limit_body_size_and_add_headers(request: Request, call_next):
    content_length = request.headers.get("content-length")
    if content_length is not None:
        ... 400 if not a number, 413 if > MAX_REQUEST_BODY_BYTES ...
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("X-Frame-Options", "DENY")
    if request.url.path.startswith("/app"):
        response.headers.setdefault("Content-Security-Policy", FRONTEND_CSP)
    return response
```

   **Middleware** runs around every request. `call_next(request)` passes the request on to the route; code after it edits the response. The CSP is only added for `/app` because `/docs` loads Swagger UI from a CDN.

4. Registers two **exception handlers**: `handle_validation_error` (422 with `detail` + `errors`, built by `_friendly_validation_errors`, which also replaces Pydantic's JSON error with "The request body is not valid JSON.") and `handle_unexpected_error` (500, generic message, full details logged).
5. Includes the two routers and mounts the frontend:

```python
app.mount("/app", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
```

`html=True` serves `index.html` for `/app/`.

The last line, `app = create_app()`, is what `uvicorn app.main:app` looks for: *module* `app.main`, *variable* `app`.

---

## 12. The tests (`backend/tests/`)

| File | Tests |
|---|---|
| `conftest.py` | Fake key + temp DB URL set before import; `block_live_llm_calls` (automatic, every test); `db_url`, `db_session`, `client` fixtures. |
| `fakes.py` | `COORDINATOR_TEXT`, `EXPLANATION_TEXT`, `QA_TEXT`, `SUMMARY_TEXT`, `good_crew_output()`, `fake_successful_crew()`. |
| `test_api.py` | All endpoints through `TestClient` (22 test functions; some run with many parameter sets). |
| `test_database.py` | DB helpers, restart clean-up, and `run_generation` saving results. |
| `test_output_parser.py` | Every parser, including invalid outputs. |
| `test_markdown_builder.py` | Section order, Q&A/summary formatting, safe file names. |
| `test_crewai_service.py` | Four roles, required model, prompt placeholders, prompt rules, no-key path, key redaction, friendly errors. |
| `test_schemas.py` | `GenerationCreate` rules and UTC timestamps. |

How mocking works, step by step:

```python
@pytest.fixture(autouse=True)
def block_live_llm_calls(monkeypatch):
    from app.services import generation_service
    monkeypatch.setattr(generation_service, "run_learning_crew", _live_crew_guard)
    yield
```

`monkeypatch.setattr` temporarily replaces `generation_service.run_learning_crew` for one test and restores it afterwards. Because `generation_service` calls `run_learning_crew` by that module-level name, the replacement is what actually runs. A test that wants success replaces it again:

```python
@pytest.fixture
def fake_crew(monkeypatch):
    monkeypatch.setattr(generation_service, "run_learning_crew", fakes.fake_successful_crew)
```

`test_api.py` and `test_database.py` start with `pytest.importorskip("fastapi")` / `("sqlalchemy")`, so in an environment without those packages they are reported as **skipped** rather than crashing; after `pip install -r backend/requirements.txt` they run.

---

## 13. `frontend/js/config.js`

```javascript
const PRODUCTION_API_URL = "";
const LOCAL_API_URL = "http://127.0.0.1:8000";

function resolveApiBaseUrl() {
  const servedByBackend = window.location.pathname.startsWith("/app");
  if (servedByBackend) return "";
  if (PRODUCTION_API_URL) return PRODUCTION_API_URL.replace(/\/$/, "");
  return LOCAL_API_URL;
}

window.APP_CONFIG = Object.freeze({ API_BASE_URL: resolveApiBaseUrl(), TOPIC_MIN_LENGTH: 2,
  TOPIC_MAX_LENGTH: 120, POLL_INTERVAL_MS: 2000, HISTORY_LIMIT: 12 });
```

The whole file is wrapped in `(function () { ... })();`, an **IIFE** (immediately invoked function expression). Variables inside stay private; only `window.APP_CONFIG` is shared. `Object.freeze` makes it read-only.

---

## 14. `frontend/js/api.js`

```javascript
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
  ...
  if (!response.ok) {
    const detail = body && typeof body.detail === "string" ? body.detail : "Request failed.";
    throw new ApiError(detail, response.status);
  }
  return body;
}
```

- `AbortController` cancels a request that takes longer than 15 seconds.
- `fetch` only throws for network failures; HTTP errors (404, 422…) are checked with `response.ok`.
- Every backend error has a `detail` string, which becomes the error message the page shows.

`window.Api` exposes `health`, `createGeneration`, `getGeneration`, `listGenerations`, `downloadUrl`.

---

## 15. `frontend/js/markdown.js`

- `escapeHtml(text)`: replaces `& < > " '` with HTML entities.
- `renderInline(escaped)`: on already-escaped text, temporarily hides `` `code` `` spans (so nothing inside is formatted), converts `[label](https://…)` links, `**bold**` and `*italic*`, then puts the code spans back. Underscore emphasis is intentionally unsupported so `__init__` and `snake_case` stay intact.
- `renderList(lines, start)`: handles bullet/numbered lists, nested lists (deeper indentation) and wrapped lines; returns the HTML and the next line index.
- `render(markdown, options)`: goes line by line and recognises code fences, blank lines, headings (never above `<h3>`; `options.headingOffset` pushes levels down for the full-notes view), horizontal rules, blockquotes, tables, lists and paragraphs.
- `sanitizeNode(node)`: removes anything not in `ALLOWED_TAGS`, strips attributes not in `ALLOWED_ATTRIBUTES`, forces links to `http(s)` with `rel="noopener noreferrer"`.
- `toFragment(markdown, options)`: renders into an inert `<template>`, sanitizes it, returns a `DocumentFragment` ready to insert.

The last lines export the functions to Node (`module.exports`) for the tests, or to the browser as `window.SafeMarkdown`.

---

## 16. `frontend/js/app.js`

`state` holds what the page remembers: `currentId`, `current` (latest data), timers, poll failures and the section observer.

| Function | Role |
|---|---|
| `formatDate`, `formatDuration`, `formatTook`, `secondsBetween` | Display helpers. |
| `el(tag, className, text)` | Creates an element and sets its text safely. |
| `showToast(message, isError)` | Small notification at the bottom. |
| `copyText(text)` | Clipboard API with an old-browser fallback. |
| `showView(name)` | Shows one of `home`, `progress`, `result`. |
| `stopTimers()`, `goHome()` | Stop polling/clock; return home and refresh history. |
| `openGenerationFromHash()` | Reads `#/generation/<id>` and opens it (ignores it if already open). |
| `checkHealth()` | Calls `/health`; sets the top-right indicator and the banner. |
| `validateTopic(raw)` | Same rules as the backend, for instant feedback. |
| `submitTopic(rawTopic)` | Validates, disables the button, calls the API, sets the hash. |
| `openGeneration(id)` | Shows the progress view at once, then loads the generation. |
| `handleGeneration(g)` | Routes to `renderResult`, the failure view, or `renderProgress` + `schedulePoll`. |
| `schedulePoll()`, `pollOnce()` | Every 2 s; after errors waits longer; gives up after 5 consecutive failures with an explanation. |
| `renderProgress(g)` | Marks each station *done* / *active* / *waiting* from `progress.completed_steps` only. |
| `showFailure(g, message)` | Error box, "Try this topic again", marks the step that was running (only if the job had started). |
| `renderResult(g)` | Fills every section; Markdown only via `SafeMarkdown.toFragment`. |
| `setNotesView(view)` | Switches between formatted and raw Markdown. |
| `watchSections()` | `IntersectionObserver` highlights the section-nav link for the section on screen. |
| `textForCopy(kind)` | Builds the text for each Copy button. |
| `loadHistory()` | Fetches and draws the history rows. |
| `bindEvents()`, `init()` | Attach every listener once the page has loaded (`DOMContentLoaded`). |

Event handling uses **delegation**: one click listener on `document` checks `event.target.closest("[data-action]")`, `"[data-copy]"` or `".toc a"`. This avoids attaching a listener to every button, and is why the HTML uses `data-*` attributes rather than `onclick` (which the CSP would block anyway).

---

## 17. `frontend/index.html` and `css/styles.css`

- The HTML starts with an SVG **sprite**: icons defined once as `<symbol>` and reused with `<use href="#i-copy">`.
- `<main>` holds the three views; only one is visible. `hidden` attributes are toggled by `showView`.
- ARIA attributes help screen readers: `aria-live="polite"` announces status changes; `role="alert"` for errors; `aria-pressed` on the notes toggle; `aria-current` on the active section link.
- Scripts load in order at the end of `<body>`: `config.js` → `markdown.js` → `api.js` → `app.js` (each relies on the previous ones).

The CSS is organised in numbered parts (tokens, base, layout, controls, home, progress, result, responsive). Colours, fonts and radii are **CSS custom properties** (`--teal`, `--font-read`, …) defined once in `:root`. Two media queries adapt the layout: below 1024 px the hero stacks and the section nav becomes a horizontal tab strip; below 640 px the top navigation hides, the form stacks and history rows wrap. `prefers-reduced-motion` turns off animation for people who request it.
