# apply_verdict.py  [desk] write the bot's free-X-search verdict for one queued mint.
# python3 apply_verdict.py <mint> <BUY|SKIP|HOLD|EXIT_SUGGESTED> <confidence> "<why>" "<x_read>" "<main_risk>"
import json, sys, time
from config import MIN_CONFIDENCE, PAPER, TICKET_USD, LOW_TIER
from market import pool, market_kill, tier
from check import log
import book, xqueue

mint, verdict, conf = sys.argv[1].strip(), sys.argv[2].strip().upper(), float(sys.argv[3])
why, x_read, risk = (sys.argv[4:7] + ["", "", ""])[:3]
item = next((i for i in xqueue.pending() if i["mint"] == mint), None)
if not item:
    sys.exit(f"not pending: {mint}")
ok = {"token": ("BUY", "SKIP"), "position": ("HOLD", "EXIT_SUGGESTED")}[item["kind"]]
if verdict not in ok:
    sys.exit(f"{item['kind']} item takes {'/'.join(ok)}, got {verdict}")

sym, now = item["symbol"], time.strftime("%Y-%m-%d %H:%M")
row = {"time": now, "mint": mint, "symbol": sym, "stage": "bot_x", "verdict": verdict,
       "confidence": conf, "reason": why}
action = None

if verdict == "BUY" and conf < MIN_CONFIDENCE:
    row["verdict"], row["reason"] = "SKIP", f"low confidence {conf}: {why}"
elif verdict == "BUY":                                     # re-run limits + pool at today's price
    g = book.guard(mint)
    try:
        m = pool(mint); k = market_kill(m, (item.get("payload") or {}).get("token"))   # [desk fix] tier B top10
    except Exception as e:
        m, k = None, f"dexscreener failed: {e}"
    t = tier(m) if m else "A"
    if not (g or k) and t == "B" and conf < LOW_TIER["min_confidence"]:   # [desk fix] tier B needs more
        row["verdict"], row["reason"] = "SKIP", f"low confidence {conf} (tier B needs {LOW_TIER['min_confidence']}): {why}"
    elif g or k:
        row["verdict"], row["reason"] = "SKIP", f"bot BUY, but now {g or k}: {why}"
    else:
        book.open_position(mint, m["symbol"] or sym, m["price"], m["liq_usd"], tier=t)
        action = f"PAPER BUY ${TICKET_USD} {sym} at {m['price']} tier {t}"
elif verdict == "EXIT_SUGGESTED" and mint in book.load():
    try:
        m = pool(mint); price = m["price"] if m else 0.0
    except Exception:
        price = None
    if price is None:
        action = "price feed down, position NOT closed; re-queue later"
    else:
        pnl = book.sell(mint, 1.0, price, "bot_x_review")
        action = f"PAPER EXIT {sym} at {price}, pnl ${pnl:+.2f}"

if not (action or "").startswith("price feed down"):
    xqueue.remove(mint)
log(row)
with open("bot_verdicts.jsonl", "a") as f:
    f.write(json.dumps({**row, "kind": item["kind"], "x_read": x_read, "main_risk": risk,
                        "queued_at": item["queued_at"], "action": action}) + "\n")
if action:
    xqueue.alert(f"{action} (bot_x: {why})")
print(f"{sym}: {row['verdict']} {conf}" + (f" ({row['reason'][:90]})" if row["verdict"] != verdict else "")
      + (f" -> {action}" if action else "") + f" | {len(xqueue.pending())} pending")
