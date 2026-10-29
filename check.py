# check.py
# one contract address in, one verdict out. runs every time a token crosses your desk.
import csv, json, os, sys, time
from config import LOG, MIN_CONFIDENCE, LOW_TIER, PAPER, TICKET_USD, FRESH_MAX_AGE_HOURS, API_DAILY_BUDGET_USD
import xqueue
from rugcheck import report, fact_kill
from market import pool, market_kill, tier
from grok import ask, has_key
from prompts import JUDGE_PROMPT
import book


def log(row: dict):
    new = not os.path.exists(LOG)
    with open(LOG, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["time", "mint", "symbol", "stage", "verdict",
                                          "confidence", "reason"])
        if new:
            w.writeheader()
        w.writerow({k: row.get(k) for k in w.fieldnames})


def check(mint: str) -> dict:
    if (g := book.guard(mint)):                                  # limits, free
        return {"stage": "limits", "verdict": "SKIP", "reason": g}

    try:
        token = report(mint)                                     # rug filter, free
    except Exception as e:
        return {"stage": "facts", "verdict": "SKIP", "reason": f"rugcheck failed: {e}"}
    if (k := fact_kill(token)):
        return {"stage": "facts", "verdict": "SKIP", "reason": k, "symbol": token["symbol"]}

    try:
        m = pool(mint)                                           # pool, free
    except Exception as e:
        return {"stage": "pool", "verdict": "SKIP", "reason": f"dexscreener failed: {e}"}
    if (k := market_kill(m, token)):                             # [desk fix] token -> tier B top10 rule
        return {"stage": "pool", "verdict": "SKIP", "reason": k, "symbol": token["symbol"]}

    m["tier"] = tier(m)                                          # [desk fix] A/B, travels to Grok/queue/book
    # [desk] hybrid check 14: fresh + under budget -> paid API now; everything else -> bot's free X queue
    symbol = m["symbol"] or token["symbol"]
    spent = xqueue.spent_today()
    if not has_key():
        why = "no_api_key"
    elif m["age_min"] >= FRESH_MAX_AGE_HOURS * 60:
        why = f"low_urgency_age_{m['age_min'] // 60}h"
    elif spent >= API_DAILY_BUDGET_USD:
        why = f"api_budget_reached_{spent:.2f}_of_{API_DAILY_BUDGET_USD:.2f}"
    else:
        why = None
    if why:
        added = xqueue.add(mint, symbol, "token", why, {"token": token, "pool": m})
        return {"stage": "queued_for_bot", "verdict": "QUEUED", "symbol": symbol,
                "reason": why if added else f"already_pending ({why})",
                "price": m["price"], "liq_usd": m["liq_usd"], "url": m["url"], "tier": m["tier"]}

    try:
        ans = ask(JUDGE_PROMPT, {"token": token, "pool": m}, read_x=True)   # the only paid step
    except Exception as e:
        return {"stage": "grok", "verdict": "SKIP", "reason": f"grok failed: {e}"}

    verdict, conf = ans.get("verdict"), ans.get("confidence") or 0
    need = LOW_TIER["min_confidence"] if m["tier"] == "B" else MIN_CONFIDENCE   # [desk fix] tier B stricter
    if verdict == "BUY" and conf < need:
        verdict = "SKIP"
        ans["why"] = f"low confidence {conf}{' (tier B needs ' + str(need) + ')' if m['tier'] == 'B' else ''}: {ans.get('why')}"   # [desk fix] keep Grok's reason
    return {**ans, "stage": "grok", "verdict": verdict, "symbol": m["symbol"] or token["symbol"],
            "reason": ans.get("why"), "price": m["price"], "liq_usd": m["liq_usd"], "url": m["url"],
            "tier": m["tier"]}


if __name__ == "__main__":
    mint = sys.argv[1].strip()
    v = check(mint)
    log({"time": time.strftime("%Y-%m-%d %H:%M"), "mint": mint, **v})
    if v["verdict"] == "BUY":
        if PAPER:
            book.open_position(mint, v["symbol"], v["price"], v["liq_usd"], tier=v.get("tier", "A"))
            v["action"] = f"PAPER BUY ${TICKET_USD} at {v['price']}"
            xqueue.alert(f"PAPER BUY {v['symbol']} {mint} at {v['price']} conf {v.get('confidence')} tier {v.get('tier')} (api)")
        else:
            v["action"] = (f"APPROVAL NEEDED: buy ${TICKET_USD} of {v['symbol']} in your own wallet, "
                           f"then run: python book.py add {mint} {TICKET_USD} <fill price> {v['liq_usd']}")
    print(json.dumps(v, indent=2))
