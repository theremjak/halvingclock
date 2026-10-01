"""Regenerate the hand-posted launch drafts (Show HN + Reddit) with today's numbers.

    python launch_posts.py          reads https://halvingclock.com/state.json (falls back to site/state.json)
Writes launch/show_hn.md and launch/reddit.md. Run it right before posting so every number is current.
"""
import json
from datetime import date
from pathlib import Path

import requests

HERE = Path(__file__).parent
OUT = HERE / "launch"
ORD = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th", 5: "5th"}


def load():
    try:
        r = requests.get("https://halvingclock.com/state.json", timeout=20)
        r.raise_for_status()
        if "past" in r.json():                      # older deployments lack the cycle-history fields
            return r.json(), "halvingclock.com"
    except Exception:
        pass
    return json.loads((HERE / "site" / "state.json").read_text()), "local site/state.json"


def and_list(items):
    items = list(items)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def pct(x):
    return f"{x * 100:+.0f}%".replace("-", "−")


def usd(v, k=False):
    return f"${v / 1000:,.1f}k" if k else f"${v:,.0f}"


def main():
    s, src = load()
    past = s["past"]
    day, lo, hi = s["day"], *s["low_window"]
    pk = and_list(str(c["peak_days"]) for c in past)
    lw = and_list(str(c["low_days"]) for c in past)
    halv_years = and_list(c["halving"][:4] for c in past)
    dds = ", ".join(pct(c["drawdown"]) for c in past)
    mults = " → ".join(f"{m:.0f}×" if m >= 10 else f"{m:.1f}×" for m in s["low_to_peak"])
    peak_d = date.fromisoformat(s["peak_date"])
    window = ("we're inside that window now" if lo <= day <= hi else
              f"that window opens in {lo - day} days" if day < lo else f"we're {day - hi} days past that window")
    low_line = (f" The low so far is {usd(s['low'], True)} on {date.fromisoformat(s['low_date']):%b %-d} "
                f"({pct(s['low'] / s['peak'] - 1)})." if s.get("low") else "")
    next_h = date.fromisoformat(s["next_halving"])

    hn_title = "Show HN: The Halving Clock – Bitcoin's four-year cycle, rebuilt daily"
    assert len(hn_title) <= 80
    show_hn = f"""# Show HN

_Generated {date.today():%b %-d, %Y} from {src} (day {day}). Re-run `python launch_posts.py` right before posting._

Post at https://news.ycombinator.com/submit, ideally a weekday between 8 and 10am US Eastern. Stay around for the first two
hours to answer comments; that matters more than the wording.

**Title** ({len(hn_title)} characters; HN allows 80):

    {hn_title}

**URL:**

    https://halvingclock.com

**First comment** (post it yourself right after submitting; HN readers expect the maker to explain):

---

I wanted one page that answers "where are we in Bitcoin's four-year cycle?" without the hype, so I built this.

It's a static page rebuilt every morning by a GitHub Action: Python pulls block heights, exact halving times, hash rate
and miner rewards from the mempool.space API and daily prices from Bitstamp, then deploys to Cloudflare. The countdown
re-checks the live block height in your browser every minute. No accounts, no ads, no cookies.

What it shows:

- Each past cycle lined up by days since its halving. The last three peaked {s['pk_window'][0]}–{s['pk_window'][1]} days after
  the halving and bottomed {lo}–{hi} days after. This cycle peaked on day {s['peak_days_cur']} ({usd(s['peak'], True)},
  {peak_d:%b %Y}). Today is day {day}, and {window}.
- Where the old rhythm would put the next low and high. These are projections from three data points, not forecasts, and
  this cycle already broke the pattern once (a new high before the halving, after the US spot ETFs launched).
- A "returns per unit of mining difficulty" table. The result surprised me: price gained *more* per doubling of
  difficulty in recent cycles. What has collapsed is how fast difficulty grows, and what a unit of hash rate earns.

Code is open: https://github.com/theremjak/halvingclock

I'd especially like feedback on the cycle definitions (peak = highest close within two years of a halving) and on
whether the projections are framed honestly enough.

---

**Notes**
- Don't ask anyone to upvote; HN detects it and penalizes the post.
- If it doesn't catch on, you can repost once after a few weeks; HN allows a second try for Show HNs that got no attention.
"""

    reddit = f"""# Reddit launch posts

_Generated {date.today():%b %-d, %Y} from {src} (day {day}). Re-run `python launch_posts.py` right before posting._

Read each subreddit's sidebar rules on the day you post; they change. Post from your own account, reply to comments, and
don't post the same link in several subreddits on the same day (Reddit's spam filter links them). Space them out by a few days.

---

## r/Bitcoin (one-time launch post)

r/Bitcoin is wary of self-promotion. Lead with the observation, keep the tone matter-of-fact, and disclose that it's yours.

**Title:**

    Day {day} of the cycle: the last three bottoms came {lo}–{hi} days after the halving. I built a free tracker for it.

**Body:**

    I kept doing this math by hand, so I made a page that does it every day: halvingclock.com (free, no ads, open source).

    What stood out lining up the cycles by days since each halving:

    - Peaks: {pk} days after the {halv_years} halvings. This cycle's peak ({usd(s['peak'], True)}, {peak_d:%b %-d %Y}) landed on day {s['peak_days_cur']}.
    - Bottoms: {lw} days after. Today is day {day}, so {window}.{low_line}
    - Each cycle's gains are smaller: low-to-next-peak went {mults}. Drawdowns are shallower too ({dds}).

    It also has a live countdown to the next halving (~{s['remaining']:,} blocks, around {next_h:%B %Y}) and a section on mining difficulty vs returns.

    Three cycles is a small sample, and this one already broke the pattern once (new high before the halving, after the ETFs).
    So treat it as "where the old rhythm points", not a prediction. Data is mempool.space and Bitstamp; code: github.com/theremjak/halvingclock

    Curious whether people think the four-year cycle still holds post-ETF.

---

## r/BitcoinMarkets (daily discussion thread comment, not a standalone post)

r/BitcoinMarkets is strict about links outside the daily thread. Post this as a comment in the pinned **Daily Discussion**.

    Cycle-timing check, day {day} since the {ORD.get(s['cycle'], s['cycle'])} halving:

    Past bottoms came {lo}–{hi} days after their halving. This cycle topped on day {s['peak_days_cur']} ({usd(s['peak'], True)}),
    and {window}.{low_line} BTC is {usd(s['price'], True)} today, {pct(s['dd'])} from the peak; past cycles fell {dds}.

    I put the full comparison on a free page that updates daily (halvingclock.com) if anyone wants the charts.
    Not a prediction: three data points, and the ETF era may have changed the rhythm.

---

## Later: milestone posts

The daily job emails you a ready-to-paste draft whenever a notable milestone happens (new cycle low, leaving the
historical low window, 365 days to the halving, and so on). Those make good r/BitcoinMarkets daily-thread comments, and
occasionally a r/Bitcoin discussion post. Aim for at most one Reddit post a month so the account doesn't read as promotional.
"""
    OUT.mkdir(exist_ok=True)
    (OUT / "show_hn.md").write_text(show_hn)
    (OUT / "reddit.md").write_text(reddit)
    print(f"wrote launch/show_hn.md and launch/reddit.md (day {day}, from {src})")


if __name__ == "__main__":
    main()
