# queue_positions.py  [desk] queue every open paper position for the bot's low-urgency X re-read.
import time
import book, xqueue
from market import pool
from rugcheck import report

added = 0
for mint, p in book.load().items():
    if xqueue.is_pending(mint, "position"):
        continue
    try:
        m = pool(mint)
    except Exception as e:
        m = {"error": f"dexscreener failed: {e}"}
    try:
        t = report(mint)
    except Exception as e:
        t = {"error": f"rugcheck failed: {e}"}
    pos = {"entry": p["entry"], "peak": p["peak"], "liq0": p["liq0"], "steps": p["steps"],
           "held_hours": round((time.time() - p["opened"]) / 3600, 1),
           "pct_now": round((m["price"] / p["entry"] - 1) * 100, 1) if m and m.get("price") else None}
    added += xqueue.add(mint, p["symbol"], "position", "position_review",
                        {"position": pos, "pool": m, "token": t})
print(f"queued {added} position(s), {len(xqueue.pending())} pending total")
