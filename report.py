# report.py
# the evening report. everything in it comes from checks.csv and trades.csv, nothing from memory.
import csv, os, time
from collections import Counter
from config import LOG, PAPER, API_DAILY_BUDGET_USD
import book, xqueue, pnl
from desklog import latest_per_mint

day = time.strftime("%Y-%m-%d")
checks = [r for r in csv.DictReader(open(LOG))] if os.path.exists(LOG) else []
checks = [r for r in checks if r["time"].startswith(day)]
done = [t for t in book.trades() if t["time"].startswith(day) and t["action"] != "open"]


# [desk fix] history stays in checks.csv; invalid rows dropped, latest verdict per mint (see desklog.py)
entry_all = checks
checks = latest_per_mint(checks)
reviews = [r for r in entry_all if r["verdict"] in ("HOLD", "EXIT_SUGGESTED")]

by_stage = Counter(r["stage"] for r in checks if r["verdict"] == "SKIP")
buys = [r for r in checks if r["verdict"] == "BUY"]
wins = [t for t in done if float(t["pnl"]) > 0]
reasons = Counter(r["reason"] for r in checks if r["stage"] in ("facts", "pool"))

print(f"EVENING REPORT {day} {'(PAPER)' if PAPER else '(LIVE)'}")
print(f"checked: {len(checks)} tokens (latest verdict per mint)")
print(f"killed by rug filter: {by_stage['facts']} | by pool: {by_stage['pool']} | "
      f"by Grok API: {by_stage['grok']} | by bot X read: {by_stage['bot_x']} | by limits: {by_stage['limits']}")
no_key = [r for r in checks if r["stage"] == "grok_skipped"]
if no_key:
    print(f"passed 13 checks, never judged (no key): {len(no_key)}")
q = xqueue.pending()
print(f"bot queue: {len(q)} pending ({sum(i['kind'] == 'token' for i in q)} tokens, "
      f"{sum(i['kind'] == 'position' for i in q)} position reviews)")
if reviews:
    print(f"position reviews today: {sum(r['verdict'] == 'HOLD' for r in reviews)} HOLD, "
          f"{sum(r['verdict'] == 'EXIT_SUGGESTED' for r in reviews)} EXIT_SUGGESTED")
print(f"bought: {len(buys)} | open now: {len(book.load())}")
r_day, r_all = pnl.realized(day), pnl.realized()
print(f"realized pnl today: gross ${r_day['gross']:+.2f} | net ${r_day['net']:+.2f} "
      f"(cost {pnl.PAPER_COST_PCT}% of sells: ${r_day['cost']:.2f})")
print(f"realized pnl all time: gross ${r_all['gross']:+.2f} | net ${r_all['net']:+.2f}")
unr_g = unr_c = 0.0
for _m, _p in book.load().items():
    try:
        from market import pool
        _px = (pool(_m) or {}).get("price") or 0
        unr_g += _p["qty"] * (_px - _p["entry"]); unr_c += pnl.unrealized_cost(_p["qty"], _px)
    except Exception:
        pass
if book.load():
    print(f"open positions unrealized: gross ${unr_g:+.2f} | net ${unr_g - unr_c:+.2f}")
gl = pnl.go_live()
print(f"go-live gate: closed trades {gl['closed_trades']}/{gl['min_trades']} {'OK' if gl['trades_met'] else 'no'} | "
      f"net total ${gl['net_total']:+.2f} {'OK' if gl['net_met'] else 'no'} | "
      f"losses beyond stop ({gl['stop_pct']}%): {gl['beyond_stop']} {'OK' if gl['beyond_stop_met'] else 'no'}")
print(f"xAI API spend today: ${xqueue.spent_today():.2f} of ${API_DAILY_BUDGET_USD:.2f} budget")
if done:
    print(f"green exits: {len(wins)}/{len(done)} gross, "
          f"{sum(1 for l in pnl.legs(done) if l['net'] > 0)}/{len(done)} net")
    dl = [l for l in pnl.legs(done)]
    best = max(dl, key=lambda t: t["gross"]); worst = min(dl, key=lambda t: t["gross"])
    print(f"best: {best['symbol']} ${best['gross']:+.2f} (net ${best['net']:+.2f}) | "
          f"worst: {worst['symbol']} ${worst['gross']:+.2f} (net ${worst['net']:+.2f})")
if reasons:
    top, n = reasons.most_common(1)[0]
    print(f"most common kill: {top} ({n}x)")
