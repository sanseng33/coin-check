# config.py
# every number on the desk lives here. when you retune, you edit this file and nothing else.

MODEL = "grok-4.3"          # check console.x.ai -> Models if the API rejects it
                            # [desk] was "grok-4.7"; switched with owner approval 2026-10-28: 4.7 never ran x_search
PAPER = True                # week one: fake fills at real prices. flip only after you read the log

TICKET_USD = 25             # flat. never sized off the last win
MAX_OPEN = 4                # 4 x $25 = $100 in the market, max
MAX_ENTRIES_PER_DAY = 6
DAILY_LOSS_HALT_USD = 50    # realized loss today hits this -> no new entries until tomorrow
COOLDOWN_HOURS = 24         # no re-entry into a token you just left

FACTS = {                   # the rug filter. code only, no model
    "max_risk_score": 40,       # rugcheck score_normalised, 0-100, higher = riskier
    "min_lp_locked_pct": 90,    # biggest pool: LP locked or burned
    "max_top10_pct": 30,        # top 10 holders, pools and lockers excluded
    "max_dev_pct": 5,           # supply still sitting in the creator wallet
    "max_insiders": 0,          # insider-flagged holders + insider graph hits
    "min_liquidity_usd": 30000,  # tier A floor: pools >= this keep the article's rules unchanged
    "max_ticket_share": 0.01,   # your ticket is never more than 1% of the pool
    "min_age_min": 30,          # younger than this, every report is still guessing
    "max_age_hours": 72,
}

MIN_CONFIDENCE = 0.7        # Grok says BUY below this -> treated as SKIP

# [desk fix] 2026-10-29 tiered liquidity, owner-approved ("调整门槛，但是要聪明。你来定").
# Data (66 thin_pool rejects 10/28-29): 41 were still on the pump.fun bonding curve (DexScreener liq = 0),
# the 16 graduated pools were 4-57 min old at check; the 9 in the $10k-30k band: 7 are down 90-100% since.
# A flat $10k floor would have bought 10 of them in their first hour; in a replay all 10 hit the -35% stop.
# So: a lower floor only for pools that have SURVIVED the post-launch dump, plus stricter holders + confidence.
LOW_TIER = {                    # tier B = pools from min_liquidity_usd here up to FACTS["min_liquidity_usd"]
    "min_liquidity_usd": 12000,     # hard floor ($25 = 0.21% of the pool; 40% liq-drop exit still leaves $7.2k)
    "min_age_min": 120,             # pool older than 2h: the graduation dump is usually over by then
    "min_change_1h_pct": -30,       # not dumping right now (DexScreener priceChange.h1)
    "min_change_6h_pct": -50,       # not a collapsed chart (priceChange.h6)
    "max_vol1h_to_liq": 4.0,        # 1h volume above 4x the pool = churn / wash trading
    "max_top10_pct": 20,            # tighter than tier A's 30
    "min_confidence": 0.8,          # Grok / bot BUY needs >= 0.8 here (tier A: MIN_CONFIDENCE)
}
RECHECK = {                     # [desk fix] pool-stage rejects used to be final: re-look while they mature
    "reasons": ["thin_pool", "too_fresh", "bonding_curve", "lowtier_too_young", "lowtier_dumping",
                "lowtier_churn", "lowtier_top10", "dexscreener failed"],
    "window_hours": 24,             # only for mints first seen in the last 24h
    "every_min": 60,                # at most one re-check per mint per hour
    "per_run": 5,                   # plus up to 5 re-checks per scan (on top of 5 fresh mints)
}

EXIT = {
    "stop_pct": -35,                        # hard stop from entry
    "ladder": [(100, 0.50), (200, 0.25)],   # +100% sells half, +200% sells a quarter
    "trail_pct": 30,                        # the rest: out when price falls 30% from its peak
    "time_stop_hours": 6,                   # not up 20% after 6 hours -> out, dead money
    "time_stop_min_pct": 20,
    "liq_drop_pct": 40,                     # pool liquidity down 40% from entry -> out now
}

# [desk] hybrid check 14, new knobs (not part of the article's strategy numbers)
FRESH_MAX_AGE_HOURS = 6     # passed 13 checks and pool younger than this -> paid xAI call now
                            # older (low urgency) -> x_queue.jsonl for the bot's free X search
API_DAILY_BUDGET_USD = 3.0  # today's costs.csv total reaches this -> fresh tokens are queued too
QUEUE = "x_queue.jsonl"
PAPER_COST_PCT = 5.0        # [desk] round-trip slippage + fees estimate, % of each SELL leg's notional
                            # (a partial take-profit bears its share). reporting only: never changes a trigger

LOG = "checks.csv"
POSITIONS = "positions.json"
TRADES = "trades.csv"
