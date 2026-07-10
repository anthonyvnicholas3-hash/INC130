#!/usr/bin/env python3
"""Refreshes feed.json for the landing page. Run it on a schedule:

    cron:      * * * * * /usr/bin/python3 /path/to/update_feed.py
    or a loop: while true; do python3 update_feed.py; sleep 30; done

The page polls feed.json every 30s and animates any odds that changed.

Fill in fetch_bets() with your odds source. To use the sportsbook's own
data: open the sports page in Chrome, DevTools > Network > Fetch/XHR,
find the request returning match/odds JSON, right-click > Copy as cURL,
and replicate that request below. Any odds API works the same way.

Team names can be a plain string (shown for all languages) or a dict
like {"en": "India", "hi": "भारत", "mr": "भारत"}. Same for path/time/live.
"""
import json
import os
import tempfile
import time

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "feed.json")
MAX_BETS = 4


def fetch_bets():
    """Return a list of bets in the feed schema, or None to keep the old file.

    Example against a JSON odds endpoint:

        import requests
        r = requests.get("https://<your-odds-endpoint>", timeout=10,
                         headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        out = []
        for m in r.json()["matches"][:MAX_BETS]:
            out.append({
                "path": m["league"],
                "time": m["start_time"],          # or "live": m["state"]
                "teams": [{"name": m["home"], "score": m.get("home_score", "")},
                          {"name": m["away"], "score": m.get("away_score", "")}],
                "odds": [{"label": "1", "value": m["odds"]["home"]},
                         {"label": "2", "value": m["odds"]["away"]}],
            })
        return out
    """
    return None


def main():
    bets = fetch_bets()
    if not bets:
        return
    payload = {
        "updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "bets": bets[:MAX_BETS],
    }
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(OUT))
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, OUT)


if __name__ == "__main__":
    main()
