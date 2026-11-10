# API Reference

Base URL when running locally: `http://127.0.0.1:8000`

Interactive documentation (try requests in the browser): `http://127.0.0.1:8000/docs` (disabled when `APP_ENV=production` unless `ENABLE_API_DOCS=true`).

All request and response bodies are JSON unless noted. Every error response has this shape:

```json
{ "detail": "Human-readable message" }
```

Validation errors (422) also include an `errors` list:

```json
{
  "detail": "topic: String should have at least 2 characters",
  "errors": [{ "field": "topic", "message": "String should have at least 2 characters" }]
}
```

The examples below use `curl`. In **PowerShell**, type `curl.exe` (plain `curl` is an alias for a different command). In **Git Bash**, `curl` works as shown.

---

## GET `/`

API welcome information.

```bash
curl http://127.0.0.1:8000/
```

**200 OK**

```json
{
  "name": "CrewAI Multi-Agent Learning Assistant",
  "version": "1.0.0",
  "message": "Welcome! Submit a technical topic to POST /api/generations.",
  "frontend": "/app/",
  "docs": "/docs",
  "health": "/health"
}
```

`frontend` is `null` when `SERVE_FRONTEND=false`; `docs` is `null` when the docs are disabled.

---

## GET `/health`

Backend health check.

```bash
curl http://127.0.0.1:8000/health
```

**200 OK**

```json
{
  "status": "ok",
  "database": "ok",
  "llm_configured": true,
  "model": "groq/openai/gpt-oss-20b",
  "version": "1.0.0"
}
```

| Field | Meaning |
|---|---|
| `status` | `ok`, or `degraded` if the database query failed |
| `database` | `ok` or `unavailable` |
| `llm_configured` | `true` if `GROQ_API_KEY` is set. The key itself is never returned. |

---

## POST `/api/generations`

Submit a topic. The server saves it, answers immediately, and runs the four agents in the background.

**Request body**

| Field | Type | Rules |
|---|---|---|
| `topic` | string | Required. 2–120 characters after trimming; single line (no newlines/tabs); repeated spaces are collapsed. No other fields allowed. |

```bash
curl -X POST http://127.0.0.1:8000/api/generations \
     -H "Content-Type: application/json" \
     -d '{"topic": "FastAPI"}'
```

PowerShell alternative:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/generations `
  -ContentType "application/json" -Body '{"topic": "FastAPI"}'
```

**202 Accepted**

```json
{
  "id": "6f1c0e5a9b0f4c2d8e7a1b3c5d7e9f01",
  "topic": "FastAPI",
  "status": "pending",
  "progress": { "completed_steps": 0, "total_steps": 4 },
  "created_at": "2026-11-10T08:15:02.112233Z",
  "started_at": null,
  "completed_at": null,
  "teaching_plan": null,
  "explanation": null,
  "qa_pairs": null,
  "summary_points": null,
  "markdown": null,
  "warnings": [],
  "error_message": null
}
```

(Timestamps are UTC; the exact suffix may be `Z` or `+00:00`.)

**Errors**

| Status | When | Example `detail` |
|---|---|---|
| 413 | Body larger than 4 KB | `Request body too large (limit 4096 bytes).` |
| 422 | Missing `topic`, wrong type, empty/whitespace, too short/long, contains a newline, unknown field, invalid JSON | `topic: String should have at most 120 characters` |
| 429 | `MAX_ACTIVE_GENERATIONS` jobs are already pending/processing | `Other generations are still running. Please wait for them to finish and try again.` |
| 503 | `GROQ_API_KEY` is not configured | `The server has no GROQ_API_KEY configured, so it cannot generate content.` |

---

## GET `/api/generations`

Generation history, newest first.

**Query parameters**

| Name | Type | Default | Rules |
|---|---|---|---|
| `limit` | integer | 20 | 1–100 |

```bash
curl "http://127.0.0.1:8000/api/generations?limit=5"
```

**200 OK**

```json
{
  "items": [
    {
      "id": "6f1c0e5a9b0f4c2d8e7a1b3c5d7e9f01",
      "topic": "FastAPI",
      "status": "completed",
      "created_at": "2026-11-10T08:15:02.112233Z",
      "completed_at": "2026-11-10T08:15:51.004512Z"
    }
  ],
  "count": 1
}
```

**Errors:** 422 if `limit` is not an integer between 1 and 100.

---

## GET `/api/generations/{generation_id}`

Status, progress and (when completed) all results of one generation. The frontend polls this every 2 seconds.

```bash
curl http://127.0.0.1:8000/api/generations/6f1c0e5a9b0f4c2d8e7a1b3c5d7e9f01
```

**200 OK — while running**

```json
{
  "id": "6f1c0e5a9b0f4c2d8e7a1b3c5d7e9f01",
  "topic": "FastAPI",
  "status": "processing",
  "progress": { "completed_steps": 2, "total_steps": 4 },
  "started_at": "2026-11-10T08:15:02.301000Z",
  "explanation": null,
  "...": "other result fields are null"
}
```

`completed_steps` is updated by CrewAI's task callback after each agent finishes: 1 = Coordinator, 2 = Teacher, 3 = Q&A, 4 = Summary. After 4, the server validates the outputs and then sets `completed` (or `failed`).

**200 OK — completed** (long fields shortened)

```json
{
  "id": "6f1c0e5a9b0f4c2d8e7a1b3c5d7e9f01",
  "topic": "FastAPI",
  "status": "completed",
  "progress": { "completed_steps": 4, "total_steps": 4 },
  "created_at": "2026-11-10T08:15:02.112233Z",
  "started_at": "2026-11-10T08:15:02.301000Z",
  "completed_at": "2026-11-10T08:15:51.004512Z",
  "teaching_plan": "### Teaching Plan\n1. Explain what an API is.\n...",
  "explanation": "### What is FastAPI?\nFastAPI is a Python framework ...",
  "qa_pairs": [
    { "question": "What is FastAPI?", "answer": "FastAPI is a Python framework for building web APIs ..." },
    { "question": "How does FastAPI validate incoming data?", "answer": "..." },
    { "question": "When would a beginner choose FastAPI?", "answer": "The explanation does not cover this." }
  ],
  "summary_points": ["...", "...", "...", "...", "..."],
  "markdown": "# FastAPI: Learning Notes\n\n> Generated on ...",
  "warnings": [],
  "error_message": null
}
```

**200 OK — failed**

```json
{
  "id": "…",
  "topic": "FastAPI",
  "status": "failed",
  "progress": { "completed_steps": 1, "total_steps": 4 },
  "explanation": null,
  "warnings": [],
  "error_message": "The AI agents could not finish: Groq rate limit reached. Please wait a minute and try again."
}
```

Possible `error_message` values start with one of:

- `GROQ_API_KEY is not configured on the server.`
- `The AI agents could not finish: …` (Groq/CrewAI error, with a friendly reason)
- `The agents' output did not pass validation: …` (e.g. `The Summary Writer produced 4 bullet points instead of exactly 5.`)
- `The server restarted before this generation finished, …`
- `An unexpected server error occurred. Please try again.`

`warnings` may contain notes such as *"The explanation may be incomplete…"* on a completed generation.

**Errors:** 404 `Generation not found.`

---

## GET `/api/generations/{generation_id}/download`

Download the complete learning notes as a Markdown file.

```bash
curl -OJ http://127.0.0.1:8000/api/generations/6f1c0e5a9b0f4c2d8e7a1b3c5d7e9f01/download
```

(`-O -J` saves the file using the server's file name.)

**200 OK**

Headers:

```text
Content-Type: text/markdown; charset=utf-8
Content-Disposition: attachment; filename="fastapi-learning-notes.md"
```

Body (Markdown):

```markdown
# FastAPI: Learning Notes

> Generated on 10 Nov 2026, 08:15 UTC by the CrewAI Multi-Agent Learning Assistant (model: `groq/openai/gpt-oss-20b`).
> AI-generated content can contain mistakes. Check important details against official documentation.

## 1. Learning Plan
...
## 2. Topic Explanation
...
## 3. Questions and Answers
### Q1. What is FastAPI?
...
## 4. Five-Point Summary
1. ...
```

**Errors**

| Status | When |
|---|---|
| 404 | Unknown ID |
| 409 | The generation is not `completed` (still running or failed) |

---

## Other paths

| Path | What it is |
|---|---|
| `/app/` | The website (when `SERVE_FRONTEND=true`) |
| `/docs`, `/redoc`, `/openapi.json` | Auto-generated API documentation (when enabled) |

## Response headers added to every response

| Header | Value | Purpose |
|---|---|---|
| `X-Content-Type-Options` | `nosniff` | Browser must trust the declared content type |
| `Referrer-Policy` | `no-referrer` | Don't leak URLs to other sites |
| `X-Frame-Options` | `DENY` | Page cannot be embedded in another site's frame |
| `Content-Security-Policy` | (only on `/app/...`) | Only our own scripts may run |
