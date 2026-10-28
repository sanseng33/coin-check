# export_dashboard.py  [desk] desk files -> dashboard/site/data.json for the static observability page.
# Reads only desk files (+ one DexScreener price per open position). Never reads or writes secrets / env.
import csv, json, os, re, sys, time
from collections import Counter, defaultdict

DESK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(DESK); sys.path.insert(0, DESK)
import book, xqueue
from config import (PAPER, MODEL, EXIT, FACTS, TICKET_USD, MAX_OPEN, MAX_ENTRIES_PER_DAY, DAILY_LOSS_HALT_USD,
                    MIN_CONFIDENCE, FRESH_MAX_AGE_HOURS, API_DAILY_BUDGET_USD)
from desklog import rows, latest_per_mint, REVIEW_VERDICTS

OUT = os.path.join(DESK, "dashboard", "site", "data.json")
DS = "https://dexscreener.com/solana/"
now = time.time()
day = time.strftime("%Y-%m-%d")


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def jsonl(path):
    if not os.path.exists(path):
        return []
    out = []
    for l in open(path):
        try:
            out.append(json.loads(l))
        except ValueError:
            pass
    return out


def tail(path, n):
    return [l.rstrip("\n") for l in open(path).readlines()[-n:]] if os.path.exists(path) else []


# ---- scheduler health (from logs/, no env) ----
def scheduler():
    pid, alive = None, False
    try:
        pid = int(open("logs/scheduler.lock").read().strip())
        os.kill(pid, 0); alive = True
    except Exception:
        pass
    last = {"start": None, "watch.py": None, "scan.py": None}
    runs = []
    for l in tail("logs/scheduler.log", 400):
        m = re.match(r"(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) (\S+)(?: exit=(-?\d+))?", l)
        if not m:
            continue
        ts, what, code = m.groups()
        if what == "scheduler":
            last["start"] = ts
        elif what in last:
            last[what] = ts
            runs.append({"time": ts, "job": what, "exit": int(code) if code else None})
    def age_min(ts):
        return round((now - time.mktime(time.strptime(ts, "%Y-%m-%d %H:%M:%S"))) / 60, 1) if ts else None
    w = age_min(last["watch.py"])
    status = "ok" if alive and w is not None and w <= 15 else ("stale" if alive else "down")
    return {"running": alive, "status": status, "started": last["start"],
            "last_watch": last["watch.py"], "last_watch_age_min": w,
            "last_scan": last["scan.py"], "last_scan_age_min": age_min(last["scan.py"]),
            "failed_runs_recent": sum(1 for r in runs[-30:] if r["exit"] not in (0, None)),
            "recent_runs": runs[-12:]}


# ---- positions with exit-rule state ----
def positions():
    from market import pool
    out = []
    for mint, p in book.load().items():
        cur, liq, err = None, None, None
        try:
            m = pool(mint)
            cur, liq = (m["price"], m["liq_usd"]) if m else (0.0, 0.0)
        except Exception as e:
            err = f"dexscreener: {type(e).__name__}"
        e = p["entry"]
        held_h = (now - p["opened"]) / 3600
        steps = p["steps"]; ladder = EXIT["ladder"]
        out.append({
            "mint": mint, "symbol": p["symbol"], "url": DS + mint,
            "entry": e, "current": cur, "peak": p["peak"],
            "pct": round((cur / e - 1) * 100, 1) if cur else None,
            "peak_pct": round((p["peak"] / e - 1) * 100, 1),
            "qty_left_pct": round(p["qty"] / p["qty0"] * 100, 1),
            "value_usd": round(p["qty"] * cur, 2) if cur else None,
            "unrealized_usd": round(p["qty"] * (cur - e), 2) if cur else None,
            "liq0": p["liq0"], "liq_now": liq, "price_error": err,
            "opened": time.strftime("%Y-%m-%d %H:%M", time.localtime(p["opened"])),
            "held_hours": round(held_h, 1),
            "rules": {
                "stop_price": e * (1 + EXIT["stop_pct"] / 100), "stop_pct": EXIT["stop_pct"],
                "next_take": ({"at_pct": ladder[steps][0], "sell_frac": ladder[steps][1],
                               "price": e * (1 + ladder[steps][0] / 100)} if steps < len(ladder) else None),
                "trail_armed": steps > 0, "trail_price": p["peak"] * (1 - EXIT["trail_pct"] / 100),
                "time_stop_in_hours": round(EXIT["time_stop_hours"] - held_h, 1),
                "time_stop_min_pct": EXIT["time_stop_min_pct"],
                "liq_floor": p["liq0"] * (1 - EXIT["liq_drop_pct"] / 100),
            }})
    return out


# ---- trades + running paper pnl ----
trades = book.trades()
closed = [t for t in trades if t["action"] != "open"]
cum, curve = 0.0, []
for t in closed:
    cum += float(t["pnl"]); curve.append({"time": t["time"], "pnl": float(t["pnl"]), "cum": round(cum, 2),
                                          "symbol": t["symbol"], "reason": t["reason"]})

# ---- checks ----
allrows = rows()
latest_all = latest_per_mint(allrows)
today = latest_per_mint([r for r in allrows if r["time"].startswith(day)])
st = Counter(r["stage"] for r in today)
skip = Counter(r["stage"] for r in today if r["verdict"] == "SKIP")
funnel = {
    "checked": len(today),
    "killed_limits": skip["limits"],
    "killed_facts": skip["facts"],
    "killed_pool": skip["pool"],
    "passed_13": sum(1 for r in today if r["stage"] in ("grok", "grok_skipped", "queued_for_bot", "bot_x")),
    "to_api": st["grok"],
    "to_bot": st["queued_for_bot"] + st["bot_x"],
    "bot_pending": st["queued_for_bot"],
    "never_judged_no_key": st["grok_skipped"],
    "killed_api": skip["grok"], "killed_bot": skip["bot_x"],
    "buy": sum(1 for r in today if r["verdict"] == "BUY"),
}
kills = Counter()
for r in today:
    if r["stage"] in ("facts", "pool", "limits") and r["verdict"] == "SKIP":
        kills[r["reason"] or "?"] += 1
recent_checks = [{"time": r["time"], "mint": r["mint"], "symbol": r["symbol"], "url": DS + r["mint"],
                  "stage": r["stage"], "verdict": r["verdict"], "confidence": num(r["confidence"]),
                  "reason": r["reason"]} for r in sorted(latest_all, key=lambda r: r["time"], reverse=True)[:60]]

# ---- costs ----
by_day, calls = defaultdict(float), []
if os.path.exists(xqueue.COSTS):
    for r in csv.DictReader(open(xqueue.COSTS)):
        c = num(r.get("cost_usd")) or 0.0
        by_day[r["time"][:10]] += c
        calls.append({"time": r["time"], "mint": r["mint"], "model": r["model"], "cost_usd": c,
                      "x_search_calls": r.get("x_search_calls"), "x_posts_fetched": r.get("x_posts_fetched")})

# ---- queue (trim payload to what a human scans) ----
queue = []
for i in xqueue.pending():
    pl = i.get("payload") or {}
    pool_ = pl.get("pool") or {}; tok = pl.get("token") or {}
    queue.append({"mint": i["mint"], "symbol": i["symbol"], "kind": i["kind"], "reason_queued": i["reason_queued"],
                  "queued_at": i["queued_at"], "url": DS + i["mint"],
                  "liq_usd": pool_.get("liq_usd"), "age_min": pool_.get("age_min"),
                  "risk_score": tok.get("risk_score"), "top10_pct": tok.get("top10_pct"),
                  "pct_now": (pl.get("position") or {}).get("pct_now")})

data = {
    "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"), "generated_epoch": int(now), "tz": "UTC+8",
    "paper": PAPER, "model": MODEL,
    "config": {"ticket_usd": TICKET_USD, "max_open": MAX_OPEN, "max_entries_per_day": MAX_ENTRIES_PER_DAY,
               "daily_loss_halt_usd": DAILY_LOSS_HALT_USD, "min_confidence": MIN_CONFIDENCE,
               "fresh_max_age_hours": FRESH_MAX_AGE_HOURS, "api_budget_usd": API_DAILY_BUDGET_USD,
               "exit": EXIT, "facts": FACTS},
    "scheduler": scheduler(),
    "positions": positions(),
    "pnl": {"realized_total": round(cum, 2), "realized_today": round(book.today_pnl(), 2),
            "closed_count": len(closed), "wins": sum(1 for t in closed if float(t["pnl"]) > 0), "curve": curve},
    "trades": trades[-50:][::-1],
    "funnel_today": funnel, "kill_reasons_today": kills.most_common(),
    "recent_checks": recent_checks,
    "queue": queue,
    "bot_verdicts": [{k: v.get(k) for k in ("time", "symbol", "mint", "kind", "verdict", "confidence", "reason",
                                             "x_read", "main_risk", "action")} for v in jsonl("bot_verdicts.jsonl")[-20:][::-1]],
    "api": {"today_usd": round(by_day.get(day, 0.0), 4), "budget_usd": API_DAILY_BUDGET_USD,
            "by_day": [{"day": d, "usd": round(v, 4)} for d, v in sorted(by_day.items())][-30:],
            "recent_calls": calls[-15:][::-1]},
    "alerts": tail("alerts.log", 30)[::-1],
}
os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT + ".tmp", "w") as f:
    json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
os.replace(OUT + ".tmp", OUT)
