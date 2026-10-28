# desklog.py  [desk] shared reading of checks.csv: drop known-invalid rows, latest verdict per mint.
import csv, os
from config import LOG

REVIEW_VERDICTS = ("HOLD", "EXIT_SUGGESTED")


def rows() -> list[dict]:
    return list(csv.DictReader(open(LOG))) if os.path.exists(LOG) else []


def invalid(r) -> bool:
    if r["stage"] == "grok" and "tool_choice" in (r["reason"] or ""):       # the tool_choice 400 test
        return True
    if r["stage"] == "grok" and (r["reason"] or "").startswith("low confidence 0.65") and r["confidence"] == "0.65" \
            and r["mint"].startswith("69Y6D9xQ"):                            # the grok-4.7 run that never searched X
        return True
    return False


def latest_per_mint(rs: list[dict]) -> list[dict]:
    """append-only file in time order -> last valid entry row per mint wins (supersedes NO_KEY / queued rows)."""
    latest = {}
    for r in rs:
        if not invalid(r) and r["verdict"] not in REVIEW_VERDICTS:
            latest[r["mint"]] = r
    return list(latest.values())
