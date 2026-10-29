# pnl.py  [desk] gross vs net (after PAPER_COST_PCT) P&L, computed from trades.csv. Reporting only:
# book.py / watch.py triggers and the daily-loss halt still use gross numbers, as in the article.
import time
from config import PAPER_COST_PCT, EXIT, TICKET_USD
import book


def leg_cost(t: dict) -> float:
    """cost of one trades.csv row: sell legs (partial/close) pay PAPER_COST_PCT of their notional."""
    return 0.0 if t["action"] == "open" else float(t["usd"]) * PAPER_COST_PCT / 100


def legs(trades=None) -> list[dict]:
    """every trades.csv row + cost + net pnl (history untouched, derived on read)."""
    out = []
    for t in (trades if trades is not None else book.trades()):
        c = leg_cost(t); g = float(t["pnl"])
        out.append({**t, "gross": g, "cost": round(c, 4), "net": round(g - c, 4)})
    return out


def realized(day: str | None = None) -> dict:
    ls = [l for l in legs() if l["action"] != "open" and (day is None or l["time"].startswith(day))]
    g = sum(l["gross"] for l in ls); c = sum(l["cost"] for l in ls)
    return {"gross": round(g, 2), "cost": round(c, 2), "net": round(g - c, 2), "legs": len(ls)}


def unrealized_cost(qty: float, price: float) -> float:
    """what selling the rest now would cost."""
    return qty * price * PAPER_COST_PCT / 100


def round_trips() -> list[dict]:
    """closed positions (open ... close), with gross/net pnl and gross return on the entry ticket."""
    open_, done = {}, []
    for l in legs():
        m = l["mint"]
        if l["action"] == "open":
            open_[m] = {"mint": m, "symbol": l["symbol"], "opened": l["time"], "ticket": float(l["usd"]) or TICKET_USD,
                        "gross": 0.0, "cost": 0.0, "legs": 0, "tier": l.get("tier") or "A"}   # [desk fix] tier
            continue
        p = open_.setdefault(m, {"mint": m, "symbol": l["symbol"], "opened": None, "ticket": TICKET_USD,
                                 "gross": 0.0, "cost": 0.0, "legs": 0, "tier": l.get("tier") or "A"})
        p["gross"] += l["gross"]; p["cost"] += l["cost"]; p["legs"] += 1
        if l["action"] == "close":
            p.update(closed=l["time"], exit_reason=l["reason"], net=round(p["gross"] - p["cost"], 2),
                     gross=round(p["gross"], 2), cost=round(p["cost"], 2),
                     gross_pct=round(p["gross"] / p["ticket"] * 100, 1))
            p["beyond_stop"] = p["gross_pct"] < EXIT["stop_pct"]
            done.append(open_.pop(m))
    return done


def by_tier() -> dict:
    """[desk fix] closed round trips split by liquidity tier, for the week-end review (A >= $30k, B $12k-30k)."""
    out = {}
    for t in ("A", "B"):
        rt = [r for r in round_trips() if r.get("tier", "A") == t]
        out[t] = {"closed": len(rt), "gross": round(sum(r["gross"] for r in rt), 2),
                  "net": round(sum(r["net"] for r in rt), 2), "wins_net": sum(1 for r in rt if r["net"] > 0),
                  "beyond_stop": sum(1 for r in rt if r["beyond_stop"])}
    return out


def go_live(min_trades: int = 20) -> dict:
    """informational go-live criteria (实盘门槛). Nothing reads this to trade."""
    rt = round_trips(); net = realized()["net"]
    beyond = sum(1 for r in rt if r["beyond_stop"])
    return {"closed_trades": len(rt), "min_trades": min_trades, "trades_met": len(rt) >= min_trades,
            "net_total": net, "net_met": net > 0,
            "beyond_stop": beyond, "stop_pct": EXIT["stop_pct"], "beyond_stop_met": beyond == 0,
            "all_met": len(rt) >= min_trades and net > 0 and beyond == 0}
