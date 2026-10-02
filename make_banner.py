"""Profile banner (1500x500) for X / Bluesky / Nostr: the four halving cycles overlaid, price as a multiple of the halving-day price.

    python make_banner.py            → brand/halvingclock-banner.png   (needs a prior build for cache/ + site/index.html)

Timeless on purpose (no countdown or price text) — the platforms' banner APIs need OAuth1 or manual upload, so it isn't refreshed daily.
Layout respects the crops: X puts the avatar over the bottom-left and trims top/bottom on phones, so text sits top-left and the
chart's busy part is centre/right.
"""
import json
import re
from io import BytesIO
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib import font_manager
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).parent
W, H = 1500, 500
GROUND, INK, MUTED, FAINT, RULE = "#0d0f13", "#e9ecf1", "#9ba3b1", "#6c7483", "#272c35"
COLS = ["#3987e5", "#199e70", "#9085e9", "#d97706"]          # dark-theme --c1 --c2 --c3 --now, as on the site
font_manager.fontManager.addfont(str(HERE / "brand" / "fonts" / "JetBrainsMono.ttf"))
MONO = font_manager.FontProperties(fname=str(HERE / "brand" / "fonts" / "JetBrainsMono.ttf"), size=13)

html = (HERE / "site" / "index.html").read_text()
D = json.loads(re.search(r'<script id="data" type="application/json">(.*?)</script>', html, re.S).group(1))
px = pd.read_parquet(HERE / "cache" / "bitstamp.parquet")["close"]
px.index = pd.to_datetime(px.index)
cycles = D["cycles"]
past = cycles[:-1]

# ── chart (matplotlib, transparent, composited onto the ground) ──
dpi = 100
fig = plt.figure(figsize=(W / dpi, H / dpi), dpi=dpi)
ax = fig.add_axes([0.30, 0.17, 0.66, 0.70])                 # leaves the left third for the title / avatar
fig.patch.set_alpha(0)
ax.set_facecolor("none")
span = 1460
pk = [c["peak_days"] for c in past]
lw = [c["low_days"] for c in past]
ax.axvspan(min(pk), max(pk), color="#3987e5", alpha=.10, lw=0)
ax.axvspan(min(lw), max(lw), color="#f06a5e", alpha=.09, lw=0)
for i, c in enumerate(cycles):
    h0 = pd.Timestamp(c["halving"])
    end = pd.Timestamp(c["next_halving"]) if c["complete"] else px.index[-1]
    s = px[(px.index >= h0) & (px.index <= end)]
    x = (s.index - h0).days
    y = s / s.iloc[0]
    cur = i == len(cycles) - 1
    ax.plot(x, y, color=COLS[i], lw=3.2 if cur else 1.9, alpha=1 if cur else .85, solid_capstyle="round", zorder=3 if cur else 2)
    if cur:
        ax.scatter([x[-1]], [y.iloc[-1]], s=70, color=COLS[i], zorder=4, edgecolor=GROUND, linewidth=2)
    ax.annotate(f"{h0:%Y} · now" if cur else f"{h0:%Y}", (x[-1], y.iloc[-1]), xytext=(9 if cur else 6, 0), textcoords="offset points",
                color=COLS[i], va="center", fontproperties=MONO)
ax.set_yscale("log")
ax.set_xlim(0, span + 60)
ax.set_ylim(0.35, 160)
ax.axhline(1, color=RULE, lw=1, zorder=1)
for sp in ax.spines.values():
    sp.set_visible(False)
ax.set_xticks([])
ax.set_yticks([])
ax.minorticks_off()
ax.tick_params(which="both", length=0)
# label the shaded windows in place (a legend swatch read as one of the cycle lines)
for lo, hi, lab, col in ((min(pk), max(pk), "past peaks", "#7fb0ee"), (min(lw), max(lw), "past lows", "#f3a39b")):
    ax.text((lo + hi) / 2, 0.42, lab, ha="center", va="bottom", color=col, fontproperties=MONO, alpha=.9)
buf = BytesIO()
fig.savefig(buf, format="png", dpi=dpi, transparent=True)
plt.close(fig)
chart = Image.open(buf).convert("RGBA")

img = Image.new("RGBA", (W, H), GROUND)
img.alpha_composite(chart)
g = ImageDraw.Draw(img)


def font(name, size, weight):
    f = ImageFont.truetype(str(HERE / "brand" / "fonts" / name), size)
    try:
        f.set_variation_by_axes([weight])
    except OSError:
        pass
    return f


kick = font("JetBrainsMono.ttf", 17, 600)
title = font("SchibstedGrotesk.ttf", 58, 800)
sub = font("SchibstedGrotesk.ttf", 23, 500)
mono = font("JetBrainsMono.ttf", 18, 500)
X0 = 64
g.text((X0, 92), "BITCOIN HALVING CYCLES", font=kick, fill=FAINT)
g.text((X0, 120), "The Halving", font=title, fill=INK)
g.text((X0, 182), "Clock", font=title, fill=COLS[3])
g.text((X0, 262), "Four cycles, one rhythm.", font=sub, fill=MUTED)
g.text((X0, 294), "Updated daily.", font=sub, fill=MUTED)

url = "halvingclock.com"
g.text((W - 64 - g.textlength(url, font=mono), 60), url, font=mono, fill=COLS[3])

out = HERE / "brand" / "halvingclock-banner.png"
img.convert("RGB").save(out, optimize=True)
print(f"wrote {out} ({W}x{H})")
