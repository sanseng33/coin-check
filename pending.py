# pending.py  [desk] print the bot's queue as compact JSON, with the criteria to judge it by.
import json
import xqueue
from config import MIN_CONFIDENCE, API_DAILY_BUDGET_USD
from prompts import JUDGE_PROMPT, POSITION_PROMPT

items = xqueue.pending()
out = {"pending": len(items),
       "api_spent_today_usd": round(xqueue.spent_today(), 4), "api_budget_usd": API_DAILY_BUDGET_USD,
       "min_confidence": MIN_CONFIDENCE,
       "apply": 'python3 apply_verdict.py <mint> <BUY|SKIP|HOLD|EXIT_SUGGESTED> <confidence> "<why>" "<x_read>" "<main_risk>"',
       "items": items}
if any(i["kind"] == "token" for i in items):
    out["judge_prompt"] = JUDGE_PROMPT.strip()
if any(i["kind"] == "position" for i in items):
    out["position_prompt"] = POSITION_PROMPT.strip()
print(json.dumps(out, separators=(",", ":")))
