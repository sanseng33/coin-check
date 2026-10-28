# xqueue.py  [desk] hybrid check 14: the low-urgency queue the bot judges with its own free X search,
# plus today's paid-API spend from costs.csv.
import csv, json, os, time
from config import QUEUE

COSTS = "costs.csv"
ALERTS = "alerts.log"


def pending() -> list[dict]:
    if not os.path.exists(QUEUE):
        return []
    return [json.loads(l) for l in open(QUEUE) if l.strip()]


def is_pending(mint: str, kind: str | None = None) -> bool:
    return any(i["mint"] == mint and (kind is None or i["kind"] == kind) for i in pending())


def add(mint, symbol, kind, reason_queued, payload) -> bool:
    """kind: 'token' (entry judgment) or 'position' (re-read an open paper position). No double-queue."""
    if is_pending(mint, kind):
        return False
    item = {"mint": mint, "symbol": symbol, "kind": kind, "reason_queued": reason_queued,
            "queued_at": time.strftime("%Y-%m-%d %H:%M"), "payload": payload}
    with open(QUEUE, "a") as f:
        f.write(json.dumps(item) + "\n")
    return True


def remove(mint: str) -> dict | None:
    items = pending()
    hit = next((i for i in items if i["mint"] == mint), None)
    if hit:
        rest = [i for i in items if i is not hit]
        with open(QUEUE + ".tmp", "w") as f:
            f.writelines(json.dumps(i) + "\n" for i in rest)
        os.replace(QUEUE + ".tmp", QUEUE)
    return hit


def spent_today() -> float:
    if not os.path.exists(COSTS):
        return 0.0
    day = time.strftime("%Y-%m-%d")
    return sum(float(r["cost_usd"] or 0) for r in csv.DictReader(open(COSTS)) if r["time"].startswith(day))


def alert(line: str):
    with open(ALERTS, "a") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M')} {line}\n")
