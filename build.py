"""Build halvingclock.com — a static page regenerated daily.

Data (no API keys, no non-commercial licences):
  mempool.space   block heights and exact halving block times, daily hash rate + difficulty adjustments,
                  per-block miner rewards (subsidy + fees), current epoch timing
  Bitstamp        daily BTC/USD closes from Aug 2011 (public OHLC API)
  mempool.space   weekly historical price for Jul 2010 – Aug 2011 (pre-Bitstamp; only used for the 2011 context)

Outputs site/: index.html (template + data), og.png (social preview), favicon.svg, robots.txt, sitemap.xml, _headers.
Usage:  python build.py            (network fetch, then build)
        python build.py --offline  (rebuild from cache/ only)
"""
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

HERE = Path(__file__).parent
CACHE = HERE / "cache"
SITE = HERE / "site"
CONFIG = json.loads((HERE / "config.json").read_text())
MP = "https://mempool.space/api"
UA = {"User-Agent": "halvingclock.com daily build"}
HALVING_INTERVAL = 210_000


def get(url, **params):
    for attempt in range(5):
        try:
            r = requests.get(url, params=params or None, headers=UA, timeout=90)
            if r.status_code == 200:
                return r
        except requests.RequestException:
            pass
        time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"failed: {url}")


# ───────────── fetch ─────────────

def fetch():
    CACHE.mkdir(exist_ok=True)
    (CACHE / "hash.json").write_text(get(f"{MP}/v1/mining/hashrate/all").text)
    (CACHE / "rewards.json").write_text(get(f"{MP}/v1/mining/blocks/rewards/all").text)
    (CACHE / "hp.json").write_text(get(f"{MP}/v1/historical-price", currency="USD").text)
    (CACHE / "diffadj.json").write_text(get(f"{MP}/v1/difficulty-adjustment").text)
    tip = int(get(f"{MP}/blocks/tip/height").text)
    blocks = {"tip": tip}
    for h in range(HALVING_INTERVAL, tip + 1, HALVING_INTERVAL):
        bh = get(f"{MP}/block-height/{h}").text.strip()
        blocks[str(h)] = get(f"{MP}/block/{bh}").json()["timestamp"]
    tip_hash = get(f"{MP}/blocks/tip/hash").text.strip()
    blocks["tip_time"] = get(f"{MP}/block/{tip_hash}").json()["timestamp"]
    (CACHE / "blocks.json").write_text(json.dumps(blocks))
    # Bitstamp daily closes (1000 per call)
    rows, start, now = [], 1293840000, time.time()
    while start < now:
        d = get("https://www.bitstamp.net/api/v2/ohlc/btcusd/", step=86400, limit=1000, start=start).json()["data"]["ohlc"]
        if not d:
            break
        rows += d
        start = int(d[-1]["timestamp"]) + 86400
        time.sleep(0.5)
    b = pd.DataFrame(rows).astype({"timestamp": int, "close": float})
    b["date"] = pd.to_datetime(b.timestamp, unit="s")
    b.drop_duplicates("date")[["date", "close"]].to_csv(CACHE / "bitstamp.csv", index=False)


# ───────────── load ─────────────

def load():
    b = pd.read_csv(CACHE / "bitstamp.csv", parse_dates=["date"]).set_index("date").close
    hp = pd.DataFrame(json.loads((CACHE / "hp.json").read_text())["prices"])
    hp["date"] = pd.to_datetime(hp.time, unit="s").dt.normalize()
    early = hp[hp.date < b.index.min()].groupby("date").USD.last()
    early = early[early > 0].resample("D").last().interpolate("time")  # weekly → daily line, 2010–11 only
    px = pd.concat([early, b]).sort_index()
    px = px[~px.index.duplicated(keep="last")]
    h = json.loads((CACHE / "hash.json").read_text())
    hr = pd.DataFrame(h["hashrates"])
    hr = hr.assign(date=pd.to_datetime(hr.timestamp, unit="s").dt.normalize()).groupby("date").avgHashrate.mean()
    hr = hr[hr > 0] / 1e12                                                   # H/s → TH/s
    rw = pd.DataFrame(json.loads((CACHE / "rewards.json").read_text()))
    rw["date"] = pd.to_datetime(rw.timestamp, unit="s").dt.normalize()
    rw = rw.groupby("date").agg(avgRewards=("avgRewards", "mean"), avgHeight=("avgHeight", "last"))
    blocks = json.loads((CACHE / "blocks.json").read_text())
    diffadj = json.loads((CACHE / "diffadj.json").read_text())
    return px, hr, rw, blocks, diffadj


# ───────────── analysis (same definitions as the research version) ─────────────

def analyse(px, hr, rw, blocks, diffadj):
    tip, tip_time = blocks["tip"], pd.Timestamp(blocks["tip_time"], unit="s")
    halv = [pd.Timestamp(blocks[str(h)], unit="s") for h in range(HALVING_INTERVAL, tip + 1, HALVING_INTERVAL)]
    halv_d = [h.normalize() for h in halv]
    # next halving: blocks remaining at the pace since the last halving, cross-checked with the current epoch pace
    next_height = (tip // HALVING_INTERVAL + 1) * HALVING_INTERVAL
    remaining = next_height - tip
    secs_per_block = (tip_time - halv[-1]).total_seconds() / (tip - HALVING_INTERVAL * len(halv))
    next_h = tip_time + pd.Timedelta(seconds=remaining * secs_per_block)
    today = px.index[-1]
    bounds = halv_d + [next_h.normalize()]

    cycles = []
    for k in range(len(halv_d)):
        h, nh = bounds[k], bounds[k + 1]
        seg = px[(px.index >= h) & (px.index <= min(h + pd.Timedelta(days=730), nh, today))]
        pk = seg.idxmax()
        after = px[(px.index > pk) & (px.index < min(nh, today + pd.Timedelta(days=1)))]
        c = dict(n=k + 1, halving=h, next_halving=nh, complete=bool(nh <= today), halving_price=float(px.asof(h)),
                 peak_date=pk, peak=float(seg.max()), peak_days=int((pk - h).days), peak_mult=float(seg.max() / px.asof(h)))
        if len(after):
            lo = after.idxmin()
            c.update(low_date=lo, low=float(after.min()), low_days=int((lo - h).days), peak_to_low_days=int((lo - pk).days),
                     drawdown=float(after.min() / seg.max() - 1))
        hs = hr[(hr.index >= h) & (hr.index <= min(nh, today))].rolling(14, min_periods=7).mean().dropna()
        ps = px[(px.index >= h) & (px.index <= min(nh, today))]
        c["hash_mult"] = float(hs.iloc[-1] / hs.iloc[0])
        c["price_mult_cycle"] = float(ps.iloc[-1] / ps.iloc[0])
        c["hash_doublings"] = float(np.log2(c["hash_mult"]))
        c["per_doubling"] = float(c["price_mult_cycle"] ** (1 / c["hash_doublings"])) if c["hash_mult"] > 1 else None
        c["elasticity"] = float(np.log(c["price_mult_cycle"]) / np.log(c["hash_mult"])) if c["hash_mult"] > 1 else None
        cycles.append(c)
    comp = [c for c in cycles if c["complete"]]
    cur = cycles[-1]
    fit = lambda y: np.polyfit(np.arange(1, len(y) + 1), y, 1)
    pk_days = np.array([c["peak_days"] for c in comp])
    lo_days = np.array([c["low_days"] for c in comp])
    p2l = np.array([c["peak_to_low_days"] for c in comp])
    dds = np.array([c["drawdown"] for c in comp])
    dd_trend = float(np.polyval(fit(dds), len(comp) + 1))
    l2p = np.array([cycles[k + 1]["peak"] / cycles[k]["low"] for k in range(len(cycles) - 1)])
    ll = np.log(l2p)
    l2p_next = float(np.exp(ll[-1] * np.exp(np.mean(np.diff(np.log(ll))))))
    low_trend_price = cur["peak"] * (1 + dd_trend)
    all_pk = np.r_[pk_days, cur["peak_days"]]
    proj = dict(
        low_window=[halv_d[-1] + pd.Timedelta(days=int(lo_days.min())), halv_d[-1] + pd.Timedelta(days=int(lo_days.max()))],
        low_trend=halv_d[-1] + pd.Timedelta(days=int(round(np.polyval(fit(lo_days), len(comp) + 1)))),
        low_from_peak=[cur["peak_date"] + pd.Timedelta(days=int(p2l.min())), cur["peak_date"] + pd.Timedelta(days=int(p2l.max()))],
        next_halving=next_h,
        next_peak_window=[next_h + pd.Timedelta(days=int(all_pk.min())), next_h + pd.Timedelta(days=int(all_pk.max()))],
        next_peak_cluster=[next_h + pd.Timedelta(days=int(np.sort(all_pk)[1])), next_h + pd.Timedelta(days=int(all_pk.max()))],
        dd_range=[float(dds.min()), float(dds.max())], dd_trend=dd_trend, low_price_trend=low_trend_price,
        low_to_peak=l2p.tolist(), low_to_peak_next=l2p_next,
        next_peak_from_low=[low_trend_price * l2p_next, cur.get("low", px.iloc[-1]) * l2p_next],
    )
    # hashprice: USD miner revenue per PH/s per day (avg reward per block × blocks that day × price ÷ hash rate)
    blk = rw.avgHeight.diff().clip(lower=0)
    rev_usd = (rw.avgRewards / 1e8) * blk * px.reindex(rw.index)
    hp = (rev_usd / (hr.reindex(rw.index) / 1000)).astype(float)
    hp = hp[np.isfinite(hp)]
    hp = hp[hp > 0].rolling(30, min_periods=15).mean().dropna()
    hp_year = hp.groupby(hp.index.year).mean()
    years = (px.groupby(px.index.year).last() / px.groupby(px.index.year).last().shift(1) - 1).dropna()
    wk = px.resample("W").last()
    iso = lambda d: None if d is None else pd.Timestamp(d).strftime("%Y-%m-%d")
    pre = px[px.index < halv_d[0]]
    pre_pk = pre[pre.index < "2011-09-01"].idxmax()
    return dict(
        asof=iso(today), built=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), price=float(px.iloc[-1]),
        tip=tip, tip_time=int(blocks["tip_time"]), next_height=next_height, remaining=remaining,
        secs_per_block=secs_per_block, blocks_per_day=86400 / secs_per_block,
        next_halving_ts=int(next_h.timestamp()), epoch=dict(progress=diffadj.get("progressPercent"), change=diffadj.get("difficultyChange"),
                                                            retarget_ts=int(diffadj.get("estimatedRetargetDate", 0) / 1000)),
        halvings=[iso(h) for h in halv_d], halving_ts=[int(h.timestamp()) for h in halv], next_halving=iso(next_h),
        pre=dict(peak_date=iso(pre_pk), peak=float(pre.max()), low_date=iso(pre[pre.index > pre_pk].idxmin()), low=float(pre[pre.index > pre_pk].min())),
        cycles=[{k: (iso(v) if isinstance(v, pd.Timestamp) else v) for k, v in c.items()} for c in cycles],
        cur_dd=float(px.iloc[-1] / cur["peak"] - 1),
        proj={k: ([iso(x) if isinstance(x, pd.Timestamp) else x for x in v] if isinstance(v, list) else iso(v) if isinstance(v, pd.Timestamp) else v)
              for k, v in proj.items()},
        weekly=dict(d=[iso(x) for x in wk.index], p=[float(f"{v:.6g}") for v in wk.values]),
        hashprice=dict(d=[iso(x) for x in hp.resample("W").last().dropna().index], v=[float(f"{v:.5g}") for v in hp.resample("W").last().dropna().values]),
        hp_year={str(int(k)): float(v) for k, v in hp_year.items() if k >= 2014},
        years={str(int(y)): float(v) for y, v in years.items()},
        config={k: CONFIG.get(k) for k in ("site_url", "kofi", "lightning", "twitter", "nostr")},
    )


# ───────────── site ─────────────

def og_image(d, path):
    from PIL import Image, ImageDraw, ImageFont
    W, H = 1200, 630
    img = Image.new("RGB", (W, H), (13, 15, 19))
    g = ImageDraw.Draw(img)
    f = lambda s: ImageFont.load_default(size=s)
    cur = d["cycles"][-1]
    day = (pd.Timestamp(d["asof"]) - pd.Timestamp(cur["halving"])).days
    span = (pd.Timestamp(d["next_halving"]) - pd.Timestamp(cur["halving"])).days
    g.text((64, 56), "THE HALVING CLOCK", font=f(30), fill=(155, 163, 177))
    g.text((64, 110), f"Day {day} of cycle {cur['n']}", font=f(84), fill=(233, 236, 241))
    g.text((64, 220), f"Next halving ~{pd.Timestamp(d['next_halving']):%b %d, %Y} · {d['remaining']:,} blocks to go", font=f(34), fill=(155, 163, 177))
    x0, x1, y = 64, W - 64, 360
    X = lambda dd: x0 + (x1 - x0) * dd / span
    past = d["cycles"][:-1]
    pk = [c["peak_days"] for c in past]; lw = [c["low_days"] for c in past if c.get("low_days")]
    g.rectangle([X(min(pk)), y - 26, X(max(pk)), y + 26], fill=(20, 40, 66))
    g.rectangle([X(min(lw)), y - 26, X(max(lw)), y + 26], fill=(60, 26, 24))
    g.line([x0, y, x1, y], fill=(52, 58, 68), width=6)
    g.line([x0, y, X(day), y], fill=(217, 119, 6), width=6)
    g.ellipse([X(day) - 13, y - 13, X(day) + 13, y + 13], fill=(217, 119, 6))
    g.text((X(min(pk)), y + 40), "past peaks", font=f(24), fill=(120, 160, 220))
    g.text((X(min(lw)), y + 40), "past lows", font=f(24), fill=(230, 120, 110))
    g.text((64, 470), f"BTC ${d['price']:,.0f} · {d['cur_dd'] * 100:+.0f}% from the cycle peak", font=f(34), fill=(233, 236, 241))
    g.text((64, 540), (d["config"].get("site_url") or "").replace("https://", ""), font=f(28), fill=(217, 119, 6))
    img.save(path, optimize=True)


def state(d):
    """Small daily snapshot the social poster compares against yesterday's (milestones = changes between the two)."""
    cur, past = d["cycles"][-1], d["cycles"][:-1]
    day = (pd.Timestamp(d["asof"]) - pd.Timestamp(cur["halving"])).days
    return dict(asof=d["asof"], cycle=cur["n"], day=day, price=round(d["price"], 2), peak=cur["peak"], peak_date=cur["peak_date"],
                low=cur.get("low"), low_date=cur.get("low_date"), dd=round(d["cur_dd"], 4), remaining=d["remaining"],
                next_height=d["next_height"], next_halving=d["next_halving"],
                days_to_halving=(pd.Timestamp(d["next_halving"]) - pd.Timestamp(d["asof"])).days,
                pk_window=[min(c["peak_days"] for c in past), max(c["peak_days"] for c in past)],
                low_window=[min(c["low_days"] for c in past if c.get("low_days")), max(c["low_days"] for c in past if c.get("low_days"))],
                low_from_peak=d["proj"]["low_from_peak"])


def build(d):
    SITE.mkdir(exist_ok=True)
    tpl = (HERE / "template.html").read_text()
    blob = json.dumps(d, separators=(",", ":"), allow_nan=False).replace("</", "<\\/")
    url = (CONFIG.get("site_url") or "").rstrip("/")
    cur = d["cycles"][-1]
    day = (pd.Timestamp(d["asof"]) - pd.Timestamp(cur["halving"])).days
    desc = (f"Day {day} of Bitcoin's halving cycle {cur['n']}. Where past cycles peaked and bottomed, where this one stands, "
            f"and a live countdown to the next halving (≈{pd.Timestamp(d['next_halving']):%b %Y}). Updated daily.")
    analytics = ""
    if CONFIG.get("cf_analytics_token"):
        analytics = (f"<script defer src='https://static.cloudflareinsights.com/beacon.min.js' "
                     f"data-cf-beacon='{{\"token\": \"{CONFIG['cf_analytics_token']}\"}}'></script>")
    html = (tpl.replace("/*DATA*/", blob).replace("{{DESC}}", desc).replace("{{URL}}", url)
               .replace("{{BUILT}}", d["built"]).replace("{{ANALYTICS}}", analytics))
    (SITE / "index.html").write_text(html)
    og_image(d, SITE / "og.png")
    (SITE / "favicon.svg").write_text(
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'><circle cx='32' cy='32' r='29' fill='none' stroke='#d97706' stroke-width='6'/>"
        "<path d='M32 14v19l12 8' stroke='#d97706' stroke-width='6' fill='none' stroke-linecap='round'/></svg>")
    (SITE / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {url}/sitemap.xml\n")
    (SITE / "sitemap.xml").write_text(f"<?xml version='1.0' encoding='UTF-8'?><urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>"
                                      f"<url><loc>{url}/</loc><lastmod>{d['asof']}</lastmod><changefreq>daily</changefreq></url></urlset>\n")
    (SITE / "_headers").write_text("/\n  Cache-Control: public, max-age=0, must-revalidate\n/og.png\n  Cache-Control: public, max-age=3600\n"
                                   "/state.json\n  Cache-Control: public, max-age=0, must-revalidate\n  Access-Control-Allow-Origin: *\n"
                                   "/.well-known/nostr.json\n  Access-Control-Allow-Origin: *\n")
    # identity verification: Nostr NIP-05 (halvingclock@halvingclock.com) and Bluesky domain handle (@halvingclock.com)
    wk = SITE / ".well-known"
    wk.mkdir(exist_ok=True)
    if CONFIG.get("nostr_pubkey"):
        (wk / "nostr.json").write_text(json.dumps({"names": {"halvingclock": CONFIG["nostr_pubkey"], "_": CONFIG["nostr_pubkey"]}}))
    if CONFIG.get("bluesky_did"):
        (wk / "atproto-did").write_text(CONFIG["bluesky_did"].strip())
    st = state(d)
    prev_path = HERE / "prev_state.json"                 # yesterday's live state (downloaded by the workflow), if present
    if prev_path.exists():
        try:
            prev = json.loads(prev_path.read_text())
            st["posted_for"], st["posted_state"] = prev.get("posted_for"), prev.get("posted_state")
        except json.JSONDecodeError:
            pass
    (SITE / "state.json").write_text(json.dumps(st, indent=1))
    bd = SITE / "brand"                                  # profile pictures for the social accounts
    bd.mkdir(exist_ok=True)
    for size in (400, 1000):
        src = HERE / "brand" / f"halvingclock-avatar-{size}.png"
        if src.exists():
            (bd / f"avatar-{size}.png").write_bytes(src.read_bytes())
    print(f"built site/ · day {day} of cycle {cur['n']} · BTC ${d['price']:,.0f} · next halving ≈ {d['next_halving']} "
          f"({d['remaining']:,} blocks) · index.html {len(html) / 1e3:.0f} KB")


if __name__ == "__main__":
    if "--offline" not in sys.argv:
        fetch()
    build(analyse(*load()))
