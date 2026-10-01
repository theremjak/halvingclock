"""X (Twitter) OAuth 2.0 for the Halving Clock bot.

X's pay-per-use apps post with OAuth 2.0 user tokens: the access token lasts ~2 hours and every refresh returns a NEW
refresh token that replaces the old one. So the daily job must save the rotated token every run.

Storage: Cloudflare Workers KV (namespace "halvingclock-secrets"), reached with the workflow's existing
CLOUDFLARE_API_TOKEN, so no extra GitHub token is needed. The very first refresh token comes from the one-time
authorization below, saved as GitHub secrets X_REFRESH_TOKEN_INIT + X_INIT_ID; a new authorization (new X_INIT_ID)
always wins over whatever is in KV.

One-time setup (run locally; opens your browser — be logged in to X as the bot account):
    python x_oauth.py setup          reads ~/halvingclock-x-oauth.txt (CLIENT_ID=… / CLIENT_SECRET=…)
"""
import base64
import hashlib
import http.server
import json
import os
import secrets
import subprocess
import sys
import threading
import urllib.parse
import webbrowser
from pathlib import Path

import requests

TOKEN_URL = "https://api.x.com/2/oauth2/token"
AUTH_URL = "https://x.com/i/oauth2/authorize"
REDIRECT = "http://127.0.0.1:8976/callback"
SCOPES = "tweet.read tweet.write users.read media.write offline.access"
KV_TITLE = "halvingclock-secrets"
KV_KEY = "x_oauth"
REPO = "theremjak/halvingclock"


# ───────────── Cloudflare KV (daily job) ─────────────

def _cf():
    tok, acct = os.environ.get("CLOUDFLARE_API_TOKEN"), os.environ.get("CLOUDFLARE_ACCOUNT_ID")
    if not (tok and acct):
        raise RuntimeError("CLOUDFLARE_API_TOKEN / CLOUDFLARE_ACCOUNT_ID missing (needed to store the rotating X token)")
    return f"https://api.cloudflare.com/client/v4/accounts/{acct}/storage/kv/namespaces", {"Authorization": f"Bearer {tok}"}


def _namespace():
    base, h = _cf()
    r = requests.get(base, headers=h, params={"per_page": 100}, timeout=30)
    r.raise_for_status()
    for ns in r.json()["result"]:
        if ns["title"] == KV_TITLE:
            return ns["id"]
    r = requests.post(base, headers=h, json={"title": KV_TITLE}, timeout=30)
    r.raise_for_status()
    return r.json()["result"]["id"]


def _kv_get(ns):
    base, h = _cf()
    r = requests.get(f"{base}/{ns}/values/{KV_KEY}", headers=h, timeout=30)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return json.loads(r.text)


def _kv_put(ns, value):
    base, h = _cf()
    r = requests.put(f"{base}/{ns}/values/{KV_KEY}", headers=h, data=json.dumps(value), timeout=30)
    r.raise_for_status()


def access_token():
    """Refresh → save the rotated refresh token to KV immediately → return a fresh access token."""
    cid, csec = os.environ.get("X_CLIENT_ID", "").strip(), os.environ.get("X_CLIENT_SECRET", "").strip()
    init, init_id = os.environ.get("X_REFRESH_TOKEN_INIT", "").strip(), os.environ.get("X_INIT_ID", "").strip()
    if not (cid and csec and (init or init_id)):
        return None
    ns = _namespace()
    stored = _kv_get(ns)
    rt = stored["refresh_token"] if stored and stored.get("init_id") == init_id else init
    r = requests.post(TOKEN_URL, auth=(cid, csec), timeout=30,
                      data={"grant_type": "refresh_token", "refresh_token": rt, "client_id": cid})
    if not r.ok:
        raise RuntimeError(f"X token refresh {r.status_code}: {r.text[:200]} — re-run `python x_oauth.py setup`")
    tok = r.json()
    if tok.get("refresh_token"):
        _kv_put(ns, {"init_id": init_id, "refresh_token": tok["refresh_token"]})   # before anything else can fail
    return tok["access_token"]


# ───────────── one-time setup (local) ─────────────

def _read_client():
    f = Path("~/halvingclock-x-oauth.txt").expanduser()
    if not f.exists():
        sys.exit(f"Missing {f}. It needs two lines:\nCLIENT_ID=...\nCLIENT_SECRET=...")
    vals = dict(line.split("=", 1) for line in f.read_text().splitlines() if "=" in line)
    cid, csec = vals.get("CLIENT_ID", "").strip(), vals.get("CLIENT_SECRET", "").strip()
    if not (cid and csec):
        sys.exit(f"{f} must contain CLIENT_ID=... and CLIENT_SECRET=... (values from the X console, OAuth 2.0 section)")
    return cid, csec


def _gh_secret(name, value):
    gh = "/opt/homebrew/bin/gh" if Path("/opt/homebrew/bin/gh").exists() else "gh"
    subprocess.run([gh, "secret", "set", name, "--repo", REPO, "--body", value], check=True, capture_output=True)


def setup(expect="halvingclock"):
    cid, csec = _read_client()
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    got = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            got.update({k: v[0] for k, v in q.items()})
            ok = "code" in got and got.get("state") == state
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(("<h2>Done. You can close this tab and go back to the terminal.</h2>" if ok
                              else f"<h2>Authorization failed: {got.get('error', 'unknown')}</h2>").encode())

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 8976), Handler)
    t = threading.Thread(target=srv.handle_request, daemon=True)
    t.start()
    url = AUTH_URL + "?" + urllib.parse.urlencode({
        "response_type": "code", "client_id": cid, "redirect_uri": REDIRECT, "scope": SCOPES, "state": state,
        "code_challenge": challenge, "code_challenge_method": "S256"})
    print("Opening X in your browser. Make sure you're logged in as @%s, then click Authorize.\n"
          "If it doesn't open, visit:\n%s\n" % (expect, url), flush=True)
    webbrowser.open(url)
    t.join(timeout=300)
    srv.server_close()
    if got.get("state") != state or "code" not in got:
        sys.exit(f"No authorization received ({got.get('error_description') or got.get('error') or 'timed out'}).")
    r = requests.post(TOKEN_URL, auth=(cid, csec), timeout=30, data={
        "code": got["code"], "grant_type": "authorization_code", "redirect_uri": REDIRECT,
        "code_verifier": verifier, "client_id": cid})
    if not r.ok:
        sys.exit(f"Token exchange failed {r.status_code}: {r.text[:300]}")
    tok = r.json()
    who = requests.get("https://api.x.com/2/users/me", headers={"Authorization": f"Bearer {tok['access_token']}"}, timeout=30)
    if not who.ok:
        sys.exit(f"Authorized, but /users/me failed {who.status_code}: {who.text[:200]}")
    user = who.json()["data"]["username"]
    if user.lower() != expect:
        sys.exit(f"That authorized @{user}, not @{expect}. Log out of X, log in as @{expect}, and run setup again. Nothing was saved.")
    if "refresh_token" not in tok:
        sys.exit("X returned no refresh token (offline.access scope missing?). Nothing was saved.")
    for name, val in (("X_CLIENT_ID", cid), ("X_CLIENT_SECRET", csec), ("X_REFRESH_TOKEN_INIT", tok["refresh_token"]),
                      ("X_INIT_ID", secrets.token_hex(8))):
        _gh_secret(name, val)
    print(f"✓ Authorized @{user}. Saved X_CLIENT_ID, X_CLIENT_SECRET, X_REFRESH_TOKEN_INIT and X_INIT_ID to GitHub secrets.\n"
          f"Scopes granted: {tok.get('scope')}")


if __name__ == "__main__":
    if sys.argv[1:] == ["setup"]:
        setup()
    else:
        print(__doc__)
