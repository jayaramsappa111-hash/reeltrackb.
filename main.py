import csv
import io
import os
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from starlette.middleware.sessions import SessionMiddleware

BASE = Path(__file__).parent
IS_VERCEL = os.getenv("VERCEL") == "1"
# Vercel functions have an ephemeral writable /tmp directory. Use it only as a
# deployment fallback; persistent production storage requires a managed DB.
DB_PATH = Path(os.getenv("DATABASE_PATH", "/tmp/reeltrack.db" if IS_VERCEL else str(BASE / "reeltrack.db")))
ADMIN_USER = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASS = os.getenv("ADMIN_PASSWORD", "ChangeMe-Now-123!")
SECRET = os.getenv("SESSION_SECRET", "local-dev-secret-change-before-deploy")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://127.0.0.1:8000")

if IS_VERCEL and (not os.getenv("ADMIN_USERNAME") or not os.getenv("ADMIN_PASSWORD") or not os.getenv("SESSION_SECRET")):
    raise RuntimeError("Set ADMIN_USERNAME, ADMIN_PASSWORD, and SESSION_SECRET in Vercel Environment Variables.")
if IS_VERCEL and len(SECRET) < 32:
    raise RuntimeError("SESSION_SECRET must be at least 32 characters on Vercel.")

app = FastAPI(title="ReelTrack", version="1.0.0")
app.add_middleware(SessionMiddleware, secret_key=SECRET, https_only=IS_VERCEL, same_site="lax")
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    with db() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS campaigns (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          slug TEXT UNIQUE NOT NULL,
          title TEXT NOT NULL,
          reel_url TEXT,
          created_at TEXT NOT NULL,
          active INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS visits (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          campaign_id INTEGER NOT NULL,
          visited_at TEXT NOT NULL,
          consented INTEGER NOT NULL DEFAULT 0,
          instagram_username TEXT,
          contact_email TEXT,
          FOREIGN KEY(campaign_id) REFERENCES campaigns(id)
        );
        """)
init_db()


def is_admin(request: Request):
    return bool(request.session.get("admin"))


def page(title: str, body: str, request: Request = None):
    nav = ""
    if request and is_admin(request):
        nav = '<nav><a href="/dashboard">Dashboard</a><a href="/logout">Sign out</a></nav>'
    return HTMLResponse(f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1"><title>{title} · ReelTrack</title>
    <link rel="stylesheet" href="/static/style.css"></head><body>
    <header><a class="brand" href="/">ReelTrack<span>.</span></a>{nav}</header>
    <main>{body}</main><footer>ReelTrack · Consent-based campaign analytics</footer>
    </body></html>""")


def require_admin(request: Request):
    if not is_admin(request):
        raise HTTPException(status_code=401, detail="Admin login required")


@app.get("/", response_class=HTMLResponse)
def home():
    return page("Welcome", """
    <section class="hero"><p class="eyebrow">CAMPAIGN LINK MANAGEMENT</p>
    <h1>Understand your<br><span>campaign engagement.</span></h1>
    <p class="muted">Create trackable links, measure visits and manage information visitors choose to share.</p>
    <a class="button" href="/login">Admin sign in</a></section>
    <section class="notice"><b>Privacy first</b><p>ReelTrack never asks for Instagram passwords, login codes or session cookies. Visitors choose what information to share.</p></section>
    """)


@app.get("/login", response_class=HTMLResponse)
def login_form():
    return page("Admin sign in", """
    <section class="panel narrow"><p class="eyebrow">PRIVATE WORKSPACE</p><h1>Admin sign in</h1>
    <form method="post" action="/login"><label>Username<input name="username" required autocomplete="username"></label>
    <label>Password<input type="password" name="password" required autocomplete="current-password"></label>
    <button class="button" type="submit">Sign in</button></form>
    <p class="small muted">Use the admin credentials configured by the site owner.</p></section>
    """)


@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    if not (secrets.compare_digest(username, ADMIN_USER) and secrets.compare_digest(password, ADMIN_PASS)):
        return page("Sign in failed", '<section class="panel narrow"><h1>Sign in failed</h1><p>Check your username and password.</p><a href="/login">Try again</a></section>')
    request.session.clear()
    request.session["admin"] = True
    return RedirectResponse("/dashboard", status_code=303)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    require_admin(request)
    with db() as con:
        campaigns = con.execute("""
          SELECT c.*, COUNT(v.id) AS visits,
          SUM(CASE WHEN v.consented=1 THEN 1 ELSE 0 END) AS submissions
          FROM campaigns c LEFT JOIN visits v ON v.campaign_id=c.id
          GROUP BY c.id ORDER BY c.id DESC
        """).fetchall()
        total_visits = con.execute("SELECT COUNT(*) FROM visits").fetchone()[0]
        total_subs = con.execute("SELECT COUNT(*) FROM visits WHERE consented=1").fetchone()[0]
        visitors = con.execute("""
          SELECT v.*, c.title, c.slug FROM visits v JOIN campaigns c ON c.id=v.campaign_id
          ORDER BY v.id DESC LIMIT 100
        """).fetchall()
    campaign_rows = "".join(
        f"""<tr><td><b>{esc(c['title'])}</b><div class="small muted">{esc(c['slug'])}</div></td>
        <td>{c['visits'] or 0}</td><td>{c['submissions'] or 0}</td>
        <td><a href="/r/{esc(c['slug'])}" target="_blank">Open link ↗</a></td>
        <td><form class="inline" method="post" action="/campaign/{c['id']}/toggle"><button class="textbtn">{'Pause' if c['active'] else 'Activate'}</button></form>
        <form class="inline" method="post" action="/campaign/{c['id']}/delete" onsubmit="return confirm('Delete this campaign and its visitor records?')"><button class="textbtn danger">Delete</button></form></td></tr>"""
        for c in campaigns
    ) or '<tr><td colspan="5">No campaigns yet. Create your first link above.</td></tr>'
    visitor_rows = "".join(
        f"""<tr><td>{esc(v['visited_at'])}</td><td>{esc(v['title'])}</td>
        <td>{('@'+esc(v['instagram_username'])) if v['instagram_username'] else '—'}</td>
        <td>{esc(v['contact_email'] or '—')}</td><td>{'Yes' if v['consented'] else 'No'}</td>
        <td>{('<a target="_blank" rel="noopener" href="https://www.instagram.com/'+esc(v['instagram_username'])+'/">Open public profile ↗</a>') if v['instagram_username'] else '—'}</td></tr>"""
        for v in visitors
    ) or '<tr><td colspan="6">No visitor activity yet.</td></tr>'
    body = f"""
    <div class="dashhead"><div><p class="eyebrow">OVERVIEW</p><h1>Dashboard</h1><p class="muted">Manage campaign links and consented visitor submissions.</p></div><a class="button secondary" href="/export.csv">Export CSV ↓</a></div>
    <section class="stats"><article><span>Total visits</span><strong>{total_visits}</strong></article><article><span>Consented submissions</span><strong>{total_subs}</strong></article><article><span>Campaigns</span><strong>{len(campaigns)}</strong></article></section>
    <section class="panel"><h2>Create a campaign link</h2><form method="post" action="/campaign">
    <label>Campaign name<input name="title" maxlength="80" placeholder="e.g. November Reel" required></label>
    <label>Instagram Reel URL <span class="muted small">(optional)</span><input name="reel_url" type="url" placeholder="https://www.instagram.com/reel/..."></label>
    <button class="button" type="submit">Generate unique link</button></form></section>
    <section class="panel"><div class="sectionhead"><h2>Your links</h2></div><div class="tablewrap"><table><thead><tr><th>Campaign</th><th>Visits</th><th>Submissions</th><th>Visitor link</th><th>Actions</th></tr></thead><tbody>{campaign_rows}</tbody></table></div></section>
    <section class="panel"><div class="sectionhead"><h2>Recent visitors</h2><span class="small muted">Latest 100 records</span></div><div class="tablewrap"><table><thead><tr><th>Visited at (UTC)</th><th>Campaign</th><th>Instagram username</th><th>Email</th><th>Consent</th><th>Profile</th></tr></thead><tbody>{visitor_rows}</tbody></table></div></section>
    """
    return page("Dashboard", body, request)


def esc(value):
    return (str(value) if value is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#x27;")


@app.post("/campaign")
def create_campaign(request: Request, title: str = Form(...), reel_url: str = Form("")):
    require_admin(request)
    title = title.strip()
    if not title or len(title) > 80:
        raise HTTPException(400, "Campaign title must be 1–80 characters")
    if reel_url and not reel_url.startswith(("https://www.instagram.com/", "https://instagram.com/")):
        raise HTTPException(400, "Please provide an Instagram URL")
    slug = secrets.token_urlsafe(7).replace("-", "").replace("_", "")[:10]
    with db() as con:
        con.execute("INSERT INTO campaigns(slug,title,reel_url,created_at) VALUES(?,?,?,?)",
                    (slug, title, reel_url.strip() or None, now()))
    return RedirectResponse("/dashboard", status_code=303)


@app.post("/campaign/{campaign_id}/toggle")
def toggle_campaign(request: Request, campaign_id: int):
    require_admin(request)
    with db() as con:
        con.execute("UPDATE campaigns SET active=1-active WHERE id=?", (campaign_id,))
    return RedirectResponse("/dashboard", status_code=303)


@app.post("/campaign/{campaign_id}/delete")
def delete_campaign(request: Request, campaign_id: int):
    require_admin(request)
    with db() as con:
        con.execute("DELETE FROM visits WHERE campaign_id=?", (campaign_id,))
        con.execute("DELETE FROM campaigns WHERE id=?", (campaign_id,))
    return RedirectResponse("/dashboard", status_code=303)


@app.get("/r/{slug}", response_class=HTMLResponse)
def visitor_page(slug: str):
    with db() as con:
        campaign = con.execute("SELECT * FROM campaigns WHERE slug=?", (slug,)).fetchone()
        if not campaign or not campaign["active"]:
            raise HTTPException(404, "This campaign link is unavailable")
        cur = con.execute("INSERT INTO visits(campaign_id,visited_at) VALUES(?,?)", (campaign["id"], now()))
        visit_id = cur.lastrowid
    reel = f'<a class="button secondary" href="{esc(campaign["reel_url"])}" target="_blank" rel="noopener">View Instagram Reel ↗</a>' if campaign["reel_url"] else ""
    body = f"""
    <section class="panel narrow visitor"><p class="eyebrow">CAMPAIGN LINK</p><h1>{esc(campaign['title'])}</h1>
    <p class="muted">You are visiting a ReelTrack campaign page. This is not an Instagram login page.</p>{reel}
    <div class="notice"><b>Choose what to share</b><p>Optionally submit your Instagram username and email to the campaign administrator. Do not enter your Instagram password or verification codes.</p></div>
    <form method="post" action="/r/{esc(slug)}/submit">
    <input type="hidden" name="visit_id" value="{visit_id}">
    <label>Instagram username <span class="muted small">(optional)</span><input name="instagram_username" maxlength="30" placeholder="your_username" autocomplete="off"></label>
    <label>Email address <span class="muted small">(optional)</span><input name="contact_email" type="email" maxlength="254" placeholder="you@example.com" autocomplete="email"></label>
    <label class="check"><input type="checkbox" name="consent" value="yes" required><span>I agree to share the information above with the campaign administrator.</span></label>
    <button class="button" type="submit">Submit with consent</button></form>
    <p class="small muted">You can leave without submitting any information. ReelTrack does not collect Instagram passwords, login codes or account sessions.</p></section>
    """
    return page("Campaign", body)


@app.post("/r/{slug}/submit")
def visitor_submit(slug: str, visit_id: int = Form(...), instagram_username: str = Form(""),
                   contact_email: str = Form(""), consent: Optional[str] = Form(None)):
    username = instagram_username.strip().lstrip("@")
    email = contact_email.strip()
    if username and (len(username) > 30 or not all(ch.isalnum() or ch in "._" for ch in username)):
        raise HTTPException(400, "Please enter a valid Instagram username")
    if email and (len(email) > 254 or "@" not in email):
        raise HTTPException(400, "Please enter a valid email")
    with db() as con:
        campaign = con.execute("SELECT id FROM campaigns WHERE slug=? AND active=1", (slug,)).fetchone()
        visit = con.execute("SELECT id FROM visits WHERE id=? AND campaign_id=?", (visit_id, campaign["id"] if campaign else -1)).fetchone()
        if not campaign or not visit:
            raise HTTPException(404, "Campaign visit not found")
        if consent != "yes":
            raise HTTPException(400, "Consent is required to submit information")
        con.execute("UPDATE visits SET consented=1, instagram_username=?, contact_email=? WHERE id=?",
                    (username or None, email or None, visit_id))
    return page("Thank you", '<section class="panel narrow"><p class="eyebrow">SUBMISSION RECEIVED</p><h1>Thank you.</h1><p class="muted">Your selected information has been shared with the campaign administrator. No Instagram password or login code was requested or stored.</p><a href="/">Return to ReelTrack</a></section>')


@app.get("/export.csv")
def export_csv(request: Request):
    require_admin(request)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["visited_at_utc", "campaign", "instagram_username", "contact_email", "consented"])
    with db() as con:
        rows = con.execute("""SELECT v.visited_at,c.title,v.instagram_username,v.contact_email,v.consented
                              FROM visits v JOIN campaigns c ON c.id=v.campaign_id ORDER BY v.id DESC""").fetchall()
    for row in rows:
        writer.writerow(list(row))
    output.seek(0)
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=reeltrack-visitors.csv"})


@app.get("/health")
def health():
    return {"status": "ok", "app": "ReelTrack"}
