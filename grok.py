# grok.py
# the only file that holds the key and the only place the desk talks to xAI.
import os, json, datetime, requests
from config import MODEL

URL = "https://api.x.ai/v1/responses"
# [desk fix] optional override without touching config.py. on 2026-10-28 grok-4.7/4.6/4.5 accepted the
# x_search tool but never called it (0 searches, invented X reads); grok-4.3 and grok-4.20 did search.
MODEL = os.environ.get("XAI_MODEL") or MODEL


def _key() -> str:
    k = os.environ.get("XAI_API_KEY")
    if not k and os.path.exists(".env"):
        for line in open(".env"):
            if line.startswith("XAI_API_KEY="):
                k = line.split("=", 1)[1].strip().strip('"')
    if not k:
        raise RuntimeError("no XAI_API_KEY in the environment or in .env")
    return k


def has_key() -> bool:
    """[desk fix] lets check.py skip the paid stage cleanly when no key is set yet."""
    try:
        _key()
        return True
    except RuntimeError:
        return False


def _text(resp: dict) -> str:
    if isinstance(resp.get("output_text"), str):
        return resp["output_text"]
    parts = []
    for item in resp.get("output") or []:
        if item.get("type") == "message":
            for c in item.get("content") or []:
                if c.get("type") in ("output_text", "text"):
                    parts.append(c.get("text") or "")
    return "\n".join(parts)


def _log_cost(payload: dict, resp: dict):
    """[desk fix] append usage + cost to costs.csv. 1 USD = 10^10 cost_in_usd_ticks."""
    import csv, time
    try:
        u = resp.get("usage") or {}
        tools = u.get("server_side_tool_usage_details") or {}
        ticks = u.get("cost_in_usd_ticks")
        row = {"time": time.strftime("%Y-%m-%d %H:%M"),
               "mint": (payload.get("token") or {}).get("mint"),
               "model": resp.get("model"),
               "input_tokens": u.get("input_tokens"), "output_tokens": u.get("output_tokens"),
               "x_search_calls": tools.get("x_search_calls"),
               "x_posts_fetched": tools.get("x_posts_fetched"),
               "cost_usd": round(ticks / 1e10, 6) if isinstance(ticks, (int, float)) else None}
        new = not os.path.exists("costs.csv")
        with open("costs.csv", "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(row))
            if new:
                w.writeheader()
            w.writerow(row)
    except Exception:
        pass


def ask(system: str, payload: dict, read_x: bool = False) -> dict:
    """One call, JSON in, JSON out. Anything that isn't JSON raises, and a raise is a SKIP upstream."""
    body = {"model": MODEL,
            "input": [{"role": "system", "content": system},
                      {"role": "user", "content": json.dumps(payload)}]}
    if read_x:
        since = (datetime.date.today() - datetime.timedelta(days=3)).isoformat()
        body["tools"] = [{"type": "x_search", "from_date": since}]
        body["max_turns"] = 2          # two rounds of searching, then it has to answer
    r = requests.post(URL, timeout=180, json=body,
                      headers={"Authorization": f"Bearer {_key()}"})
    if r.status_code >= 400:   # [desk fix] keep xAI's error text: a bad key comes back as 400, not 401
        raise RuntimeError(f"xai {r.status_code}: {r.text[:200]}")
    resp = r.json()
    _log_cost(payload, resp)   # [desk fix] record what each call cost, before parsing can fail
    os.makedirs("grok_raw", exist_ok=True)   # [desk fix] keep the raw answer for audit
    json.dump(resp, open(f"grok_raw/{(payload.get('token') or {}).get('mint')}.json", "w"), indent=1)
    text = _text(resp)
    searched = (((resp.get("usage") or {}).get("server_side_tool_usage_details") or {}).get("x_search_calls")
                or (resp.get("usage") or {}).get("num_server_side_tools_used") or 0)
    if read_x and not searched:        # [desk fix] an X read without an X search is a guess -> SKIP upstream
        raise ValueError("grok answered without running x_search")
    start, end = text.find("{"), text.rfind("}")
    if start == -1:
        raise ValueError(f"no json in answer: {text[:200]}")
    return json.loads(text[start:end + 1])
