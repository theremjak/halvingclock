# Next steps

## 1. Lightning tips via Strike (pending)

`halvingclock@strike.me` was unclaimed as of Oct 1, 2026.

1. Install **Strike**, sign up and complete ID verification (required in the US).
2. Choose the username **`halvingclock`** → Lightning address **`halvingclock@strike.me`**
   (or change an existing username under Settings → Profile).
3. Pick how incoming bitcoin is handled: keep as bitcoin, or auto-convert to dollars.
4. Then, with Claude:
   - verify the address answers publicly: `https://strike.me/.well-known/lnurlp/halvingclock` should return
     `"tag":"payRequest"` (an unclaimed name returns `"Could not get user information"`);
   - set `"lightning": "halvingclock@strike.me"` in `config.json`, commit, push and run the workflow
     (adds the ⚡ "Copy Lightning address" button next to the coffee button);
   - republish the Nostr profile so posts can be zapped:
     `NOSTR_NSEC=$(grep '^nsec:' ~/halvingclock-nostr-key.txt | awk '{print $2}') python social.py --nostr-profile`
     (adds `lud16` automatically once `lightning` is set);
   - add "⚡ halvingclock@strike.me" to the Bluesky and X bios by hand.
5. Optional: send a ~100-sat test tip from another Lightning wallet.

## 2. Profiles (by hand)

- Bluesky: Edit Profile → display name **The Halving Clock**, bio:
  "Where Bitcoin sits in its halving cycle, updated daily. Live countdown to the next halving at halvingclock.com. Not financial advice."

## 3. Launch posts (by hand)

Run `python launch_posts.py` right before posting; it refreshes `launch/show_hn.md` and `launch/reddit.md` with today's numbers.

- **Hacker News:** Show HN, a weekday 8–10am US Eastern; post the first comment yourself and answer for ~2 hours.
- **Reddit:** r/Bitcoin launch post, then a few days later the r/BitcoinMarkets daily-thread comment.
  Never the same link in several subreddits on the same day.
- After launch, milestone drafts arrive by email; aim for at most one Reddit post a month.
