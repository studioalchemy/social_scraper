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
| `settings.json` | User config: `accounts`, `recipient_emails`, `business_problems`, `schedule_days` | Frontend dashboard via `POST /api/settings` |

`config.py` handles `.env` via lazy callables (e.g. `config.APIFY_API_TOKEN()`). Each raises `EnvironmentError` loudly if missing — intentional. `settings.json` is read directly by `api.py`'s `load_settings()` / `save_settings()` helpers.

When `api.py` runs the pipeline, it reads `settings.json` first and injects accounts/emails into `os.environ` before calling scraper/emailer — this is how `config.py`'s env-var accessors pick up the dashboard values at runtime.

## Architecture

```
Browser (Vercel)          Railway service
frontend/app/page.tsx  →  api.py (FastAPI + APScheduler)
                                │
                    ┌───────────┼─────────────┐
                 scraper.py  analyzer.py  ┌──┴─────────┐
                                          report_doc.py emailer.py
```

`report_doc.py` renders the analyzer's JSON into a formal .docx via `python-docx`. `emailer.py` attaches that .docx to a minimal Gmail-API message — no inline HTML report, no thumbnail downloads.

`api.py` is the single Railway process. APScheduler runs in a background thread inside it (not a separate process). The scheduler reads `schedule_days` from `settings.json` at startup and is live-updated via `_reschedule()` whenever `POST /api/settings` is called.

**Pipeline data flow:**

1. `scraper.scrape_accounts(accounts)` → `dict[username, account_data]`  
   For each account, five Apify actors run sequentially:
   - `apify/instagram-profile-scraper` — followers, following, posts count, verified, bio, category
   - `apify/instagram-scraper` (`resultsType: posts`, `addParentData: true`, limit 30) — recent posts
   - `apify/instagram-reel-scraper` (limit 15) — Reels with accurate `playCount`
   - `apify/instagram-comment-scraper` — comments on the top-5 posts by engagement (30 each)
   - `apify/instagram-tagged-scraper` — UGC posts where the account is tagged (limit 15)

   Each per-slice scrape is wrapped in try/except so one actor's failure doesn't poison the whole account — partial data is preserved. The returned `account_data` shape is `{username, profile, posts, reels, comments, tagged_posts}` where `comments` is a dict keyed by post URL. Total per pipeline run: 5 actor types × N accounts ≈ 25 actor invocations for a 5-account brief, ~10–15 min real time. Default actor timeouts apply.

   Post / reel / comment / tagged outputs are normalized via the local `_extract_*` helpers so the analyzer doesn't have to know about each actor's raw schema.

2. `analyzer.analyse(scraped_data, business_problems=[...])` → `report_dict`  
   Calls Claude (`claude-sonnet-4-6`, `max_tokens=64000`, streaming via `client.messages.stream` — required because high `max_tokens` can push the request past 10 min). System prompt defines the full 7-section report structure (header, 6 sections, summary, footer). User message embeds the inputs (BRAND_NAME inferred from the **first account's handle**, BRAND_CATEGORY inferred from the set, BUSINESS_PROBLEMS from settings, ACCOUNTS_ANALYSED with the primary brand flagged) and the scraped data block, then ends with a JSON schema Claude must match. Code fences are stripped before `json.loads()`. `_meta` is injected post-parse with the report date, scrape period, accounts count, and posts scraped — `emailer.py` and `report_doc.py` read from it.

   **The first account in `settings.accounts` is the brand being analysed**, and Section 3 of the report audits that account specifically. Everything else is competitive context. If this convention changes, update the prompt and the dashboard hint together.

3. `report_doc.build_docx_bytes(report)` → `bytes`  
   Renders the JSON report into a formal .docx via `python-docx`. Calibri body, slate-accent headings, 1-inch margins, light-grid-accent tables. Empty / zero numeric cells render as `—` so missing scrape data (Instagram hides like counts on some posts) doesn't read as "actual zero engagement." Page breaks between sections.

4. `emailer.send_report(report)` → sends via **Gmail API** (HTTPS, OAuth 2.0 refresh-token flow)  
   Builds a plain-text email body (one-paragraph notice) with the rendered .docx attached as `MIMEApplication` (`vnd.openxmlformats-officedocument.wordprocessingml.document`). Subject is fixed: `Analysis of ITC social scraper Agent`. Attachment filename is derived from the brand name and report date. The message is base64url-encoded and POSTed to `gmail.users.messages.send`. `Credentials` auto-refreshes the short-lived access token using the stored refresh token on every call.

   **Why Gmail API and not SMTP:** Railway blocks outbound SMTP on both port 587 (STARTTLS) and 465 (implicit TLS). Gmail API rides over HTTPS so the firewall is moot, and the sender stays as the user's real `@gmail.com` address with no custom domain required. The refresh token is generated once locally via `google-auth-oauthlib`'s `InstalledAppFlow.run_local_server()` and persists indefinitely unless revoked.

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
