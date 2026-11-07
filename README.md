# ReelTrack

A consent-based Instagram campaign link manager built with FastAPI.

## Features
- Admin sign-in and session protection
- Create, list, pause and delete campaign links
- Unique visitor URLs and click tracking
- Visitor landing page with clear consent
- Optional, voluntary Instagram username and email submission
- Campaign analytics and CSV export
- Local SQLite database for development
- Vercel serverless deployment configuration

## Run locally (Windows PowerShell)

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn main:app --reload
```

Visit http://127.0.0.1:8000. For local testing only, fallback credentials are `admin` / `ChangeMe-Now-123!`. Set your own values before exposing the app.

## Deploy to Vercel

Follow [DEPLOY_TO_VERCEL.md](DEPLOY_TO_VERCEL.md).

**Storage warning:** Vercel uses temporary `/tmp` SQLite storage as a demo fallback. Data is not durable or guaranteed to be shared between serverless instances. Connect persistent PostgreSQL before using real campaign or visitor records.

## Privacy boundary

ReelTrack does not ask for or store Instagram passwords, one-time codes, cookies, or session tokens. Visitors voluntarily choose whether to share their username and email.
