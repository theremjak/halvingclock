# Show HN

_Generated Sep 30, 2026 from local site/state.json (day 892). Re-run `python launch_posts.py` right before posting._

Post at https://news.ycombinator.com/submit, ideally a weekday between 8 and 10am US Eastern. Stay around for the first two
hours to answer comments; that matters more than the wording.

**Title** (69 characters; HN allows 80):

    Show HN: The Halving Clock – Bitcoin's four-year cycle, rebuilt daily

**URL:**

    https://halvingclock.com

**First comment** (post it yourself right after submitting; HN readers expect the maker to explain):

---

I wanted one page that answers "where are we in Bitcoin's four-year cycle?" without the hype, so I built this.

It's a static page rebuilt every morning by a GitHub Action: Python pulls block heights, exact halving times, hash rate
and miner rewards from the mempool.space API and daily prices from Bitstamp, then deploys to Cloudflare. The countdown
re-checks the live block height in your browser every minute. No accounts, no ads, no cookies.

What it shows:

- Each past cycle lined up by days since its halving. The last three peaked 371–546 days after
  the halving and bottomed 777–924 days after. This cycle peaked on day 534 ($124.7k,
  Oct 2025). Today is day 892, and we're inside that window now.
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
