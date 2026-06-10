# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running Locally

**Backend** (FastAPI + scheduler, production entry point):
```bash
source venv/bin/activate
uvicorn api:app --reload --port 8000
```

**Frontend** (Next.js dashboard):
```bash
cd frontend
npm install
cp .env.local.example .env.local   # sets NEXT_PUBLIC_API_URL=http://localhost:8000
npm run dev                         # http://localhost:3000
```

**Standalone CLI runner** (no API server, useful for one-off pipeline tests):
```bash
source venv/bin/activate
python main.py   # runs setup wizard if .env missing, then executes pipeline once
```

## Configuration: Two Sources

There are two separate config sources that must not be conflated:

| Source | What it holds | Who writes it |
|---|---|---|
| `.env` | Secret credentials: `APIFY_API_TOKEN`, `ANTHROPIC_API_KEY`, `GMAIL_SENDER_EMAIL`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REFRESH_TOKEN` | Developer / Railway env vars |
| `settings.json` | User config: `accounts`, `recipient_emails`, `schedule_days` | Frontend dashboard via `POST /api/settings` |

`config.py` handles `.env` via lazy callables (e.g. `config.APIFY_API_TOKEN()`). Each raises `EnvironmentError` loudly if missing — intentional. `settings.json` is read directly by `api.py`'s `load_settings()` / `save_settings()` helpers.

When `api.py` runs the pipeline, it reads `settings.json` first and injects accounts/emails into `os.environ` before calling scraper/emailer — this is how `config.py`'s env-var accessors pick up the dashboard values at runtime.

## Architecture

```
Browser (Vercel)          Railway service
frontend/app/page.tsx  →  api.py (FastAPI + APScheduler)
                                │
                    ┌───────────┼───────────┐
                 scraper.py  analyzer.py  emailer.py
```

`api.py` is the single Railway process. APScheduler runs in a background thread inside it (not a separate process). The scheduler reads `schedule_days` from `settings.json` at startup and is live-updated via `_reschedule()` whenever `POST /api/settings` is called.

**Pipeline data flow:**

1. `scraper.scrape_accounts(accounts)` → `dict[username, list[post_dict]]`  
   Fixed post schema: `url`, `shortCode`, `caption`, `likesCount`, `commentsCount`, `type`, `musicInfo`, `displayUrl`, `timestamp`, `ownerUsername`, `videoViewCount`.

2. `analyzer.analyse(scraped_data)` → `report_dict`  
   Calls Claude (`claude-sonnet-4-6`, `max_tokens=64000` — the model's ceiling, picked so multi-account reports never truncate). Prompt demands raw JSON matching an exact schema. Code fences are stripped before `json.loads()` because Claude occasionally wraps output anyway. `message.stop_reason == "max_tokens"` is logged as a warning so any future truncation is visible. A `_raw_posts` key is injected post-parse (top-5 per account by total engagement) for the emailer.

3. `emailer.send_report(report)` → sends via **Gmail API** (HTTPS, OAuth 2.0 refresh-token flow)  
   Sender is always `GMAIL_SENDER_EMAIL` (the Gmail inbox that authorized the OAuth client). The message is built as a `multipart/related` MIME tree (HTML + inline CID image attachments), base64url-encoded, and POSTed to `gmail.users.messages.send` via the `googleapiclient` SDK. `Credentials` auto-refreshes the short-lived access token using the stored refresh token on every call. `build_html()` prefers `_raw_posts` for accurate Apify thumbnails/URLs; falls back to Claude's synthesised `top_5_posts` if absent. All user-derived strings pass through `_esc()` before insertion into HTML.

   **Why Gmail API and not SMTP:** Railway blocks outbound SMTP on both port 587 (STARTTLS) and 465 (implicit TLS). Gmail API rides over HTTPS so the firewall is moot, and the sender stays as the user's real `@gmail.com` address with no custom domain required. The refresh token is generated once locally via `google-auth-oauthlib`'s `InstalledAppFlow.run_local_server()` and persists indefinitely unless revoked.

   **Email durability:** thumbnails are downloaded at send time and attached as `Content-ID` inline images. This is the key reason the email doesn't degrade after a few days — Instagram's signed CDN URLs (`scontent-*.cdninstagram.com`) expire within hours; the inlined copies live inside the email itself.

## Key Behaviours to Preserve

- `scraper.py` uses `client.actor().call()` (blocking, default actor timeout). `apify-client` 2.x dropped the `timeout_secs` kwarg and changed the return type from a dict to a Pydantic-style `Run` object; field access goes through `_run_field()` which tries attribute → bracket → `model_dump()` so the code works across SDK 1.x and 2.x.
- `config.py` accessors are lambdas so `load_dotenv(override=True)` in `_execute_pipeline()` picks up fresh env values on each run without a process restart.
- Apify actor input uses `directUrls` (full profile URL) not username — avoids Apify's username-resolution step.
- `CORS_ORIGINS` is set via the `FRONTEND_URL` env var in Railway. In local dev it defaults to `*`.
- `settings.json` is the source of truth for accounts/emails at pipeline runtime — Railway env vars for these are not needed.

## Deployment

- **Railway**: start command `uvicorn api:app --host 0.0.0.0 --port $PORT` (via `Procfile`). Env vars required:
  - `APIFY_API_TOKEN`, `ANTHROPIC_API_KEY`
  - `GMAIL_SENDER_EMAIL`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REFRESH_TOKEN` (Gmail API auth)
  - `FRONTEND_URL` (Vercel origin, exact match — no trailing slash)
  - `SETTINGS_DIR=/data` (points to the attached Railway volume so `settings.json` persists across redeploys)
- **Vercel**: root directory set to `frontend/`. Needs `NEXT_PUBLIC_API_URL` pointing to the Railway service URL (must include `https://`, no trailing slash — it's baked into the JS bundle at build time, so changing it requires a fresh Vercel build, not just a save).
