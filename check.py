# check.py
# one contract address in, one verdict out. runs every time a token crosses your desk.
import csv, json, os, sys, time
from config import LOG, MIN_CONFIDENCE, LOW_TIER, PAPER, TICKET_USD, FRESH_MAX_AGE_HOURS, API_DAILY_BUDGET_USD, FALLBACK
import xqueue
from rugcheck import report, fact_kill
import onchain                                                   # [desk fix] fallback when rugcheck is down
from market import pool, market_kill, tier
from grok import ask, has_key
from prompts import JUDGE_PROMPT
import book


FIELDS = ["time", "mint", "symbol", "stage", "verdict", "confidence", "reason", "source"]   # [desk fix] + source


def _migrate():
    """[desk fix] 2026-11-01: add the data-source column once. Old rows: rugcheck if they got past the
    fact filter or were killed by it on a real report, 'none' when rugcheck itself failed, blank for limits."""
    if not os.path.exists(LOG):
        return
    with open(LOG) as f:
        if "source" in f.readline().strip().split(","):
            return
    rows = list(csv.DictReader(open(LOG)))
    with open(LOG + ".tmp", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            src = ("" if r["stage"] == "limits" else
                   "none" if (r["reason"] or "").startswith("rugcheck failed") else "rugcheck")
            w.writerow({**r, "source": src})
    os.replace(LOG + ".tmp", LOG)


def log(row: dict):
    _migrate()
    new = not os.path.exists(LOG)
    with open(LOG, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow({k: row.get(k) for k in w.fieldnames})


def check(mint: str) -> dict:
    if (g := book.guard(mint)):                                  # limits, free
        return {"stage": "limits", "verdict": "SKIP", "reason": g}

    # [desk fix] 2026-11-01: rugcheck first; if it errors, times out or has no report -> on-chain fallback
    # (onchain.py, stricter rules). Fallback can't fetch a required fact -> SKIP (fail closed).
    src, kill = "rugcheck", fact_kill
    try:
        token = report(mint)                                     # rug filter, free
        if token["risk_score"] is None:
            raise RuntimeError("no_report")
    except Exception as e:
        rc_err = str(e)[:80]
        if not FALLBACK["enabled"]:
            return {"stage": "facts", "verdict": "SKIP", "reason": f"rugcheck failed: {rc_err}", "source": "none"}
        try:
            token = onchain.report(mint)
        except Exception as e2:
            return {"stage": "facts", "verdict": "SKIP", "source": "none",
                    "reason": f"rugcheck failed: {rc_err} | fallback {str(e2)[:80]}"}
        src, kill = "onchain_fallback", onchain.fact_kill
    token["source"] = src
    if (k := kill(token)):
        return {"stage": "facts", "verdict": "SKIP", "reason": k, "symbol": token["symbol"], "source": src}

    try:
        m = pool(mint)                                           # pool, free
    except Exception as e:
        return {"stage": "pool", "verdict": "SKIP", "reason": f"dexscreener failed: {e}", "source": src}
    if (k := market_kill(m, token)):                             # [desk fix] token -> tier B top10 rule
        return {"stage": "pool", "verdict": "SKIP", "reason": k, "symbol": token["symbol"], "source": src}

    m["tier"] = tier(m)                                          # [desk fix] A/B, travels to Grok/queue/book
    if src == "onchain_fallback" and FALLBACK["tier_a_only"] and m["tier"] != "A":   # [desk fix] fallback: A only
        return {"stage": "pool", "verdict": "SKIP", "reason": "fallback_tier_b", "symbol": token["symbol"], "source": src}
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
                "price": m["price"], "liq_usd": m["liq_usd"], "url": m["url"], "tier": m["tier"], "source": src}

    try:
        ans = ask(JUDGE_PROMPT, {"token": token, "pool": m}, read_x=True)   # the only paid step
    except Exception as e:
        return {"stage": "grok", "verdict": "SKIP", "reason": f"grok failed: {e}", "source": src}

    verdict, conf = ans.get("verdict"), ans.get("confidence") or 0
    need = LOW_TIER["min_confidence"] if m["tier"] == "B" else MIN_CONFIDENCE   # [desk fix] tier B stricter
    if src == "onchain_fallback":                                # [desk fix] fallback facts -> higher bar
        need = max(need, FALLBACK["min_confidence"])
    if verdict == "BUY" and conf < need:
        verdict = "SKIP"
        ans["why"] = f"low confidence {conf}{' (needs ' + str(need) + (' tier B' if m['tier'] == 'B' else '') + (' fallback' if src != 'rugcheck' else '') + ')' if need != MIN_CONFIDENCE else ''}: {ans.get('why')}"   # [desk fix] keep Grok's reason
    return {**ans, "stage": "grok", "verdict": verdict, "symbol": m["symbol"] or token["symbol"],
            "reason": ans.get("why"), "price": m["price"], "liq_usd": m["liq_usd"], "url": m["url"],
            "tier": m["tier"], "source": src}


if __name__ == "__main__":
    mint = sys.argv[1].strip()
    v = check(mint)
    log({"time": time.strftime("%Y-%m-%d %H:%M"), "mint": mint, **v})
    if v["verdict"] == "BUY":
        if PAPER:
            book.open_position(mint, v["symbol"], v["price"], v["liq_usd"], tier=v.get("tier", "A"),
                               source=v.get("source", "rugcheck"))   # [desk fix] data source tag
            v["action"] = f"PAPER BUY ${TICKET_USD} at {v['price']}"
            xqueue.alert(f"PAPER BUY {v['symbol']} {mint} at {v['price']} conf {v.get('confidence')} tier {v.get('tier')} src {v.get('source')} (api)")
        else:
            v["action"] = (f"APPROVAL NEEDED: buy ${TICKET_USD} of {v['symbol']} in your own wallet, "
                           f"then run: python book.py add {mint} {TICKET_USD} <fill price> {v['liq_usd']}")
    print(json.dumps(v, indent=2))
