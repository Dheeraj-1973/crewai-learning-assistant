# Architecture

This document explains how the parts of the application fit together. Every name here (files, functions, endpoints) exists in the code.

## 1. The big picture

There are three running pieces:

1. **The browser** shows `frontend/index.html` and runs the JavaScript files.
2. **The FastAPI server** (`backend/app`) receives HTTP requests, stores data in SQLite, and runs the CrewAI agents in the background.
3. **The Groq API** (on the internet) runs the language model `openai/gpt-oss-20b` whenever an agent needs to "think".

The browser never talks to Groq directly, and never sees the API key. Only the server does.

## 2. Frontend ↔ backend communication

The frontend and backend talk using **HTTP requests with JSON bodies**.

| Browser function (`js/api.js`) | HTTP request | Backend function |
|---|---|---|
| `Api.health()` | `GET /health` | `system.health` |
| `Api.createGeneration(topic)` | `POST /api/generations` | `generations.submit_generation` |
| `Api.getGeneration(id)` | `GET /api/generations/{id}` | `generations.read_generation` |
| `Api.listGenerations(limit)` | `GET /api/generations?limit=…` | `generations.list_history` |
| `Api.downloadUrl(id)` (a link) | `GET /api/generations/{id}/download` | `generations.download_markdown` |

Where is the API? `js/config.js` decides:

- If the page was loaded from `/app/...`, the backend served it, so requests go to the **same origin** (`API_BASE_URL = ""`). No CORS is involved.
- Otherwise (e.g. Live Server on port 5500) requests go to `http://127.0.0.1:8000`, and the backend's **CORS** settings must list that page's origin (they do by default).

## 3. FastAPI architecture

```mermaid
flowchart TB
    REQ[HTTP request] --> CORS[CORSMiddleware]
    CORS --> MW[limit_body_size_and_add_headers<br/>413 if body > 4 KB<br/>adds security headers]
    MW --> ROUTER{Which path?}
    ROUTER -- "/ , /health" --> SYS[routes/system.py]
    ROUTER -- "/api/generations..." --> GEN[routes/generations.py]
    ROUTER -- "/app/..." --> STATIC[StaticFiles: frontend folder]
    GEN -- "Depends(get_db)" --> SESSION[database.get_db<br/>one session per request]
    GEN -- "Depends(get_settings)" --> SETTINGS[core/config.get_settings]
    GEN -- "payload: GenerationCreate" --> PYD[Pydantic validation<br/>422 on failure]
    GEN --> SERVICE[services/generation_service.py]
```

Layers and their single responsibilities:

| Layer | Folder | Responsibility |
|---|---|---|
| Entry point | `app/main.py` | Builds the app: startup code, middleware, error handlers, routes, static files. |
| Routes | `app/api/routes/` | Translate HTTP into function calls and back. No business logic. |
| Schemas | `app/schemas/` | Pydantic models: what valid input and output look like. |
| Services | `app/services/` | The actual work: database helpers, running the crew, validating output, building Markdown. |
| Database | `app/database/` | Connection, sessions, and the table definition. |
| Config | `app/core/` | All settings in one immutable `Settings` object. |

## 4. CrewAI architecture

`services/crewai_service.py` builds one `Crew` containing four `Agent`s and four `Task`s, all sharing one `LLM` object.

```mermaid
flowchart LR
    LLM[LLM<br/>groq/openai/gpt-oss-20b<br/>temperature 0.4, max_tokens 8192]
    A1[Agent: Learning Coordinator] --- LLM
    A2[Agent: Beginner-Friendly Content Teacher] --- LLM
    A3[Agent: Grounded Question Answering Specialist] --- LLM
    A4[Agent: Beginner-Friendly Summary Writer] --- LLM

    T1[plan_task] --> A1
    T2[explain_task<br/>context: plan_task] --> A2
    T3[qa_task<br/>context: plan_task, explain_task] --> A3
    T4[summary_task<br/>context: explain_task] --> A4
```

Key settings:

- `process=Process.sequential`: tasks run one after another, in list order.
- `context=[...]`: CrewAI pastes the output of the listed tasks into the next agent's prompt. This is how the teacher sees the plan and the Q&A specialist sees the explanation.
- `allow_delegation=False`: agents cannot hand work to each other, so each does exactly its own job.
- `max_iter=3`: no tools are used, so an agent normally finishes in one model call; three is a safety limit.
- `task_callback`: called by CrewAI after each task finishes. We use it for progress.

## 5. The four-agent workflow

```mermaid
sequenceDiagram
    participant W as run_generation
    participant C as Coordinator
    participant T as Content Teacher
    participant Q as Q&A Specialist
    participant S as Summary Writer
    participant DB as SQLite

    W->>C: plan the lesson for "{topic}"
    C-->>W: Teaching Plan + Key Concepts + Q1..Q3
    W->>DB: completed_steps = 1
    W->>T: explain, following the plan (no Q&A, no summary)
    T-->>W: Markdown explanation + END_OF_EXPLANATION
    W->>DB: completed_steps = 2
    W->>Q: answer Q1..Q3 using ONLY the explanation
    Q-->>W: Q1/A1, Q2/A2, Q3/A3
    W->>DB: completed_steps = 3
    W->>S: five bullet points from the explanation
    S-->>W: exactly five "- " lines
    W->>DB: completed_steps = 4
    W->>W: validate all four outputs (output_parser)
    W->>DB: status = completed, save results + Markdown
```

How the agents avoid repeating each other:

| Agent | Must do | Must not do |
|---|---|---|
| Coordinator | Plan + exactly three different questions | Explain the topic or answer the questions |
| Teacher | Full explanation with a worked example, `###` headings, end marker | Write questions, Q&A, summaries or recaps |
| Q&A Specialist | Answer the Coordinator's three questions from the explanation only | Use outside knowledge; guess when the explanation is silent |
| Summary Writer | Exactly five one-sentence bullets | Add titles, intros or new facts |

The prompts state these rules, and `output_parser.py` enforces the checkable ones in code.

## 6. Database architecture

One table is enough because there is one kind of thing to store: a generation.

```mermaid
erDiagram
    GENERATIONS {
        string id PK "32 hex chars (uuid4)"
        string topic "max 120"
        string status "pending | processing | completed | failed (indexed)"
        int completed_steps "0-4"
        text teaching_plan "nullable"
        text explanation "nullable"
        json qa_pairs "list of question/answer, nullable"
        json summary_points "list of 5 strings, nullable"
        text markdown "nullable"
        json warnings "list of strings, nullable"
        text error_message "nullable"
        datetime created_at "indexed"
        datetime started_at "nullable"
        datetime completed_at "nullable"
    }
```

- Tables are created automatically at startup by `init_db()` (`Base.metadata.create_all`).
- The database file is `backend/data/learning_assistant.db` by default.
- Q&A pairs and summary points are stored as JSON columns rather than separate tables, because they are always read together with their generation and never queried on their own.

## 7. Request–response flow: submitting a topic

```mermaid
sequenceDiagram
    participant B as Browser (app.js)
    participant F as FastAPI
    participant P as Pydantic
    participant G as generation_service
    participant DB as SQLite

    B->>F: POST /api/generations {"topic": " FastAPI "}
    F->>P: validate body as GenerationCreate
    P-->>F: topic = "FastAPI" (or 422 error)
    F->>F: GROQ key set? (else 503)
    F->>G: count_active_generations()
    G->>DB: SELECT count(*) WHERE status IN (pending, processing)
    F->>F: below MAX_ACTIVE_GENERATIONS? (else 429)
    F->>G: create_generation("FastAPI")
    G->>DB: INSERT row (status = pending)
    F->>F: background_tasks.add_task(run_generation, id)
    F-->>B: 202 Accepted {id, status: "pending", progress: 0/4}
    Note over F: response sent; now run_generation starts in a worker thread
    B->>B: location.hash = #/generation/{id}
    loop every 2 seconds
        B->>F: GET /api/generations/{id}
        F-->>B: status + progress (+ results when completed)
    end
```

## 8. Background generation lifecycle

```mermaid
stateDiagram-v2
    [*] --> pending: create_generation()
    pending --> processing: run_generation() starts
    processing --> processing: task_callback (completed_steps 1..4)
    processing --> completed: all outputs valid
    processing --> failed: CrewExecutionError / OutputValidationError / unexpected error
    pending --> failed: server restarted (fail_interrupted_generations)
    processing --> failed: server restarted (fail_interrupted_generations)
    completed --> [*]
    failed --> [*]
```

**Why FastAPI `BackgroundTasks`?** It needs no extra software. After the response is sent, FastAPI runs `run_generation` in a worker thread (because it is a normal `def` function), so the server can keep answering status requests while the agents work.

**The important limitation.** Background tasks live in the memory of the server process. If you stop the server (Ctrl+C, a crash, a redeploy, or `--reload` restarting after you edit a file) while a job is running, that job disappears. The row would say "processing" forever, so on every startup `lifespan()` calls `fail_interrupted_generations()`, which marks such rows **failed** with the message *"The server restarted before this generation finished…"*. The user can then submit the topic again.

Other consequences of this simple design (all acceptable for a portfolio project):

- Jobs are not retried automatically.
- The concurrency cap (`MAX_ACTIVE_GENERATIONS`) is checked with a count followed by an insert, so two requests arriving at exactly the same moment could both pass. A real queue or a database lock would close that gap.
- Running several server processes would need a shared database and a real job queue (for example Celery with Redis, or a managed queue).

## 9. Error handling map

| What goes wrong | Where it is caught | What the user sees |
|---|---|---|
| Bad JSON, wrong type, empty or too-long topic | Pydantic + `handle_validation_error` | 422 with a field-specific message |
| Body over 4 KB | `limit_body_size_and_add_headers` | 413 |
| No `GROQ_API_KEY` | `submit_generation` | 503 and a banner on the page |
| Too many jobs running | `submit_generation` | 429 "Other generations are still running…" |
| Groq rate limit / bad key / timeout | `run_learning_crew` → `safe_error_message` | Generation **failed** with a friendly reason |
| Agent ignored the format | `output_parser` → `OutputValidationError` | Generation **failed** explaining which agent and why |
| Any other bug | `run_generation` last `except`, or `handle_unexpected_error` | Generic message; details only in the server log |
| Network loss while polling | `pollOnce` in `app.js` | Retries with back-off, then an explanation |
