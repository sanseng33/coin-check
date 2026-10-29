# market.py
# the pool itself: depth, age, price, and whether anyone can actually sell.
import time
import requests
from config import FACTS, TICKET_USD, LOW_TIER

DS = "https://api.dexscreener.com/tokens/v1/solana"


def pool(mint: str) -> dict | None:
    r = requests.get(f"{DS}/{mint}", timeout=15)
    r.raise_for_status()
    data = r.json()
    pairs = data if isinstance(data, list) else (data.get("pairs") or [])
    pairs = [p for p in pairs if (p.get("baseToken") or {}).get("address") == mint]
    if not pairs:
        return None
    p = max(pairs, key=lambda x: (x.get("liquidity") or {}).get("usd") or 0)
    h1 = (p.get("txns") or {}).get("h1") or {}
    born = p.get("pairCreatedAt")
    return {
        "symbol": (p.get("baseToken") or {}).get("symbol"),
        "price": float(p.get("priceUsd") or 0),
        "liq_usd": (p.get("liquidity") or {}).get("usd") or 0,
        "age_min": round((time.time() * 1000 - born) / 60000) if born else None,
        "buys_1h": h1.get("buys", 0),
        "sells_1h": h1.get("sells", 0),
        "vol_1h": (p.get("volume") or {}).get("h1"),
        "url": p.get("url"),
        # [desk fix] tiered liquidity inputs
        "dex": p.get("dexId"),
        "chg_1h": (p.get("priceChange") or {}).get("h1"),
        "chg_6h": (p.get("priceChange") or {}).get("h6"),
    }


def tier(m: dict) -> str:
    """[desk fix] A = pool >= FACTS min_liquidity_usd (article rules), B = LOW_TIER band (extra rules)."""
    return "A" if (m.get("liq_usd") or 0) >= FACTS["min_liquidity_usd"] else "B"


def market_kill(m: dict | None, token: dict | None = None) -> str | None:
    if not m:                                                    return "no_pool"
    if m["price"] <= 0:                                          return "no_price"
    if not m["liq_usd"] and m.get("dex") == "pumpfun":           return "bonding_curve"   # [desk fix] own code
    if m["liq_usd"] < LOW_TIER["min_liquidity_usd"]:             return "thin_pool"       # [desk fix] was FACTS floor
    if TICKET_USD / m["liq_usd"] > FACTS["max_ticket_share"]:    return "ticket_too_big"
    if m["age_min"] is None or m["age_min"] < FACTS["min_age_min"]:
        return "too_fresh"
    if m["age_min"] > FACTS["max_age_hours"] * 60:               return "too_old"
    if m["buys_1h"] >= 20 and m["sells_1h"] == 0:                return "nobody_can_sell"
    if tier(m) == "B":                                           # [desk fix] stricter rules for $12k-30k pools
        L = LOW_TIER
        if m["age_min"] < L["min_age_min"]:                      return "lowtier_too_young"
        if m.get("chg_1h") is None or m["chg_1h"] < L["min_change_1h_pct"]:
            return "lowtier_dumping"
        if m.get("chg_6h") is not None and m["chg_6h"] < L["min_change_6h_pct"]:
            return "lowtier_dumping"
        if (m.get("vol_1h") or 0) > L["max_vol1h_to_liq"] * m["liq_usd"]:
            return "lowtier_churn"
        if token is not None and (token.get("top10_pct") is None or token["top10_pct"] > L["max_top10_pct"]):
            return "lowtier_top10"
    return None
