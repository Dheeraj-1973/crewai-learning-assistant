# Setup and Execution (Windows 11)

Commands are given for **PowerShell** and **Git Bash**. Use one terminal type consistently. In Cursor, open a terminal with `` Ctrl+` `` and pick the shell from the dropdown next to the `+` button.

---

## 1. Install Python 3.12

1. Download **Python 3.12.10** (64-bit) from <https://www.python.org/downloads/windows/>.
2. In the installer, tick **"Add python.exe to PATH"**, then click *Install Now*.
3. Check it worked:

```powershell
py -3.12 --version     # Python 3.12.10
```

CrewAI supports Python 3.10–3.13. Do not use 3.14 for this project.

## 2. Get the project

Unzip `crewai-learning-assistant.zip`, then open the `crewai-learning-assistant` folder in Cursor (*File → Open Folder*). All commands below start from that folder.

To put it on GitHub:

```bash
git init
git add .
git commit -m "Initial commit: CrewAI Multi-Agent Learning Assistant"
git branch -M main
git remote add origin https://github.com/<your-username>/crewai-learning-assistant.git
git push -u origin main
```

`.gitignore` already excludes `.env`, the virtual environment, caches and the database.

## 3. Create a virtual environment

A **virtual environment** is a private folder of Python packages for this project only.

**PowerShell**

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell says *"running scripts is disabled on this system"*, run this once and try again:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

**Git Bash**

```bash
py -3.12 -m venv .venv
source .venv/Scripts/activate
```

Your prompt now starts with `(.venv)`. In Cursor, also choose this interpreter: `Ctrl+Shift+P` → *Python: Select Interpreter* → `.venv`.

## 4. Install dependencies

```bash
python -m pip install --upgrade pip
pip install -r backend/requirements.txt
```

(PowerShell accepts either `/` or `\` in the path.) CrewAI pulls in many packages, so this can take several minutes.

## 5. Configure `.env`

**PowerShell:** `Copy-Item .env.example .env`
**Git Bash:** `cp .env.example .env`

Open `.env` and replace `your_groq_api_key_here` with your key from <https://console.groq.com/keys>. Never commit or share this file. The other values have sensible defaults; each is explained in `.env.example`.

## 6. Start the backend (and the website)

```bash
cd backend
uvicorn app.main:app --reload
```

You should see `Uvicorn running on http://127.0.0.1:8000`. Leave this terminal open.

| Open this | To see |
|---|---|
| <http://127.0.0.1:8000/app/> | The website |
| <http://127.0.0.1:8000/docs> | Interactive API documentation |
| <http://127.0.0.1:8000/health> | `llm_configured` should be `true` |

`--reload` restarts the server when you save a Python file. Remember: a restart stops any generation that is running (it will be marked failed). Leave out `--reload` when you don't need it.

Stop the server with `Ctrl+C`.

## 7. Alternative: serve the frontend separately

Normally the backend serves the frontend at `/app/`. If you prefer the Live Server extension (port 5500), or another static server:

```bash
cd frontend
python -m http.server 5500
```

Open <http://127.0.0.1:5500/>. `js/config.js` detects that the page did not come from `/app` and sends API requests to `http://127.0.0.1:8000`. The default `CORS_ORIGINS` already allows port 5500. The backend must still be running.

## 8. Run the tests

The tests never call Groq and need no API key.

```bash
cd backend
pytest
```

Useful variations:

```bash
pytest -v                          # one line per test
pytest tests/test_api.py           # one file
pytest -k download                 # tests whose name contains "download"
```

Frontend Markdown renderer tests (optional, needs Node.js 18+ from <https://nodejs.org>), from the project root:

```bash
node --test frontend/tests/markdown.test.js
```

## 9. Using it

1. Type a topic or click an example, then **Generate notes**.
2. Watch the four steps tick off. A full run usually takes under a couple of minutes, depending on Groq.
3. Read, copy, or **Download Markdown**.
4. Reopen anything from **Recent topics**.

Each generation makes four LLM calls to Groq (one per agent).

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `py` is not recognized | Reinstall Python with "Add python.exe to PATH", or use the full path to `python.exe`. |
| `Activate.ps1 cannot be loaded` | Run the `Set-ExecutionPolicy` command in step 3. |
| `ModuleNotFoundError: No module named 'app'` | Run `uvicorn` and `pytest` from inside the `backend` folder. |
| `ModuleNotFoundError: fastapi` / `crewai` | The virtual environment is not active, or step 4 was skipped. |
| `Microsoft Visual C++ 14.0 or greater is required` during install | Install "Build Tools for Visual Studio" (C++ build tools) and run step 4 again. |
| Install fails with long file paths | Move the project to a short path like `C:\dev\crewai-learning-assistant`, or enable Windows long paths. |
| Banner: "has no Groq API key" | `.env` is missing, in the wrong folder (it must sit next to `.env.example`), or the key line is wrong. Restart the backend after editing. |
| Banner: "Can't reach the backend server" | Start the backend (step 6), and check it is on port 8000. |
| `[Errno 10048] address already in use` | Another program uses port 8000. Stop it, or run `uvicorn app.main:app --reload --port 8001` and open that port. |
| Generation fails with "rate limit" | Free Groq accounts have per-minute limits. Wait a minute and try again. |
| Generation fails with "rejected the API key" | Create a new key and update `.env`. |
| Generation fails validation (e.g. "4 bullet points instead of exactly 5") | The model didn't follow the format this time; click **Try this topic again**. |
| Warning "explanation may be incomplete" | The model stopped before its end marker. Try again, or raise `LLM_MAX_TOKENS` in `.env`. |
| Jobs marked "server restarted" | Expected after the server stopped mid-run (including `--reload` restarts). Submit again. |
| "Other generations are still running" (429) | Wait, or raise `MAX_ACTIVE_GENERATIONS` (this spends quota faster). |
| CORS error in the browser console | Serve the page from `/app/`, or add the page's origin to `CORS_ORIGINS`. |
| See every agent step in the terminal | Set `CREW_VERBOSE=true` in `.env` and restart. |

---

## Deploying online

Do not deploy until you have read the security section below: a public site lets strangers spend your Groq quota.

### Recommended: one web service (backend + frontend together)

Because FastAPI already serves the frontend at `/app`, a single service is the simplest setup: one URL, no CORS, and the Content-Security-Policy header protects the pages.

Example with **Render** (it supports Python web services from a GitHub repo):

1. Push the project to GitHub (step 2).
2. In Render, create a **Web Service** from the repository.
3. Settings:

| Setting | Value |
|---|---|
| Build command | `pip install -r backend/requirements.txt` |
| Start command | `cd backend && uvicorn app.main:app --host 0.0.0.0 --port $PORT` |

4. Environment variables (set in Render's dashboard, never in Git):

| Variable | Value |
|---|---|
| `PYTHON_VERSION` | `3.12.10` |
| `GROQ_API_KEY` | your key |
| `APP_ENV` | `production` (hides `/docs`) |
| `CORS_ORIGINS` | `https://<your-service>.onrender.com` |
| `MAX_ACTIVE_GENERATIONS` | `1` |

5. Visit `https://<your-service>.onrender.com/app/`.

**Free-tier limitations (check Render's current pricing page before relying on these):** according to Render's documentation, a free web service spins down after 15 minutes without traffic and takes about a minute to wake up; free services get 750 instance hours per month; and their filesystem is ephemeral, so a SQLite database is lost on every redeploy, restart or spin-down. Free services cannot attach a persistent disk. For this project that means **history resets** on the free tier. Options: accept it for a demo, use a paid instance with a persistent disk and point `DATABASE_URL` at it, or move to a hosted PostgreSQL database (SQLAlchemy supports it with a different `DATABASE_URL` and the `psycopg` driver).

Any similar platform works (Railway, Fly.io, a small VPS); the build and start commands are the same idea.

### Alternative: separate frontend hosting

You can host `frontend/` on a static host (Netlify, GitHub Pages, Cloudflare Pages) and the backend elsewhere:

1. In `frontend/js/config.js`, set `PRODUCTION_API_URL` to your backend URL, e.g. `"https://my-api.onrender.com"`.
2. On the backend, set `CORS_ORIGINS` to your frontend's exact origin, e.g. `https://my-notes.netlify.app`, and `SERVE_FRONTEND=false`.
3. Add a Content-Security-Policy through the static host's headers settings (the backend's CSP header only covers pages it serves itself). Its `connect-src` must include the backend URL.

### Database persistence

| Setup | History survives restarts? |
|---|---|
| Local machine | Yes (file in `backend/data/`) |
| Free host with ephemeral disk | No |
| Host with a persistent disk + `DATABASE_URL` on that disk | Yes |
| Managed PostgreSQL | Yes, and supports several server instances |

### Secret management

- Set `GROQ_API_KEY` only in the host's environment-variable settings.
- Use a **separate Groq key** for the public deployment so you can revoke it without affecting your own work.
- Never print settings or environment variables in logs. (`Settings` hides the key from its printed form.)

### Protections to add before going public

The project already has input validation, a 4 KB body limit, a concurrency cap, generic error messages, no secret exposure, safe rendering and security headers. For a public site that spends **your** Groq quota, also add:

1. **Per-visitor rate limiting**, e.g. a few generations per IP address per hour (a library such as `slowapi`, or your host's/CDN's rate-limiting rules).
2. **A daily total cap** on generations, checked in `submit_generation`.
3. **Authentication**, even a simple shared password or sign-in, so only intended users can generate.
4. **Bot protection** on the form (e.g. a CAPTCHA such as Cloudflare Turnstile).
5. **Spending limits/alerts** in your Groq account, if available for your plan, and monitoring of usage.
6. **A persistent job system** if reliability matters (jobs currently die with the process).
7. Keep `APP_ENV=production` so `/docs` is hidden, and keep HTTPS (hosts provide it).

### Costs

- Groq: check your plan's limits and prices at <https://console.groq.com>; each generation is four model calls.
- Hosting: free tiers exist but have the limitations above; persistent storage usually requires a paid plan.

Nothing in this project deploys or creates accounts automatically; every step above is yours to take.
