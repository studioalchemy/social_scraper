# ITC Social Scraper Agent

A scheduled competitive-intelligence agent for Instagram. It scrapes a set of brand accounts, sends the data to Claude for a structured 7-section competitive analysis, renders the result as a formal Word document, and emails it to a recipient list — automatically, on the cadence the user chooses, from a web dashboard.

The agent runs as two services: a **FastAPI + APScheduler backend** (hosted on Railway) and a **Next.js dashboard** (hosted on Vercel) that the user configures it from.

---

## How the agent works

### 1. The user configures everything from a dashboard

The Vercel-hosted dashboard is the only thing the user ever touches. From it, they can set:

- **Accounts** — Instagram handles to watch. The **first handle is the brand being analysed**; everything below it is a competitor the brand is benchmarked against. A "Your brand" badge marks the first chip so the convention stays visible.
- **Recipients** — email addresses the report is sent to.
- **Business problems** — up to three concise statements (e.g. "increase purchase frequency"). Every recommendation in the final report is anchored back to these.
- **Cadence** — a slider for "every N days" (1–90).
- **Lookback window** — how far back the scraper looks for content. Two modes:
  - *Days* — a slider from 3 to 90 days (default 15).
  - *Custom range* — explicit From/To dates with mutual min/max constraints.
- **Monthly 2-month deep-dive** — a toggle that, when on, adds a *second* report on the 1st of every month covering a fixed 60-day window. Independent of the lookback slider.
- **Agent kill switch** — a banner at the very top of the dashboard. Toggling it off immediately pauses both scheduled jobs and disables the manual Run Now button. No reports go out until the user flips it back on. Re-anchors the regular cadence to the resume time.

All of this lands in a `settings.json` file persisted to a Railway volume (`/data/settings.json`) so it survives container restarts.

### 2. Two reports, each on its own schedule

The backend runs **APScheduler** on the `Asia/Kolkata` timezone:

| Report | When it fires | Lookback window | Subject line | Focus |
|---|---|---|---|---|
| **Regular** | Every N days at **09:30 IST** | Whatever the user set on the dashboard | `Analysis of ITC social scraper Agent` | Standard 7-section report |
| **Monthly 2-month** *(opt-in)* | 1st of every month at **10:00 IST** | Fixed last 60 days, ignores the slider | `Analysis of ITC social scraper Agent — Monthly 2-Month Deep-Dive` | Re-weighted toward competitor wins, trends, growth signals, share/save drivers, plays the brand can borrow |

The user can also click **Run Now** for an immediate ad-hoc fire of the regular report (the monthly version is cron-only).

### 3. Each run goes through the same four stages

**a) Scrape** — for every configured account, six Apify actors run sequentially with graceful per-slice failure handling:

| Actor | What it gets |
|---|---|
| `apify/instagram-profile-scraper` | Profile metadata: followers, following, post count, verified status, bio, category |
| `apify/instagram-scraper` (posts) | Up to 30 recent posts with engagement, captions, hashtags, media URLs |
| `apify/instagram-reel-scraper` | Up to 15 Reels with accurate `playCount` |
| `apify/instagram-comment-scraper` | 30 comments each from the top-5 posts by engagement |
| `apify/instagram-tagged-scraper` | Up to 15 UGC posts where the account is tagged |
| `apify/brand-collaboration-scraper` | Up to 20 paid-partnership posts, surfacing creator handles and post URLs |

The lookback window is enforced two ways: the posts actor honours `onlyPostsNewerThan` natively, and every other slice is post-filtered by `timestamp`. Items with unparseable timestamps are kept rather than dropped silently.

For a typical 5-account brief that's ~30 actor invocations and 12–18 minutes of real time.

**b) Analyse** — the scraped JSON is sent to **Claude (`claude-sonnet-4-6`, `max_tokens=64000`, streaming)**. The system prompt is a fully-specified 7-section report template (Header, 6 sections, Top-10 Summary, Footer). The user message embeds:

- Inferred `BRAND_NAME` (from the first handle) and `BRAND_CATEGORY` (from the set)
- The list of business problems
- All accounts flagged with their role (primary brand vs. competitor)
- The complete scraped data block
- The exact JSON schema Claude must return

For monthly 2-month runs, a `MONTHLY_FOCUS_DIRECTIVE` is prepended to the user message that re-weights Sections 3 and 5 toward the competitor-growth analysis described in the table above. The regular run takes no focus directive.

**c) Render** — the JSON report is rendered to a formal `.docx` via `python-docx`:

- Calibri body, slate-accent headings, 1.0" top/bottom margins, **0.5" left/right margins** (7.5" usable width)
- Light-Grid-Accent tables with white-on-slate headers
- Top 5 Performing Posts table uses explicit column widths so the prose `why_it_worked` column gets ~3" instead of being squeezed by autofit
- Empty / zero cells render as `—` so missing data (Instagram hides like counts on some posts) doesn't read as actual zero engagement
- Per-account **Creator Collaborations** subsection lists every brand-partnership creator detected in that scrape window

**d) Email** — the `.docx` is attached to a plain-text MIME message and sent via the **Gmail API** (HTTPS, OAuth 2.0 refresh-token flow). Subject differs by report type (table above). Attachment filename is derived from the brand name + report date.

Gmail API is used instead of SMTP because Railway blocks outbound SMTP on both 587 and 465 — Gmail API rides over HTTPS so the firewall is moot, and the sender stays as the configured Gmail address with no custom domain required.

### 4. The security model

- **Bearer token on every mutating endpoint** — `/api/settings`, `/api/status`, `/api/run`, `/api/agent`. The server reads `API_BEARER_TOKEN` from env; missing → 503 (fail closed), missing/wrong header → 401. `/api/health` stays public for Railway's monitor.
- **Vercel proxy hides the token from the browser** — the dashboard calls relative `/api/*` paths handled by `frontend/app/api/[...path]/route.ts`. That handler reads a **private** env var (no `NEXT_PUBLIC_` prefix) and forwards to Railway with the bearer attached server-side. Opening DevTools on the dashboard only shows browser ↔ Vercel traffic; the token never reaches the browser.
- **Input validation at the API layer**:
  - Handles: `^[a-zA-Z0-9._]{1,30}$` after stripping `@` and lowercasing. Stops `nike/p/abcd`-style attempts to redirect Apify.
  - Emails: practical shape + explicit `\r`/`\n` rejection. Stops Bcc-injection through the recipient list.
  - Lookback dates: parsed via `datetime.fromisoformat`, invalid input becomes `None`.
  - All bounded fields are clamped at the API boundary.
- **Settings persistence** lives on a Railway volume at `/data`, so the token-required state and all user config survive redeploys.

---

## Setup

### Architecture

```
Browser (visitor)
       │
       ▼
Vercel  ──── proxy: frontend/app/api/[...path]/route.ts
       │            attaches Authorization: Bearer <token>
       ▼
Railway ──── api.py (FastAPI + APScheduler)
                │
       ┌────────┼──────────────────────────────┐
       ▼        ▼              ▼               ▼
   scraper.py  analyzer.py  report_doc.py  emailer.py
   (Apify)     (Claude)     (python-docx)  (Gmail API)
```

The Next.js dashboard never talks to Railway directly. All calls go to Vercel's own origin first, get authenticated server-side, then proxy to Railway.

### What you need before deploying

| Service | What for | Cost |
|---|---|---|
| **Apify** | Six Instagram scraper actors | Pay-per-use; ~$0.50–$2 per 5-account brief |
| **Anthropic** | Claude Sonnet 4.6 for the analysis | Pay-per-use; ~$0.50 per report at 64k max_tokens |
| **Google Cloud** | OAuth client for the Gmail API | Free |
| **Railway** | Hosts the FastAPI backend + the volume holding `settings.json` | Free tier OK for low cadences; $5/mo on Hobby |
| **Vercel** | Hosts the Next.js dashboard + the proxy route | Free tier is fine |
| **A GitHub repo** | Source of truth for both Railway and Vercel | Free |

### 1. Get your API tokens

**Apify** — Sign up → Settings → Integrations → API Token. Save as `APIFY_API_TOKEN`.

**Anthropic** — [console.anthropic.com](https://console.anthropic.com) → API keys → create. Save as `ANTHROPIC_API_KEY`.

**Gmail API** — this is the longest one because OAuth wants a refresh token, not a password:

1. Go to [Google Cloud Console](https://console.cloud.google.com) → create a new project.
2. **APIs & Services → Library → Gmail API → Enable.**
3. **APIs & Services → OAuth consent screen** → External → fill in app name (any), support email, developer email. Add the Gmail address you want to send *from* as a Test User under the Audience tab.
4. **APIs & Services → Credentials → Create Credentials → OAuth client ID** → Application type: **Desktop app**. Download the JSON. You only need the `client_id` and `client_secret` from it.
5. Generate a refresh token from your local machine (one-time):

   ```bash
   pip install google-auth-oauthlib
   python3 -c "
   from google_auth_oauthlib.flow import InstalledAppFlow
   flow = InstalledAppFlow.from_client_config({
       'installed': {
           'client_id': 'YOUR_CLIENT_ID',
           'client_secret': 'YOUR_CLIENT_SECRET',
           'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
           'token_uri': 'https://oauth2.googleapis.com/token',
           'redirect_uris': ['http://localhost']
       }
   }, ['https://www.googleapis.com/auth/gmail.send'])
   creds = flow.run_local_server(port=0)
   print('Refresh token:', creds.refresh_token)
   "
   ```

   A browser window opens; sign in with the Gmail account you added as a Test User. Copy the printed refresh token.

6. Save these four values:
   - `GMAIL_SENDER_EMAIL` — the Gmail address you signed in with
   - `GOOGLE_CLIENT_ID` — from the JSON
   - `GOOGLE_CLIENT_SECRET` — from the JSON
   - `GOOGLE_REFRESH_TOKEN` — what the script just printed

### 2. Generate the bearer token

This is the shared secret that authenticates the dashboard with the backend:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

Copy that string. You'll paste the **same value** in three places: Railway, Vercel, and (optionally) your local `.env` files.

### 3. Deploy the backend to Railway

1. Push the repo to GitHub.
2. [railway.app](https://railway.app) → New Project → Deploy from GitHub repo → pick yours.
3. **Variables** tab — add all of these:

   | Key | Value |
   |---|---|
   | `APIFY_API_TOKEN` | from step 1 |
   | `ANTHROPIC_API_KEY` | from step 1 |
   | `GMAIL_SENDER_EMAIL` | the Gmail address |
   | `GOOGLE_CLIENT_ID` | from step 1 |
   | `GOOGLE_CLIENT_SECRET` | from step 1 |
   | `GOOGLE_REFRESH_TOKEN` | from step 1 |
   | `API_BEARER_TOKEN` | the token from step 2 |
   | `FRONTEND_URL` | the Vercel URL (after step 4) — exact match, no trailing slash |
   | `SETTINGS_DIR` | `/data` |

4. **Settings → Volumes** → add a volume → mount path `/data`. This is where `settings.json` persists across redeploys.
5. Railway picks up the start command from `Procfile` automatically (`uvicorn api:app --host 0.0.0.0 --port $PORT`).
6. **Settings → Domains** → generate a public domain. Copy it — that's your `BACKEND_API_URL`.

### 4. Deploy the dashboard to Vercel

1. [vercel.com](https://vercel.com) → Add New → Project → import your repo.
2. **Root Directory** → `frontend/`.
3. **Environment Variables**:

   | Key | Value | Visibility |
   |---|---|---|
   | `BACKEND_API_URL` | the Railway URL from step 3.6 (no trailing slash) | server-only |
   | `BACKEND_API_TOKEN` | same value as Railway's `API_BEARER_TOKEN` | server-only |

   **Neither variable should be prefixed with `NEXT_PUBLIC_`.** That prefix would expose them to the browser and defeat the purpose of the proxy.

4. Deploy. Vercel will install `node_modules/` and build the Next.js app automatically.
5. Once it's up, go back to Railway and set `FRONTEND_URL` to the Vercel URL.

### 5. Configure from the dashboard

1. Visit your Vercel URL.
2. Add accounts (first handle = the brand being analysed).
3. Add recipient emails.
4. Add 1–3 business problems.
5. Pick the cadence + lookback window.
6. Optionally flip the monthly 2-month deep-dive on.
7. Click **Save settings**. Then **Run now** for the first report so you can verify the end-to-end pipeline works.

### Local development

Backend:
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# .env with all of the same env vars as Railway, plus:
# API_BEARER_TOKEN=<the token>

uvicorn api:app --reload --port 8000
```

Frontend:
```bash
cd frontend
npm install
cp .env.local.example .env.local
# edit .env.local — both vars need to be set:
#   BACKEND_API_URL=http://localhost:8000
#   BACKEND_API_TOKEN=<same token as backend's API_BEARER_TOKEN>
npm run dev   # http://localhost:3000
```

There's also a standalone CLI runner if you want to test the pipeline without spinning up the API server:
```bash
source venv/bin/activate
python main.py
```

---

## Reference

### Project structure

```
social_scraper/
├── api.py             # FastAPI app + APScheduler (single Railway process)
├── scraper.py         # Orchestrates the 6 Apify actors with per-slice fault isolation
├── analyzer.py        # Claude streaming call + 7-section system prompt + focus-directive plumbing
├── report_doc.py      # python-docx renderer for the 7-section report
├── emailer.py         # Gmail API send with the .docx attachment
├── config.py          # Env-var accessors (lambdas, lazy, raise on missing)
├── main.py            # Standalone CLI runner — runs the pipeline once and exits
├── Procfile           # `web: uvicorn api:app --host 0.0.0.0 --port $PORT`
├── requirements.txt
├── CLAUDE.md          # Internal notes for Claude Code sessions
└── frontend/
    ├── app/
    │   ├── page.tsx                       # The dashboard UI
    │   ├── globals.css                    # All styles (dark Apple-ish theme)
    │   ├── api/[...path]/route.ts         # Server-side proxy that injects the bearer token
    │   └── layout.tsx, etc.
    ├── package.json
    └── .env.local.example
```

### API endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/api/health` | none | Public health check (Railway monitor) |
| `GET` | `/api/settings` | Bearer | Read current settings |
| `POST` | `/api/settings` | Bearer | Persist new settings; re-applies scheduler + monthly job + kill-switch state |
| `GET` | `/api/status` | Bearer | Read run state (`{running, last_run, last_error, status}`) |
| `POST` | `/api/run` | Bearer | Trigger a one-off regular run in the background. 409 if a run is already in progress or the agent is paused |
| `POST` | `/api/agent` | Bearer | Immediate kill switch toggle, body `{enabled: bool}` |

### Settings file shape

`/data/settings.json` (Railway volume):

```jsonc
{
  "accounts": ["sunfeastdarkfantasy", "oreo_in", "...competitors"],
  "recipient_emails": ["team@itc.in"],
  "business_problems": [
    "Increase purchase frequency among Gen-Z",
    "Stand out in the dark-chocolate-biscuit category"
  ],
  "schedule_days": 7,                       // 1–90, regular cadence
  "lookback_mode": "days",                  // "days" | "custom"
  "lookback_days": 15,                      // 1–180; used when mode == "days"
  "lookback_start": null,                   // "YYYY-MM-DD"; used when mode == "custom"
  "lookback_end": null,                     // "YYYY-MM-DD"; used when mode == "custom"
  "monthly_two_month_report": false,        // monthly 60-day deep-dive on the 1st
  "agent_enabled": true                     // kill switch
}
```

### Scheduling details

- Scheduler timezone is `Asia/Kolkata`. `tzdata` is pinned in `requirements.txt` so it works on slim container images.
- **Regular job (`trend_report`)** — `IntervalTrigger(days=N, start_date=<next 09:30 IST>)`. Re-saving settings or resuming from a pause both re-anchor `start_date` to the next 09:30 IST from "now," so the cadence restarts cleanly.
- **Monthly job (`monthly_two_month_report`)** — `CronTrigger(day=1, hour=10, minute=0, timezone=IST)`. Calendar-anchored — pausing skips a month, resuming picks up next 1st.
- A single `_run_lock` prevents the regular cron, the monthly cron, and a manual Run Now from running concurrently. Whichever holds the lock wins; the others early-return.
- `run_pipeline_background` checks `agent_enabled` at entry as defense in depth. Even if the scheduler somehow fires a paused job, no pipeline runs.

### Known behaviours

- **Instagram hides like counts on some posts.** The DOCX renderer turns empty / zero numeric cells into an em-dash (`—`) so they don't read as "actual zero engagement." If you see a lot of em-dashes for one account, that's Instagram's privacy default, not a scraper bug.
- **The Apify SDK changed shape in 2.x.** `client.actor().call()` now returns a Pydantic-style `Run` object instead of a dict. `scraper._run_field()` probes attribute / bracket / `model_dump` access so the code works across SDK 1.x and 2.x.
- **`NEXT_PUBLIC_API_URL` is no longer used.** Older versions of the dashboard read the backend URL from a public env var; the proxy reads it from a private one. If you migrated from an earlier setup, you can delete the old `NEXT_PUBLIC_API_URL` and `NEXT_PUBLIC_API_TOKEN` from Vercel.
- **The `Procfile` start command must include `--host 0.0.0.0`.** Railway routes the public port to `0.0.0.0:$PORT`, not localhost.
- **`FRONTEND_URL` must have no trailing slash.** CORS does exact-match origin checking.
- **The first account in `accounts` is the brand being analysed.** Section 3 of the report audits that account specifically. Everything else is competitive context. The dashboard surfaces this convention with a "Your brand" badge on the first chip.
