# Interview Preparation

Everything here describes what the code actually does. If an interviewer asks about something not built (for example, user accounts or streaming), say so plainly and describe how you would add it; the "Limitations" and "Future enhancements" sections give you those answers.

---

## 60-second introduction

> I built a CrewAI Multi-Agent Learning Assistant. You type a technical topic, and a team of four AI agents writes beginner-friendly notes: a Learning Coordinator plans the lesson and writes three questions, a Content Teacher explains the topic with a worked example, a Q&A Specialist answers the questions using only the teacher's explanation, and a Summary Writer condenses it into five points.
>
> The backend is FastAPI with Pydantic validation and SQLite through SQLAlchemy. Because the four LLM calls take a while, the API returns a job ID immediately and runs the crew as a background task, and the frontend polls for status. Progress comes from CrewAI's task callback, so the UI only shows steps the server has confirmed.
>
> I also validate the agents' output in code — exactly three questions, three answers, five bullets — and fail the job with a clear message instead of showing broken results. The frontend is plain HTML, CSS and JavaScript with a safe Markdown renderer, and the test suite mocks CrewAI so it never spends API credits.

## Three-minute explanation

**Problem.** One big "explain X" prompt tends to mix explanation, questions and summary together, repeats itself, and gives you no way to check the structure. I wanted separate, checkable roles.

**Agents.** Four CrewAI agents run sequentially on Groq's `gpt-oss-20b`. Each task has a description and an exact expected output format. Context passing is explicit: the teacher gets the plan; the Q&A agent gets the plan (for the questions) and the explanation (the only allowed source of facts); the summary writer gets only the explanation. Delegation is off so each agent stays in its lane.

**Reliability.** LLMs don't always follow formats, so an `output_parser` module checks each output. The coordinator must produce exactly three distinct questions; the summary must be exactly five bullets; each question needs an answer. The question text always comes from the coordinator, so the Q&A agent can't silently reword it. For truncation, the teacher has to end with an `END_OF_EXPLANATION` marker; if it's missing, the user gets a visible warning. Since gpt-oss is a reasoning model whose hidden reasoning consumes tokens, I set a generous `max_tokens` and low reasoning effort.

**Backend.** FastAPI is layered: routes only translate HTTP; schemas define shapes; services hold the logic; one SQLAlchemy model stores each generation with its status, progress, results, warnings and error. `POST /api/generations` validates the topic, checks a concurrency cap, saves a pending row, schedules the job, and returns 202. The job opens its own sessions, marks processing, runs the crew, validates, builds Markdown, and saves completed or failed.

**Frontend.** Vanilla JS with three views. It polls every two seconds, shows the four-step tracker from the server's step count, and renders results through an escape-first Markdown renderer with an allowlist sanitizer. The URL hash stores the open generation so refresh works. There's copy per section and a Markdown download endpoint.

**Quality.** Pytest with TestClient covers every endpoint, validation edge case, success, failure, invalid output, progress updates, the 429/503 guards and downloads. An autouse fixture replaces the CrewAI call with a guard that fails if anything tries to reach Groq.

**Trade-offs.** Background tasks live in process memory, so a restart kills running jobs; I handle that by marking them failed at startup. For production I'd move to a real queue and add per-user rate limiting and auth.

## Architecture explanation (whiteboard version)

```text
Browser ──POST /api/generations──▶ FastAPI route ──▶ generation_service.create_generation ──▶ SQLite (pending)
   │                                   └─ BackgroundTasks.add_task(run_generation)
   │◀──────── 202 {id, status: pending}
   │
   ├─GET /api/generations/{id} every 2 s──▶ read row ──▶ status + completed_steps
   │
run_generation (worker thread):
   processing ─▶ crewai_service.run_learning_crew
                   Coordinator ▶ Teacher ▶ Q&A ▶ Summary  (task_callback → completed_steps 1..4)
              ─▶ output_parser (validate) ─▶ markdown_builder ─▶ SQLite (completed | failed)
```

## Technical decisions and why

| Decision | Reason |
|---|---|
| Four agents, sequential | Matches how the work depends on itself: plan → teach → check → summarise. |
| `allow_delegation=False` | Keeps each agent to one responsibility; fewer surprise LLM calls. |
| Explicit `context` per task | The Q&A agent must be grounded in the explanation; the summary writer needs nothing else. |
| Validate output in Python | Prompts are requests, not guarantees. Code can enforce counts and formats. |
| Fail instead of padding | Inventing a missing fifth bullet would be dishonest; a clear failure is better. |
| End-of-explanation marker | A cheap, reliable truncation signal that works without provider-specific metadata. |
| `BackgroundTasks` + polling | Simplest non-blocking design; no Redis/Celery needed for one server. |
| Progress via `task_callback` | Real signal from CrewAI; no fake percentages. |
| SQLite + one table | Zero setup; Q&A and summary are JSON columns because they're always read with their generation. |
| `crewai[litellm]` | In CrewAI 1.x LiteLLM is an optional extra, and the `groq/` model prefix routes through it. |
| Lazy CrewAI import | Tests and app startup don't load CrewAI; tests never need a key. |
| Vanilla JS + own Markdown renderer | No build step; every line is explainable; escaping first makes it safe by construction. |
| Backend serves the frontend at `/app` | One command locally, one service when deployed, no CORS needed. |

## Challenges and how I solved them

1. **Agents repeating each other** (teacher writing its own Q&A). → Prompts forbid it, and the parser cuts any Q&A/summary section the teacher adds, with a visible warning.
2. **Truncated explanations.** → End marker + warning, larger `max_tokens`, low reasoning effort, and a target length in the prompt.
3. **Inconsistent formats** (`**Q1:**`, `Question 1.`, bullets with `*` or `•`). → Tolerant regular expressions for harmless variations, strict counts for what matters.
4. **Long-running requests.** → 202 + background task + polling.
5. **Honest progress.** → `task_callback` writes `completed_steps`; the UI marks a step done only from that number.
6. **Jobs lost on restart.** → Startup hook marks leftover pending/processing rows as failed with an explanation.
7. **Testing without spending credits.** → Autouse fixture that blocks the real call; fakes for success, failure and bad-format cases; temp database per test.
8. **Rendering untrusted AI output.** → Escape-first renderer, allowlist sanitizer, `textContent` for plain text, CSP header.

---

## Interview questions and answers

### Project and CrewAI

**1. What does the project do?**
It turns any technical topic into beginner notes using four CrewAI agents: a plan with three questions, an explanation with an example, grounded answers, and a five-point summary, downloadable as Markdown.

**2. Why four agents instead of one prompt?**
Each role has one job and one output format, which makes the result easier to check and reduces repetition. It also lets me ground the Q&A agent strictly in the explanation, which a single prompt can't enforce.

**3. What is an agent in CrewAI?**
An LLM configured with a role, goal and backstory. A task is the work you give it: a description, an expected output, and optionally context from other tasks. A crew is the team plus the process that orders the tasks.

**4. How does information flow between agents?**
Through task `context`. The teacher's task lists the coordinator's task; the Q&A task lists both; the summary task lists only the explanation. CrewAI includes those outputs in the agent's prompt.

**5. Why sequential instead of hierarchical?**
The steps depend on each other in a fixed order, so a manager agent deciding the order would add cost and unpredictability for no benefit.

**6. How do you make sure there are exactly three questions and five bullets?**
The prompts specify the format, and `output_parser.py` counts them. Wrong counts raise `OutputValidationError`, and the job is marked failed with a message naming the agent.

**7. How do you stop the Q&A agent from making things up?**
It receives the explanation as context and is told to use only that, and to reply "The explanation does not cover this." otherwise. I can't prove an LLM never hallucinates, but the instruction plus the limited context reduces it, and the UI styles "not covered" answers distinctly.

**8. How do you detect truncated output?**
The teacher must finish with `END_OF_EXPLANATION`. No marker means it probably stopped early, so I add a warning. I also check whether the last line looks like a finished sentence.

**9. Which model and why those settings?**
`groq/openai/gpt-oss-20b`, as required. Temperature 0.4 for focused but natural text; `max_tokens` 8192 because gpt-oss's hidden reasoning shares the budget; reasoning effort "low"; `drop_params=True` so unsupported parameters are dropped instead of failing.

**10. How does the `groq/` prefix work?**
CrewAI 1.x has native integrations for a few providers and uses LiteLLM for others. The `groq/` prefix routes through LiteLLM, which reads the key and calls Groq. That's why the requirement is `crewai[litellm]`.

### FastAPI and REST

**11. What is REST, and how does your API follow it?**
Resources are nouns in URLs and HTTP methods are verbs. `generations` is the resource: POST creates one, GET lists them, GET by ID reads one, and `/download` returns a representation of it.

**12. Why does POST return 202, not 200 or 201?**
202 Accepted means the request was received but processing isn't finished. The notes don't exist yet when the response is sent.

**13. What status codes does the API use?**
200, 202, 404 (unknown ID), 409 (download before completion), 413 (body too large), 422 (validation), 429 (too many active jobs), 503 (no API key), 500 (unexpected).

**14. What is dependency injection in FastAPI?**
Declaring `db: Session = Depends(get_db)` makes FastAPI call `get_db`, pass the result in, and clean up afterwards. I use it for database sessions and settings; it also lets tests override settings.

**15. What does `response_model` do?**
It filters and validates the return value against a Pydantic model, converts it to JSON, and documents it at `/docs`.

**16. What is middleware, and what does yours do?**
Code that wraps every request. Mine rejects bodies over 4 KB and adds security headers, plus a Content-Security-Policy for the frontend pages. CORS is also middleware.

### Pydantic and validation

**17. How is the topic validated?**
Required string; control characters rejected; whitespace stripped; 2–120 characters; internal spaces collapsed; unknown fields forbidden. All by `GenerationCreate`.

**18. What happens when validation fails?**
FastAPI raises `RequestValidationError`; my handler returns 422 with a readable `detail` and a list of field errors. The route function never runs.

**19. Why reject newlines in the topic?**
A topic is one line. Multi-line input is a common way to smuggle instructions into prompts, so rejecting it is cheap prompt-injection hardening. The prompt also tells the agent to treat the topic only as a name.

### Database

**20. Why SQLite, and when would you switch?**
It's a single file with no server, perfect for a local portfolio project. With several server instances or a host with an ephemeral disk I'd use PostgreSQL; with SQLAlchemy that's mostly a `DATABASE_URL` change.

**21. Describe your schema.**
One `generations` table: ID, topic, status, completed_steps, the result fields (plan, explanation, JSON Q&A, JSON summary, Markdown, JSON warnings), error message, and created/started/completed timestamps. Status and created_at are indexed.

**22. Why JSON columns instead of separate tables for Q&A?**
They're always read with their generation and never queried alone, so separate tables would add joins without benefit.

**23. How are database sessions managed?**
Requests get one via the `get_db` dependency, closed after the response. The background job opens short sessions with `SessionLocal()` in `with` blocks, and holds none open during the slow LLM calls.

### Background jobs

**24. How does background processing work?**
The route schedules `run_generation` with `BackgroundTasks`. After the response is sent, FastAPI runs it in a worker thread because it's a regular function. The frontend polls the status endpoint.

**25. What happens if the server restarts mid-generation?**
The job is lost, since it lived in memory. On startup, `fail_interrupted_generations` marks pending/processing rows as failed with a message telling the user to resubmit.

**26. How would you make jobs survive restarts?**
Use a persistent queue — Celery or RQ with Redis, or a managed queue — with separate worker processes, and make jobs idempotent so they can be retried.

**27. How is progress reported?**
CrewAI's `task_callback` runs after each task. My callback increments a counter and saves `completed_steps`. The UI shows done/active/waiting only from that number.

### Security

**28. How is the API key protected?**
It's read from the environment on the server only, hidden from `Settings`'s printed form, never returned (health only says true/false), redacted from error messages, and `.env` is git-ignored.

**29. How do you render AI-generated HTML safely?**
I don't render AI HTML at all. The renderer escapes everything, then adds only its own tags; a sanitizer removes anything not on an allowlist; plain text uses `textContent`; and a CSP allows only our own scripts.

**30. What else would you add before deploying publicly?**
Per-IP rate limiting, a daily cap, authentication, bot protection, a separate Groq key with usage alerts, and a persistent database.

### Error handling and testing

**31. How are errors handled in the background job?**
Specific exceptions map to specific messages: missing key, CrewAI/Groq failure (with rate-limit/auth/timeout translated), and output validation. Anything else is logged and shown as a generic error. Partial results are never saved.

**32. How do you test without calling Groq?**
An autouse fixture replaces `run_learning_crew` with a function that fails the test if called. Tests that need results swap in fakes. No key or network is needed.

**33. How does TestClient handle background tasks?**
It runs them before `client.post()` returns, so a test can submit a topic and immediately read the final status.

**34. What do your tests cover?**
All endpoints, ten kinds of invalid input, invalid JSON, oversized bodies, success, crew failure, invalid output, unexpected errors, progress updates, 429 and 503 guards, history ordering and limits, download headers and 404/409, DB helpers, restart cleanup, parsers, the Markdown builder, prompts, key redaction, and that the frontend is served with security headers. The Markdown renderer has Node tests, including XSS cases.

### Reflection

**35. What would you improve next?**
A persistent job queue, user accounts with private history, streaming each agent's output to the page, PostgreSQL, per-user rate limits, and dark mode.

---

## Limitations (say these honestly)

- Background jobs die with the server process; they are marked failed on restart, not resumed.
- The concurrency cap is a count-then-insert check, not atomic.
- No authentication; one shared history per server.
- SQLite is single-server; free hosts with ephemeral disks lose history.
- LLM output can still be wrong even when it passes format validation; the notes say so.
- Validation failures require a manual retry (no automatic retry, to avoid surprise spending).

## Future enhancements

- Celery/RQ or a managed queue for durable jobs and retries.
- User accounts, private histories, and per-user rate limits.
- Server-Sent Events to stream progress instead of polling.
- PostgreSQL and Alembic migrations.
- Export to PDF; dark mode; regenerate a single section.
