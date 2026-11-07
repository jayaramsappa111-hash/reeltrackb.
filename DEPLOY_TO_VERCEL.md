# Deploy ReelTrack to Vercel

## Important storage limitation

This package is configured to start as a Vercel Python serverless app. The included SQLite database is stored in `/tmp` on Vercel. **That storage is temporary and instance-local**: records can disappear after a function instance is recycled and may not be shared between instances. Use this deployment for a preview/demo only.

For reliable production use, migrate the database to a managed persistent PostgreSQL service (for example, Supabase or Neon) before collecting real visitor records. Vercel `/tmp` is not durable storage.

## Deploy

1. Extract this ZIP. The extracted folder should contain `vercel.json`, `main.py`, `api/`, `static/`, and `requirements.txt`.
2. Push the folder to a GitHub repository and import that repository in Vercel.
3. Keep the Vercel project root set to this folder.
4. In **Project Settings -> Environment Variables**, add:
   - `ADMIN_USERNAME`: your chosen admin username
   - `ADMIN_PASSWORD`: a strong, unique password
   - `SESSION_SECRET`: a random secret of at least 32 characters
   - `PUBLIC_BASE_URL`: your deployed HTTPS URL, e.g. `https://your-project.vercel.app`
5. Apply the variables to Production (and Preview if needed), then redeploy.
6. Open `/health`. It should return `{"status":"ok","app":"ReelTrack"}`.
7. Open `/login` and sign in with your configured credentials.

## Generate a session secret (PowerShell)

```powershell
py -c "import secrets; print(secrets.token_urlsafe(48))"
```

Never commit `.env` or real credentials.

## Routes

- `/` home; `/login`; `/logout`; `/dashboard`
- `/campaign` create campaign
- `/r/{slug}` visitor page
- `/export.csv`; `/health`

## Before production

- Replace temporary SQLite storage with persistent PostgreSQL and test migrations.
- Add rate limiting and monitoring.
- Publish a privacy notice, data-retention policy, and contact details.
- Define consent withdrawal and deletion processes.
- Restrict access to visitor data and configure backups.
