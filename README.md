# The Halving Clock — halvingclock.com

A free, static page that rebuilds itself every day: where Bitcoin sits in its halving cycle, where past cycles peaked
and bottomed, a live countdown to the next halving, and how returns per unit of mining difficulty have changed.

- **Data:** [mempool.space](https://mempool.space) public API (block heights, halving times, hash rate, difficulty,
  miner rewards) and [Bitstamp](https://www.bitstamp.net) public OHLC API (daily BTC/USD since Aug 2011). No API keys.
- **Build:** `python build.py` → `site/` (index.html, og.png, favicon, robots, sitemap, headers). ~10 s.
- **Host:** Cloudflare Pages project `halvingclock`, custom domain `halvingclock.com`.
- **Schedule:** `.github/workflows/daily.yml` rebuilds and deploys at 06:15 UTC daily (plus a manual "Run workflow" button).
- **Settings:** `config.json` — `kofi` (Ko-fi username), `lightning` (Lightning address), `cf_analytics_token`
  (Cloudflare Web Analytics). Leave a field empty to hide that feature.

## One-time setup

1. **Domain:** register `halvingclock.com` at Cloudflare → Domain Registration (about $10/yr at cost).
2. **First deploy (local):** `npx wrangler login` once, then `./deploy.sh`. This creates the Pages project.
3. **Custom domain:** Cloudflare dashboard → Workers & Pages → `halvingclock` → Custom domains → add `halvingclock.com`
   and `www.halvingclock.com` (DNS + SSL are automatic when the domain is on Cloudflare).
4. **Daily automation:** create a GitHub repo, push this folder, then in the repo's Settings → Secrets and variables → Actions add
   - `CLOUDFLARE_API_TOKEN` — Cloudflare → My Profile → API Tokens → *Create token* → template "Edit Cloudflare Workers"
     (or a custom token with **Account › Cloudflare Pages › Edit**)
   - `CLOUDFLARE_ACCOUNT_ID` — shown on the Cloudflare dashboard's right sidebar
   Then Actions → Daily rebuild → *Run workflow* to test.
5. **Donations:** create a Ko-fi page and/or a Lightning address, put them in `config.json`, commit.
6. **Analytics (optional):** Cloudflare → Web Analytics → add site → copy the token into `config.json`.

Not financial advice: the page shows where the historical rhythm would put things, not a forecast.
