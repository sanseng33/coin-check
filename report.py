# report.py
# the evening report. everything in it comes from checks.csv and trades.csv, nothing from memory.
import csv, os, time
from collections import Counter
from config import LOG, PAPER, API_DAILY_BUDGET_USD
import book, xqueue
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
print(f"realized pnl today: ${book.today_pnl():+.2f}")
print(f"xAI API spend today: ${xqueue.spent_today():.2f} of ${API_DAILY_BUDGET_USD:.2f} budget")
if done:
    print(f"green exits: {len(wins)}/{len(done)}")
    best = max(done, key=lambda t: float(t["pnl"]))
    worst = min(done, key=lambda t: float(t["pnl"]))
    print(f"best: {best['symbol']} ${float(best['pnl']):+.2f} | worst: {worst['symbol']} ${float(worst['pnl']):+.2f}")
if reasons:
    top, n = reasons.most_common(1)[0]
    print(f"most common kill: {top} ({n}x)")
