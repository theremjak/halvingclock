"""Daily + milestone social posts for halvingclock.com (Bluesky, Nostr, X).

Compares today's site/state.json with yesterday's (downloaded from the live site before the build) and writes one post:
a milestone post when something notable happened, otherwise the daily "Day N" post. The clock image (site/og.png) is
attached on Bluesky and X; Nostr clients show it through the link preview.

A platform is skipped when its credentials are missing, so each can be switched on independently:
  Bluesky  BSKY_HANDLE, BSKY_APP_PASSWORD
  Nostr    NOSTR_NSEC  (nsec1… or 64-char hex)
  X        X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET
Usage:
  python social.py --prev prev_state.json            post (skips if yesterday's state has the same date)
  python social.py --prev prev_state.json --dry-run  print the post, send nothing
  python social.py --nostr-profile                   publish/refresh the Nostr profile (name, picture, NIP-05, Lightning)
  python social.py --nostr-keygen                    generate a new Nostr key pair (prints npub; nsec goes to a file)
"""
import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

HERE = Path(__file__).parent
SITE = HERE / "site"
CONFIG = json.loads((HERE / "config.json").read_text())
URL = (CONFIG.get("site_url") or "https://halvingclock.com").rstrip("/")
LINK = URL.replace("https://", "")
RELAYS = ["wss://relay.damus.io", "wss://nos.lol", "wss://relay.primal.net", "wss://relay.nostr.band", "wss://relay.snort.social",
          "wss://nostr.mom", "wss://offchain.pub", "wss://purplepag.es"]   # nostr.wine dropped: paid relay, refuses writes
ORD = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th", 5: "5th", 6: "6th"}


# ───────────────────────── composing ─────────────────────────

def fmt_usd(v):
    return f"${v:,.0f}"


def milestones(prev, s):
    """Notable changes between yesterday and today, most important first."""
    out = []
    if not prev:
        return out
    if s["cycle"] > prev["cycle"]:
        out.append(f"🟠 The halving is here. Cycle {s['cycle']} begins: the block reward just halved. Day 0 of the next four years.")
        return out
    if s.get("low") and prev.get("low") and s["low"] < prev["low"] - 0.5 and s["low_date"] == s["asof"]:
        out.append(f"📉 New cycle low: {fmt_usd(s['low'])}, {(s['low'] / s['peak'] - 1) * 100:+.0f}% from the {fmt_usd(s['peak'])} peak, on day {s['day']}. "
                   f"Past cycles bottomed on days {s['low_window'][0]}–{s['low_window'][1]}.")
    if s["peak"] > prev["peak"] + 0.5 and s["peak_date"] == s["asof"]:
        out.append(f"🚀 New cycle high: {fmt_usd(s['peak'])} on day {s['day']}.")
    lo, hi = s["low_window"]
    if prev["day"] < lo <= s["day"]:
        out.append(f"🎯 Day {s['day']}: entering the window where the last three cycles bottomed (days {lo}–{hi}).")
    if prev["day"] <= hi < s["day"]:
        out.append(f"⌛ Day {s['day']}: past the end of the historical low window (days {lo}–{hi}).")
    for t in (1000, 750, 500, 365, 300, 250, 200, 150, 100, 90, 60, 30, 14, 7, 3, 2, 1):
        if prev["days_to_halving"] > t >= s["days_to_halving"]:
            out.append(f"⏳ {t} day{'s' if t != 1 else ''} to Bitcoin's {ORD.get(s['cycle'] + 1, str(s['cycle'] + 1))} halving (≈{datetime.fromisoformat(s['next_halving']):%b %d, %Y}).")
            break
    marks = [m for m in list(range(200_000, 10_000 - 1, -10_000)) + [5_000, 2_016, 1_000, 500, 144, 100, 10]]
    for t in marks:
        if prev["remaining"] > t >= s["remaining"]:
            out.append(f"⛏️ Under {t:,} blocks to the next halving (block {s['next_height']:,}).")
            break
    return out


def daily_line(s):
    lo, hi = s["low_window"]
    if lo <= s["day"] <= hi:
        where = f"📍 Inside the historical low window (days {lo}–{hi})"
    elif s["day"] < lo:
        where = f"📍 {lo - s['day']} days until the historical low window"
    else:
        where = f"📍 {s['day'] - hi} days past the historical low window"
    return where


def compose(prev, s):
    ms = milestones(prev, s)
    stats = (f"{s['remaining']:,} blocks (~{s['days_to_halving']} days) to the next halving\n"
             f"BTC {fmt_usd(s['price'])} · {s['dd'] * 100:+.0f}% from the cycle peak")
    if ms:
        text = f"{ms[0]}\n\n{stats}\n{LINK}"
    else:
        text = (f"⏳ Day {s['day']} of Bitcoin's {ORD.get(s['cycle'], str(s['cycle']))} halving cycle\n"
                f"{stats}\n{daily_line(s)}\n{LINK}")
    alt = (f"The Halving Clock: day {s['day']} of cycle {s['cycle']}. A timeline of the cycle with the windows where past cycles peaked "
           f"and bottomed, today's position marked, and BTC {fmt_usd(s['price'])}, {s['dd'] * 100:+.0f}% from the cycle peak.")
    return text, alt, bool(ms)


# ───────────────────────── milestone → Reddit draft (opened as a GitHub issue by the workflow) ─────────────────────────

def reddit_draft(ms, s):
    """Write milestone_title.txt + milestone_body.md for a hand-posted Reddit comment. Reddit forbids bot posting in the
    subreddits that matter, so this only drafts; a person posts it."""
    head = ms[0]
    for e in ("📉 ", "🚀 ", "🎯 ", "⌛ ", "⏳ ", "⛏️ ", "🟠 "):
        head = head.replace(e, "")
    lo, hi = s["low_window"]
    pk_lo, pk_hi = s["pk_window"]
    short = head.split(". ")[0].replace(f", on day {s['day']}", "")   # first clause, without repeating the day
    title = f"Halving Clock milestone: {head.split(':')[0].split('.')[0][:80]} (day {s['day']})"
    comment = (f"Cycle-timing check, day {s['day']} since the {ORD.get(s['cycle'], s['cycle'])} halving: {head}\n\n"
               f"For context: the last three cycles peaked {pk_lo}–{pk_hi} days after their halving and bottomed {lo}–{hi} days after. "
               f"This cycle peaked on day {(datetime.fromisoformat(s['peak_date']) - datetime.fromisoformat(s['asof'])).days + s['day']} "
               f"({fmt_usd(s['peak'])}); BTC is {fmt_usd(s['price'])} now, {s['dd'] * 100:+.0f}% from that peak"
               + (f", and the low so far is {fmt_usd(s['low'])} ({(s['low'] / s['peak'] - 1) * 100:+.0f}%)." if s.get("low") else ".")
               + f" Next halving in about {s['days_to_halving']} days ({s['remaining']:,} blocks).\n\n"
               f"Full comparison (free, updates daily): {LINK}. Not a prediction: three data points, and the ETF era may have changed the rhythm.")
    body = (f"**Milestone detected on {s['asof']}:** {ms[0]}\n\n" + ("Also today: " + " · ".join(ms[1:]) + "\n\n" if len(ms) > 1 else "")
            + "### Suggested r/BitcoinMarkets Daily Discussion comment\n\nPaste as a comment in the pinned daily thread (not a standalone post):\n\n"
            + "```\n" + comment + "\n```\n\n"
            + "### If it's big enough for a standalone r/Bitcoin discussion post\n\n"
            + f"**Title:** Day {s['day']} of the cycle: {short[0].lower() + short[1:]}\n\n"
            + "Reuse the comment above as the body, check the sidebar rules first, and keep it to about one standalone post a month.\n\n"
            + "_Close this issue once posted (or if you skip it)._")
    return title, body


def email_alert(title, body):
    """Email the draft via Gmail SMTP (ALERT_SMTP_USER + ALERT_SMTP_APP_PASSWORD; ALERT_TO defaults to the sender)."""
    import smtplib
    from email.message import EmailMessage
    user, pw = os.environ.get("ALERT_SMTP_USER"), os.environ.get("ALERT_SMTP_APP_PASSWORD")
    if not (user and pw):
        return "skipped (no ALERT_SMTP_USER / ALERT_SMTP_APP_PASSWORD)"
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = title, f"Halving Clock <{user}>", os.environ.get("ALERT_TO") or user
    msg.set_content(body.replace("```", ""))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
        smtp.login(user, pw.replace(" ", ""))
        smtp.send_message(msg)
    return f"emailed {msg['To']}"


# ───────────────────────── Bluesky ─────────────────────────

def post_bluesky(text, img, alt):
    h, pw = os.environ.get("BSKY_HANDLE"), os.environ.get("BSKY_APP_PASSWORD")
    if not (h and pw):
        return "skipped (no BSKY_HANDLE / BSKY_APP_PASSWORD)"
    pds = "https://bsky.social/xrpc"
    sess = requests.post(f"{pds}/com.atproto.server.createSession", json={"identifier": h, "password": pw}, timeout=30)
    sess.raise_for_status()
    sess = sess.json()
    auth = {"Authorization": f"Bearer {sess['accessJwt']}"}
    blob = requests.post(f"{pds}/com.atproto.repo.uploadBlob", data=img.read_bytes(),
                         headers={**auth, "Content-Type": "image/png"}, timeout=60)
    blob.raise_for_status()
    b = text.encode("utf-8")
    i = b.rfind(LINK.encode("utf-8"))
    record = {"$type": "app.bsky.feed.post", "text": text, "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
              "langs": ["en"],
              "embed": {"$type": "app.bsky.embed.images", "images": [{"alt": alt[:1000], "image": blob.json()["blob"],
                                                                     "aspectRatio": {"width": 1200, "height": 630}}]}}
    if i >= 0:
        record["facets"] = [{"index": {"byteStart": i, "byteEnd": i + len(LINK.encode("utf-8"))},
                             "features": [{"$type": "app.bsky.richtext.facet#link", "uri": URL + "/"}]}]
    r = requests.post(f"{pds}/com.atproto.repo.createRecord", headers=auth, timeout=30,
                      json={"repo": sess["did"], "collection": "app.bsky.feed.post", "record": record})
    r.raise_for_status()
    return f"posted {r.json()['uri']}"


# ───────────────────────── Nostr ─────────────────────────

CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


def _polymod(values):
    gen = [0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3]
    chk = 1
    for v in values:
        top = chk >> 25
        chk = (chk & 0x1FFFFFF) << 5 ^ v
        for i in range(5):
            chk ^= gen[i] if ((top >> i) & 1) else 0
    return chk


def _convertbits(data, frm, to, pad=True):
    acc, bits, ret, maxv = 0, 0, [], (1 << to) - 1
    for v in data:
        acc = (acc << frm) | v
        bits += frm
        while bits >= to:
            bits -= to
            ret.append((acc >> bits) & maxv)
    if pad and bits:
        ret.append((acc << (to - bits)) & maxv)
    return ret


def bech32_encode(hrp, data8):
    data = _convertbits(data8, 8, 5)
    values = [ord(x) >> 5 for x in hrp] + [0] + [ord(x) & 31 for x in hrp] + data
    pm = _polymod(values + [0] * 6) ^ 1
    return hrp + "1" + "".join(CHARSET[d] for d in data + [(pm >> 5 * (5 - i)) & 31 for i in range(6)])


def bech32_decode(s):
    hrp, _, rest = s.lower().rpartition("1")
    data = [CHARSET.find(c) for c in rest]
    if _polymod([ord(x) >> 5 for x in hrp] + [0] + [ord(x) & 31 for x in hrp] + data) != 1:
        raise ValueError("bad bech32 checksum")
    return hrp, bytes(_convertbits(data[:-6], 5, 8, pad=False))


def nostr_keys():
    from coincurve import PrivateKey, PublicKeyXOnly
    raw = os.environ.get("NOSTR_NSEC", "").strip()
    if not raw:
        return None
    sk = bech32_decode(raw)[1] if raw.startswith("nsec") else bytes.fromhex(raw)
    return PrivateKey(sk), PublicKeyXOnly.from_secret(sk).format().hex()


def nostr_event(kind, content, tags=()):
    keys = nostr_keys()
    if keys is None:
        return None
    sk, pub = keys
    created = int(time.time())
    ser = json.dumps([0, pub, created, kind, list(tags), content], separators=(",", ":"), ensure_ascii=False)
    eid = hashlib.sha256(ser.encode("utf-8")).digest()
    return {"id": eid.hex(), "pubkey": pub, "created_at": created, "kind": kind, "tags": list(tags), "content": content,
            "sig": sk.sign_schnorr(eid).hex()}


async def _publish(ev):
    import websockets
    ok = []

    async def one(relay):
        try:
            async with websockets.connect(relay, open_timeout=10, close_timeout=5) as ws:
                await ws.send(json.dumps(["EVENT", ev]))
                for _ in range(5):
                    msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
                    if msg[0] == "OK" and msg[1] == ev["id"]:
                        if msg[2]:
                            ok.append(relay)
                        return
        except Exception:
            return
    await asyncio.gather(*(one(r) for r in RELAYS))
    return ok


def post_nostr(text):
    ev = nostr_event(1, text, tags=[["r", URL + "/"], ["t", "bitcoin"], ["t", "halving"]])
    if ev is None:
        return "skipped (no NOSTR_NSEC)"
    ok = asyncio.run(_publish(ev))
    if not ok:
        raise RuntimeError("no relay accepted the note")
    return f"posted note {bech32_encode('note', bytes.fromhex(ev['id']))} to {len(ok)}/{len(RELAYS)} relays"


def nostr_profile():
    meta = {"name": "halvingclock", "display_name": "The Halving Clock", "website": URL,
            "about": "Where Bitcoin sits in its halving cycle, updated daily: day count, past cycle peaks and lows, and a live "
                     f"countdown to the next halving. Free and ad-free at {LINK}. Not financial advice.",
            "picture": f"{URL}/brand/avatar-400.png", "nip05": f"halvingclock@{LINK}"}
    if CONFIG.get("lightning"):
        meta["lud16"] = CONFIG["lightning"]
    ev = nostr_event(0, json.dumps(meta, ensure_ascii=False))
    if ev is None:
        sys.exit("NOSTR_NSEC not set")
    ok = asyncio.run(_publish(ev))
    print(f"profile published to {len(ok)}/{len(RELAYS)} relays")


def nostr_keygen(out):
    from coincurve import PrivateKey, PublicKeyXOnly
    sk = PrivateKey()
    pub = PublicKeyXOnly.from_secret(sk.secret).format()
    out = Path(out).expanduser()
    out.write_text(f"nsec: {bech32_encode('nsec', sk.secret)}\nnpub: {bech32_encode('npub', pub)}\npubkey hex: {pub.hex()}\n")
    out.chmod(0o600)
    print(f"npub: {bech32_encode('npub', pub)}\npubkey hex: {pub.hex()}\nprivate key saved to {out} (mode 600)")


# ───────────────────────── X ─────────────────────────

def x_auth():
    keys = [(os.environ.get(k) or "").strip() for k in ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET")]
    if not all(keys):
        return None
    from requests_oauthlib import OAuth1
    return OAuth1(*keys)


def x_whoami():
    """Which account do the X tokens belong to? Refuse to post if it isn't config.json's "twitter" handle."""
    auth = x_auth()
    if auth is None:
        return None
    r = requests.get("https://api.x.com/2/users/me", auth=auth, timeout=30)
    if not r.ok:
        raise RuntimeError(f"X {r.status_code}: {r.text[:300]}")
    return r.json()["data"]["username"]


def x_diagnose():
    """Print safe facts about the X keys (lengths/shape, the public user id inside the access token) and how three
    endpoints answer. Never prints a key."""
    names = ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET")
    vals = {k: (os.environ.get(k) or "").strip() for k in names}
    expect = {"X_API_KEY": "~25 chars", "X_API_SECRET": "~50 chars", "X_ACCESS_TOKEN": "~50 chars, '<userid>-<…>'", "X_ACCESS_SECRET": "~45 chars"}
    for k, v in vals.items():
        print(f"{k:16s} length {len(v):3d} (expected {expect[k]}) | contains '-': {'-' in v} | "
              f"{'starts with digits: user id ' + v.split('-')[0] if k == 'X_ACCESS_TOKEN' and v.split('-')[0].isdigit() else ''}")
    auth = x_auth()
    if auth is None:
        return print("missing keys")
    for url in ("https://api.x.com/2/users/me", "https://api.twitter.com/2/users/me",
                "https://api.twitter.com/1.1/account/verify_credentials.json?skip_status=true"):
        r = requests.get(url, auth=auth, timeout=30)
        body = r.text[:300].replace("\n", " ")
        print(f"{r.status_code} {url}\n    {body}")


def post_x(text, img):
    auth = x_auth()
    if auth is None:
        return "skipped (no X_* keys)"
    want = (CONFIG.get("twitter") or "").lstrip("@").lower()
    who = x_whoami()
    if want and who.lower() != want:
        raise RuntimeError(f"X tokens belong to @{who}, not @{want}; refusing to post")
    media_id = None
    r = requests.post("https://api.x.com/2/media/upload", auth=auth, timeout=60,
                      files={"media": ("og.png", img.read_bytes(), "image/png")}, data={"media_category": "tweet_image"})
    if r.ok:
        media_id = (r.json().get("data") or {}).get("id")
    else:                                           # fall back to the v1.1 upload endpoint
        r1 = requests.post("https://upload.twitter.com/1.1/media/upload.json", auth=auth, files={"media": img.read_bytes()}, timeout=60)
        if r1.ok:
            media_id = r1.json().get("media_id_string")
    body = {"text": text}
    if media_id:
        body["media"] = {"media_ids": [media_id]}
    r = requests.post("https://api.x.com/2/tweets", auth=auth, json=body, timeout=30)
    if not r.ok:
        raise RuntimeError(f"X {r.status_code}: {r.text[:300]}")
    return f"posted https://x.com/i/status/{r.json()['data']['id']}" + ("" if media_id else " (text only; image upload failed)")


# ───────────────────────── main ─────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prev", help="yesterday's state.json (downloaded from the live site before the build)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="post even if yesterday's state has today's date")
    ap.add_argument("--nostr-profile", action="store_true")
    ap.add_argument("--nostr-keygen", metavar="FILE")
    ap.add_argument("--test-alert", action="store_true", help="email a sample milestone draft (checks the Gmail setup)")
    ap.add_argument("--x-diagnose", action="store_true")
    ap.add_argument("--only", choices=["bluesky", "nostr", "x"], help="post to just this platform (with --force for a test post)")
    a = ap.parse_args()
    if a.nostr_keygen:
        return nostr_keygen(a.nostr_keygen)
    if a.nostr_profile:
        return nostr_profile()
    if a.x_diagnose:
        return x_diagnose()
    if a.test_alert:
        st = json.loads((SITE / "state.json").read_text())
        t, b = reddit_draft([f"🧪 Test alert: this is what a milestone email looks like (day {st['day']})."], st)
        return print("Test alert:", email_alert("[TEST] " + t, b))
    s = json.loads((SITE / "state.json").read_text())
    prev = None
    if a.prev and Path(a.prev).exists():
        try:
            prev = json.loads(Path(a.prev).read_text())
        except json.JSONDecodeError:
            prev = None
    if prev and prev.get("posted_for") == s["asof"] and not a.force:
        print(f"already posted for {s['asof']}; nothing to do")
        return
    base = (prev or {}).get("posted_state") or prev   # compare with the numbers at the LAST POST, not the last rebuild
    text, alt, is_milestone = compose(base, s)
    if is_milestone and not a.dry_run:
        try:
            print("Milestone alert:", email_alert(*reddit_draft(milestones(base, s), s)))
        except Exception as e:
            print(f"Milestone alert: FAILED {e}")
    elif is_milestone:
        print("(dry run) milestone alert would be emailed:\n" + reddit_draft(milestones(base, s), s)[1][:600])
    print(("MILESTONE " if is_milestone else "DAILY ") + f"post ({len(text)} chars):\n{text}\n")
    if a.dry_run:
        return
    img = SITE / "og.png"
    failures, sent = 0, 0
    for name, fn in (("Bluesky", lambda: post_bluesky(text, img, alt)), ("Nostr", lambda: post_nostr(text)), ("X", lambda: post_x(text, img))):
        if a.only and name.lower() != a.only:
            continue
        try:
            res = fn()
            print(f"{name}: {res}")
            sent += res.startswith("posted")
        except Exception as e:
            failures += 1
            print(f"{name}: FAILED {e}")
    if sent:                                          # record the post in the state that is about to be deployed
        s["posted_for"] = s["asof"]
        s["posted_state"] = {k: v for k, v in s.items() if k not in ("posted_for", "posted_state")}
        (SITE / "state.json").write_text(json.dumps(s, indent=1))
    if failures:
        sys.exit(1)                                   # surfaces in the Actions run (and GitHub's failure email)


if __name__ == "__main__":
    main()
