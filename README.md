# RUG DESK (paper mode)

Solana memecoin rug filter from @0xboan's X article. **PAPER = True** - no wallet, no keys to funds, no real trades.
Every command must be run from this folder: `cd /workspace/desk` (all paths are relative).

Requires Python 3.10+ and `requests` (already installed on the box).

## Commands
| what | command |
| --- | --- |
| check one token (CA / mint) | `python3 check.py <MINT>` |
| pull 5 fresh Solana tokens from DexScreener profiles and check each | `python3 scan.py` |
| guard open paper positions (stop / ladder / trail / time stop); prints nothing if nothing happened | `python3 watch.py` |
| evening report (latest verdict per mint, API spend vs budget, queue size) | `python3 report.py` |
| queue every open paper position for a bot X re-read | `python3 queue_positions.py` |
| show the bot's queue + the judging criteria (compact JSON) | `python3 pending.py` |
| record the bot's verdict for one queued mint | `python3 apply_verdict.py <mint> <BUY\|SKIP\|HOLD\|EXIT_SUGGESTED> <confidence> "<why>" "<x_read>" "<main_risk>"` |
| scheduler (watch every 10 min, scan every 30 min) | `./scheduler.sh start\|stop\|status` |
| (live mode only, not used now) record a manual buy / sell | `python3 book.py add <mint> <usd> <price> <liq_usd>` / `python3 book.py close <mint> <price>` |

## Hybrid check 14
After the 13 free code checks pass, `check.py` routes the token:
- pool younger than `FRESH_MAX_AGE_HOURS` (6h) **and** today's `costs.csv` total < `API_DAILY_BUDGET_USD` ($3) -> paid xAI call now (grok-4.3 + x_search).
- otherwise (older = low urgency, budget reached, or no key) -> appended to `x_queue.jsonl`, logged as `stage=queued_for_bot, verdict=QUEUED`,
  reason `low_urgency_age_<N>h` / `api_budget_reached_<spent>_of_<budget>` / `no_api_key`. A mint already pending is not queued twice.

The bot judges the queue with its own free X search: `pending.py` -> search X -> `apply_verdict.py`.
- token items take BUY/SKIP. BUY below MIN_CONFIDENCE becomes SKIP. A BUY re-runs limits (book.guard) and the pool checks
  at the current price; if either fails it is logged as SKIP with the reason, else a paper position opens at the current price.
- position items (`queue_positions.py`, reason `position_review`) take HOLD/EXIT_SUGGESTED. EXIT_SUGGESTED closes the paper
  position at the current DexScreener price via book.sell, reason `bot_x_review`.
- every verdict -> checks.csv (`stage=bot_x`) and bot_verdicts.jsonl (with x_read / main_risk); opens/exits -> alerts.log.

Queue item (one JSON per line in x_queue.jsonl):
`{"mint","symbol","kind":"token"|"position","reason_queued","queued_at":"YYYY-MM-DD HH:MM","payload":{"token":{rugcheck facts},"pool":{dexscreener facts}[,"position":{entry,peak,liq0,steps,held_hours,pct_now}]}}`

## Scheduling
No cron on this box (PID 1 is tini, no crond), so `scheduler.py` is a small loop started with `nohup setsid` by `./scheduler.sh start`.
- watch.py at :00 :10 :20 ... ; scan.py at :00 and :30 (after watch). One instance only (lock file).
- logs: `logs/scheduler.log`, `logs/watch.log`, `logs/scan.log`; alerts (watch events, paper BUYs/EXITs) -> `alerts.log`.
- It inherits XAI_API_KEY from the shell that starts it (the key is never written to disk); scheduler.log says `XAI_API_KEY visible: yes/NO` at start.
- It survives the starting shell/session ending, but **not a box restart**: after a restart run `./scheduler.sh start` again.

## Files
- `config.py` - every number (untouched from the article). `PAPER = True`.
- `book.py` - limits, positions.json, trades.csv
- `rugcheck.py` - checks 1-9 (Rugcheck API), `market.py` - checks 10-13 (DexScreener API)
- `grok.py` + `prompts.py` - check 14 (xAI + X search, the only paid step)
- `check.py` - the pipeline; logs every verdict to `checks.csv`
- `original/` - the code blocks exactly as published, for diffing (`diff original/grok.py grok.py`)

## xAI key (check 14)
Without a key, tokens that pass all 13 free checks are logged as `stage=grok_skipped, verdict=NO_KEY`.
To add the key, type it yourself in a terminal on this box (it is not echoed, never paste it in chat):

    cd /workspace/desk
    read -rs -p "xai key: " K && printf 'XAI_API_KEY=%s\n' "$K" > .env && unset K
    chmod 600 .env

Test it (one cheap call, no X search):

    curl -s https://api.x.ai/v1/responses -H "Authorization: Bearer $(cut -d= -f2- .env)" \
      -H "Content-Type: application/json" -d '{"model":"grok-4.7","input":"reply with OK"}'

Note: xAI returns **400** "Incorrect API key" for a bad key (the article says 401).

## Model for check 14 (important)
On 2026-10-28 `grok-4.7` (the article's MODEL), `grok-4.6` and `grok-4.5` accepted the `x_search` tool but **never ran a search**
(0 x_search_calls) and still wrote an "X read" - i.e. made it up. `grok-4.3` and `grok-4.20-reasoning` do search.
config.py is untouched; grok.py takes an override from the environment:

config.py now has MODEL = "grok-4.3" (owner-approved). `XAI_MODEL=<name>` still overrides it.

grok.py also refuses (SKIP) any answer where no X search actually ran. Every call is logged to `costs.csv`
(tokens, x_search_calls, x_posts_fetched, cost_usd = cost_in_usd_ticks / 1e10); raw answers go to `grok_raw/<mint>.json`.

## Changes vs the article (marked `[desk fix]` in code)
1. `grok.py`: `has_key()`; `check.py` uses it to log `grok_skipped / NO_KEY` instead of calling xAI with no key.
2. `grok.py`: HTTP errors keep xAI's error text (bad key vs bad model is visible in checks.csv).
3. `rugcheck.py`: dev wallet % = max(creatorBalance, creator's share in topHolders). Live Rugcheck returns
   `creatorBalance = 0` even when the creator holds 20%+, so the original check 8 never fired.
5. `grok.py`: `XAI_MODEL` env override; SKIP when the model answered without running x_search; costs.csv + grok_raw/.
6. `check.py`: a low-confidence BUY->SKIP keeps Grok's own reason ("low confidence 0.65: <why>").
4. `report.py`: prints the count + symbols of tokens waiting on Grok (NO_KEY).

## Known limits
- NO_KEY tokens are in checks.csv, so scan.py treats them as seen and will not re-check them after the key is added.
  Re-run them by hand with `python3 check.py <MINT>` if still interesting.
- DexScreener `pairCreatedAt` is the pool's age; for pump.fun tokens that graduated, that is the migration time, not the launch time.
- Pump.fun bonding-curve pools have no `liquidity` on DexScreener -> always `thin_pool` (conservative, intended).

## Dashboard (observability page) - `dashboard/`
Static site, no build step: `dashboard/site/index.html` (vanilla JS + Chart.js from jsDelivr) reads `dashboard/site/data.json`
and refreshes every 60 s. Chinese UI, dark, mobile-friendly, marked 模拟盘 PAPER.
- `python3 dashboard/export_dashboard.py` -> writes `site/data.json` from checks.csv (deduped like report.py, via desklog.py),
  positions.json (+ one live DexScreener price per open position), trades.csv, costs.csv, x_queue.jsonl, bot_verdicts.jsonl,
  alerts.log tail and logs/scheduler.log. No key, no env values. The scheduler runs it after every 10-min cycle (logs/dashboard.log).
- Local preview: `cd dashboard/site && python3 -m http.server 8765` then open http://127.0.0.1:8765/
- Screenshots: `python3 dashboard/shot.py` -> `dashboard/preview.png` (desktop) and `dashboard/preview_mobile.png` (needs `playwright` + `python3 -m playwright install chromium`).
- Scheduler also catches up a missed :00/:30 scan (the box can sleep; runs then happen late, not on the dot).

### Publishing to GitHub Pages
Source code: branch `main` of https://github.com/sanseng33/coin-check (private). Runtime data, logs, grok_raw and .env are git-ignored.
Page: branch `gh-pages` = `index.html` + `data.json` + `.nojekyll` (+ `CNAME`), one generated commit, force-pushed.
- `dashboard/publish.conf` - repo / branch / heartbeat (not secret). `dashboard/publish.sh` - build + push; `DRY_RUN=1` builds locally only.
- The scheduler runs it after every 10-min export (logs/publish.log). It pushes only when data.json changed in substance
  (timestamps ignored) or every HEARTBEAT_MIN (60) minutes. `DESK_PUBLISH=0 ./scheduler.sh start` turns publishing off.
- Auth: `GITHUB_TOKEN` from the environment only. The remote URL has no credentials; the token goes to `git push` as an
  `http.https://github.com/.extraHeader` via `GIT_CONFIG_COUNT/KEY/VALUE` env vars (not argv, not .git/config, not on disk).
- Custom domain: put the domain on one line in `dashboard/CNAME` (e.g. `desk.example.com`), then at your DNS add
  `CNAME desk.example.com -> sanseng33.github.io` (apex: A records 185.199.108.153 / .109.153 / .110.153 / .111.153),
  set it under repo Settings -> Pages -> Custom domain, and tick "Enforce HTTPS" once the certificate is issued.
- Private repos: GitHub Pages from a private repo needs a paid plan (Pro / Team / Enterprise). Access-restricted
  ("private") Pages, visible only to people with repo access, needs GitHub Enterprise Cloud; on Pro/Team the site is public
  even though the repo is private. The data is paper-only with no secrets, but it does show strategy, positions and costs.
