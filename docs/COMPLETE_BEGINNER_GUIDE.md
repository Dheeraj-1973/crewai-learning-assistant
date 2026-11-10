# Complete Beginner Guide

This guide teaches the whole project from zero. Read it once from top to bottom, then use [CODE_EXPLANATION.md](CODE_EXPLANATION.md) to go through the code line by line.

Every new word is explained the first time it appears.

---

## Part 1 — Words you need first

| Word | Meaning in this project |
|---|---|
| **Frontend** | The part that runs in your browser: `index.html`, `styles.css` and the JavaScript files. |
| **Backend** | The Python program on the server. It stores data and runs the AI agents. |
| **Server** | A program that waits for requests and sends back responses. Here, Uvicorn runs our FastAPI app. |
| **HTTP** | The language browsers and servers use to talk. A request has a *method* (GET, POST…), a *path* (`/health`) and sometimes a *body*. |
| **API** | Application Programming Interface: a set of URLs a program can call to get something done. Our API is the `/api/generations` family of URLs. |
| **REST** | A style of API design where URLs name *things* (here, "generations") and HTTP methods say what to do with them (GET = read, POST = create). |
| **Endpoint** | One URL + method pair, e.g. `POST /api/generations`. |
| **JSON** | A text format for data: `{"topic": "FastAPI"}`. Python dicts and JavaScript objects map onto it naturally. |
| **Status code** | A number in every HTTP response: 200 OK, 202 Accepted, 404 Not Found, 422 invalid input, 500 server error… |
| **LLM** | Large Language Model, the AI that writes text. Ours is `openai/gpt-oss-20b`, hosted by Groq. |
| **Agent** | In CrewAI, an LLM given a role, a goal and a backstory, so it behaves like a specialist. |
| **Task** | A piece of work given to one agent, with instructions and an expected output format. |
| **Crew** | A team of agents and their tasks, plus rules for the order they run in. |
| **ORM** | Object-Relational Mapper. SQLAlchemy lets us use Python classes instead of writing SQL by hand. |
| **Session** | A SQLAlchemy object representing one conversation with the database. |
| **Validation** | Checking that data has the right shape before using it. Pydantic does this for requests. |
| **Background task** | Work that continues after the HTTP response has already been sent. |
| **Polling** | The browser asking "are you done yet?" every few seconds. |
| **Environment variable** | A named value set outside the code (here, in `.env`) such as `GROQ_API_KEY`. |

---

## Part 2 — The folders, and why each exists

```text
crewai-learning-assistant/
├── backend/            Python server code
│   ├── app/            the application package
│   │   ├── main.py     where the app is created
│   │   ├── api/routes/ the URLs (endpoints)
│   │   ├── core/       settings
│   │   ├── database/   database connection + table
│   │   ├── schemas/    shapes of request/response data
│   │   └── services/   the real work (agents, validation, Markdown, jobs)
│   ├── tests/          automated tests
│   ├── pytest.ini      test settings
│   └── requirements.txt  Python packages to install
├── frontend/           website files
├── docs/               these guides
├── .env.example        template for your secret settings
└── .gitignore          files Git must never commit
```

Why split the backend into so many folders? Each folder answers one question:

- *"Which URL does what?"* → `api/routes/`
- *"What does valid data look like?"* → `schemas/`
- *"How is the work actually done?"* → `services/`
- *"How do we store things?"* → `database/`
- *"What can be configured?"* → `core/`

When something breaks, you know where to look. This is called **separation of concerns**.

Each folder inside `app` has an empty `__init__.py`. That file tells Python "this folder is a package", which allows imports like `from app.services import generation_service`.

---

## Part 3 — Every important file in one sentence

### Backend

| File | Job |
|---|---|
| `app/main.py` | Creates the FastAPI app, runs startup code, adds middleware and error handlers, connects the routes, and serves the frontend at `/app`. |
| `app/core/config.py` | Reads settings (API key, database URL, limits) from the environment into a `Settings` object. |
| `app/database/database.py` | Creates the SQLite connection (`engine`), the session factory (`SessionLocal`), `init_db()` and `get_db()`. |
| `app/database/models.py` | Defines the `generations` table as the `Generation` class, and the four statuses. |
| `app/schemas/generation.py` | Pydantic models such as `GenerationCreate` (input) and `GenerationDetail` (output). |
| `app/api/routes/system.py` | `GET /` and `GET /health`. |
| `app/api/routes/generations.py` | The four `/api/generations` endpoints. |
| `app/services/crewai_service.py` | Defines the four agents and four tasks, builds the crew, runs it. |
| `app/services/output_parser.py` | Cleans and checks each agent's text; raises an error if the format is wrong. |
| `app/services/markdown_builder.py` | Joins the validated pieces into one Markdown document; makes a safe file name. |
| `app/services/generation_service.py` | Database helper functions plus `run_generation()`, the background job. |

### Frontend

| File | Job |
|---|---|
| `index.html` | The page structure: top bar, home view, progress view, result view. |
| `css/styles.css` | All visual styling, including the mobile layout. |
| `js/config.js` | Works out where the backend is and holds a few constants. |
| `js/api.js` | One function per backend endpoint, with error handling. |
| `js/markdown.js` | Turns Markdown into safe HTML. |
| `js/app.js` | Everything interactive: form, polling, rendering results, history, copy. |

---

## Part 4 — How the files talk to each other

Follow one click on **Generate notes**:

1. `app.js` → `submitTopic()` validates the text, then calls `Api.createGeneration(topic)` in `api.js`.
2. `api.js` sends `POST /api/generations` with body `{"topic": "FastAPI"}`.
3. Uvicorn hands the request to FastAPI (`main.py`). Middleware checks the body size and later adds security headers.
4. FastAPI sees the path and calls `submit_generation()` in `routes/generations.py`.
5. Before calling it, FastAPI turns the JSON into a `GenerationCreate` object (`schemas/generation.py`). If that fails, the function is never called and a 422 error goes back.
6. `submit_generation()` asks `generation_service.count_active_generations()` and then `create_generation()`, which use the `Generation` model (`models.py`) and a session from `get_db()` (`database.py`).
7. It schedules `generation_service.run_generation(id)` as a background task and returns the new row, converted by `to_detail()` into a `GenerationDetail`.
8. After the response is sent, `run_generation()` calls `run_learning_crew()` in `crewai_service.py`, which calls Groq four times (once per agent).
9. The raw texts go through `output_parser.py`, then `markdown_builder.py`, and the results are saved.
10. Meanwhile `app.js` polls `GET /api/generations/{id}` and finally calls `renderResult()`, which uses `markdown.js` to display everything safely.

---

## Part 5 — How FastAPI receives a request

FastAPI looks at **decorators** to know which function handles which URL. A decorator is the `@something` line above a function:

```python
@router.get("/{generation_id}", response_model=GenerationDetail)
def read_generation(generation_id: str, db: Session = Depends(get_db)) -> GenerationDetail:
    return to_detail(get_generation_or_404(db, generation_id))
```

FastAPI reads the function's parameters:

- `generation_id: str` matches `{generation_id}` in the path, so FastAPI fills it from the URL.
- `db: Session = Depends(get_db)` is a **dependency**. FastAPI calls `get_db()`, passes the session in, and closes it after the response.
- A parameter whose type is a Pydantic model (like `payload: GenerationCreate`) is read from the JSON **body**.
- `response_model=GenerationDetail` tells FastAPI to convert the return value to JSON in that exact shape, and to document it at `/docs`.

The routes are grouped with `APIRouter(prefix="/api/generations")` and attached to the app in `main.py` with `app.include_router(...)`.

---

## Part 6 — How Pydantic validates

```python
class GenerationCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    topic: str = Field(..., min_length=2, max_length=120)
```

When a request arrives, Pydantic checks, in order:

1. Is the body a JSON object? (Not a list, not broken JSON.)
2. Is `topic` present? (`...` means required.)
3. Is it a string? (`123` is rejected; Pydantic v2 does not turn numbers into strings.)
4. Our `reject_control_characters` validator: no newlines or tabs.
5. Strip spaces from both ends (`str_strip_whitespace`).
6. Length between 2 and 120 *after* stripping, so `"   "` fails.
7. Our `collapse_spaces` validator: `"Python    decorators"` → `"Python decorators"`.
8. No other fields allowed (`extra="forbid"`).

Any failure raises a `RequestValidationError`. `main.py` catches it and returns a friendly 422:

```json
{"detail": "topic: String should have at least 2 characters",
 "errors": [{"field": "topic", "message": "String should have at least 2 characters"}]}
```

---

## Part 7 — How CrewAI executes the four agents

Think of a relay race. Each runner (agent) runs one leg (task) and passes the baton (its output) to the next.

1. `build_llm()` creates one `LLM("groq/openai/gpt-oss-20b", ...)`. The `groq/` prefix tells CrewAI to call Groq through LiteLLM, using `GROQ_API_KEY`.
2. `build_crew()` creates four `Agent` objects from `AGENT_SPECS` (role, goal, backstory).
3. It creates four `Task` objects. Each has a `description` (the instructions), an `expected_output` (the exact format), an `agent`, and sometimes `context` (earlier tasks whose output this agent should read).
4. `Crew(..., process=Process.sequential)` runs the tasks in order.
5. `crew.kickoff(inputs={"topic": "FastAPI"})` replaces every `{topic}` in the instructions with the real topic, then runs.
6. After each task, CrewAI calls our `after_each_task` function (the `task_callback`). We count 1, 2, 3, 4 and save that number, so the browser can show real progress.
7. `kickoff` returns a `CrewOutput`. Its `tasks_output` list holds each task's result; `.raw` is the plain text. We return the four texts as a `CrewRawOutput`.

**Why validate after?** LLMs sometimes ignore instructions. `output_parser.py` checks the parts that matter (three questions, three answers, five bullets, a complete explanation) and refuses to save broken results.

**Why a marker at the end of the explanation?** A model can stop early when it hits its token limit. If the text simply ends, we cannot tell. Asking it to write `END_OF_EXPLANATION` last gives a reliable signal: no marker, probably cut off. `gpt-oss-20b` is a *reasoning* model, meaning it also produces hidden "thinking" tokens that count against `max_tokens`; that is why the limit is a generous 8192 and reasoning effort is set to `low` by default.

---

## Part 8 — How SQLite saves results

SQLite is a database stored in a single file (`backend/data/learning_assistant.db`). No separate database program is needed.

SQLAlchemy maps the `Generation` class to the `generations` table:

```python
class Generation(Base):
    __tablename__ = "generations"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_generation_id)
    topic: Mapped[str] = mapped_column(String(120), nullable=False)
    ...
```

Saving a row:

```python
generation = Generation(topic=topic, status="pending")
db.add(generation)    # "please insert this"
db.commit()           # actually write it to the file
db.refresh(generation)  # reload it, so defaults like id/created_at are filled in
```

Reading rows:

```python
db.get(Generation, generation_id)                                   # by primary key
select(Generation).order_by(Generation.created_at.desc()).limit(20) # newest 20
```

The background job opens its **own** session with `database.SessionLocal()`, because the request's session is closed once the response is sent.

---

## Part 9 — How JavaScript calls the backend

`fetch()` is the browser's built-in function for HTTP requests. `api.js` wraps it in `request()`:

```javascript
response = await fetch(BASE + path, options);   // send the request
body = await response.json();                   // read the JSON
if (!response.ok) throw new ApiError(body.detail, response.status);
```

`async`/`await` lets the code wait for the network without freezing the page.

After submitting, `app.js` **polls**: `schedulePoll()` sets a 2-second timer, `pollOnce()` calls `Api.getGeneration(id)`, and `handleGeneration()` decides what to show. Polling stops when the status is `completed` or `failed`.

---

## Part 10 — How the result appears in the browser

`index.html` contains three `<section>`s: `view-home`, `view-progress` and `view-result`. `showView(name)` hides two and shows one.

`renderResult(generation)` fills in the result view:

- Plain text (topic, questions) is set with `textContent`, which can never create HTML tags.
- Markdown (explanation, answers, notes) goes through `SafeMarkdown.toFragment()`.

The URL becomes `.../app/#/generation/<id>`. The part after `#` is the **hash**. Changing it does not reload the page, but `app.js` listens for the change and opens that generation. Because the hash stays in the address bar, refreshing reopens the same notes.

### Why the Markdown renderer is "safe"

AI output is untrusted. If the text contained `<script>`, inserting it as HTML could run code. `markdown.js` therefore:

1. **Escapes everything first** (`<` becomes `&lt;`), then adds only its own tags (`<p>`, `<h3>`, `<code>`…).
2. **Sanitizes** the result inside an inert `<template>`, removing any tag or attribute not on an allowlist, and only keeping `http(s)` links.

The server also sends a **Content-Security-Policy** header for `/app` pages, telling the browser to run only scripts from our own files.

---

## Part 11 — How Markdown is generated and downloaded

`build_learning_notes()` in `markdown_builder.py` assembles:

```text
# FastAPI: Learning Notes
> Generated on ... (model: groq/openai/gpt-oss-20b) ...
## 1. Learning Plan
## 2. Topic Explanation
## 3. Questions and Answers   (### Q1. ..., ### Q2. ..., ### Q3. ...)
## 4. Five-Point Summary      (1. ... 5.)
```

It is saved in the `markdown` column. The download endpoint returns it with two headers:

- `Content-Type: text/markdown; charset=utf-8`
- `Content-Disposition: attachment; filename="fastapi-learning-notes.md"` (this makes the browser save it as a file).

`make_download_filename()` keeps only lowercase letters, digits and hyphens, so a topic can never inject anything into that header.

---

## Part 12 — How errors are handled

There are three layers:

1. **Before work starts** (in the request): bad input → 422; too large → 413; no key → 503; too busy → 429; unknown ID → 404; download before completion → 409.
2. **During the background job**: `run_generation()` catches each kind of failure and saves `status="failed"` with a readable `error_message`. It never stores half-made or invented results.
3. **Anything unexpected**: a catch-all handler returns `{"detail": "Internal server error."}` and logs the details on the server only, so stack traces never reach users.

In the browser, `ApiError` carries a message that is safe to show, and the page shows it in the form, the banner, or the red error box.

---

## Part 13 — How the tests work

Run `pytest` inside `backend/`. Pytest finds files named `test_*.py` and runs functions named `test_*`.

- **`conftest.py`** runs first. It sets a fake API key and a temporary database URL, and its `block_live_llm_calls` fixture (a *fixture* is setup code pytest runs for tests) replaces `run_learning_crew` with a function that fails loudly. So even a mistake cannot call Groq.
- **`fakes.py`** contains realistic agent outputs. Tests that need a successful run swap in `fake_successful_crew`.
- **`TestClient`** sends requests to the app in memory, no real server needed. Background tasks finish before `client.post()` returns, so a test can submit and immediately check the final status.
- Each API test gets a brand-new SQLite file (`tmp_path`), so tests never affect each other or your real data.

What is tested: every endpoint; every kind of invalid input; success, failure and invalid-output paths; progress updates; the 429/503 guards; download headers; database helpers; restart clean-up; the output parser; the Markdown builder; prompts; key redaction; and that the frontend files are served with security headers. The Markdown renderer has its own Node.js tests.

---

## Part 14 — How deployment works (in short)

"Deploying" means running the server on a computer on the internet instead of your laptop. The simplest route for this project is **one service** that runs Uvicorn and also serves the frontend at `/app`, so there is no separate frontend hosting and no CORS to configure. You set `GROQ_API_KEY` in the hosting dashboard (never in Git).

Two things change compared with your laptop:

1. Free hosting often has a temporary disk, so the SQLite file can be wiped on restart. History is then lost (generations themselves still work).
2. Anyone can reach your site, so they can spend your Groq quota. Add rate limits and ideally a login first.

Full steps: [SETUP_AND_EXECUTION.md → Deploying online](SETUP_AND_EXECUTION.md#deploying-online).
