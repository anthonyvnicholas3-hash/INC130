#!/usr/bin/env python3
"""Refreshes feed.json by reading the sportsbook's rendered page.

The odds on the source site arrive over a WebSocket, so there is no JSON
endpoint to call directly. This script opens the page in a headless
browser (the socket connects and odds render, same as a normal visitor),
then extracts the "Most placed bets today" cards from the page.

Setup (once):
    pip install playwright
    playwright install chromium

Run on a schedule from the folder that holds feed.json:
    * * * * * cd /path/to/site && python3 update_feed_browser.py

If the extraction ever comes back empty or wrong, run with --debug and
send debug_dump.html for selector tuning.
"""
import json
import os
import re
import sys
import time

SOURCE_URL = "https://odds96.com/en/sports"
HEADING = "most placed bets"
MAX_BETS = 4
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "feed.json")
DEBUG = "--debug" in sys.argv

# Runs in the page. A card = an element whose leaf-node texts contain a
# "League / Country / Competition" path plus at least two decimal odds.
# Returns each card's leaf texts in document order (innermost match wins).
JS_EXTRACT = r"""
() => {
  const leafTexts = (root) => {
    const out = [];
    const walk = (n) => {
      for (const c of n.childNodes) {
        if (c.nodeType === 3) {
          const t = c.textContent.replace(/\s+/g, ' ').trim();
          if (t) out.push(t);
        } else if (c.nodeType === 1) walk(c);
      }
    };
    walk(root);
    return out;
  };
  const looksLikeCard = (texts) => {
    if (texts.length < 4 || texts.length > 40) return false;
    const odds = texts.filter(t => /^\d+\.\d\d$/.test(t) || /^(1|X|2) \d+\.\d\d$/.test(t));
    const path = texts.some(t => (t.match(/ \/ /g) || []).length >= 1 && /[A-Za-z]/.test(t));
    return odds.length >= 2 && path;
  };
  const all = Array.from(document.querySelectorAll('div,li,article,section'));
  const cards = [];
  for (const e of all) {
    const texts = leafTexts(e);
    if (!looksLikeCard(texts)) continue;
    let handled = false;
    for (let i = 0; i < cards.length; i++) {
      if (cards[i].el.contains(e)) { cards[i] = { el: e, texts }; handled = true; break; }
      if (e.contains(cards[i].el)) { handled = true; break; }
    }
    if (!handled) cards.push({ el: e, texts });
  }
  return cards.map(c => c.texts);
}
"""

RX_ODDS_VAL = re.compile(r"^\d+\.\d\d$")
RX_ODDS_COMBO = re.compile(r"^(1|X|2) (\d+\.\d\d)$")
RX_LABEL = re.compile(r"^(1|X|2)$")
RX_SCORE = re.compile(r"^\d+(/\d+)?$|^\d+-\d+$")
RX_LIVE = re.compile(r"innings|over |half|live|\bq[1-4]\b|\bset\b", re.I)
RX_TIME = re.compile(r"today|tomorrow|\d{1,2}:\d{2}", re.I)


def parse_card(tokens):
    # path = the token with the most " / " separators
    path, best = None, 0
    for t in tokens:
        n = len(t.split(" / ")) - 1
        if n > best and re.search(r"[A-Za-z]", t):
            path, best = t, n
    if not path:
        return None

    odds, teams, scores, meta = [], [], [], None
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t == path:
            i += 1
            continue
        m = RX_ODDS_COMBO.match(t)
        if m:
            odds.append({"label": m.group(1), "value": float(m.group(2))})
            i += 1
            continue
        if RX_LABEL.match(t) and i + 1 < len(tokens) and RX_ODDS_VAL.match(tokens[i + 1]):
            odds.append({"label": t, "value": float(tokens[i + 1])})
            i += 2
            continue
        if RX_SCORE.match(t):
            scores.append(t)
            i += 1
            continue
        if meta is None and (RX_LIVE.search(t) or RX_TIME.search(t)):
            meta = t
            i += 1
            continue
        if len(t) > 2 and re.search(r"[A-Za-zऀ-ॿ]", t) and not RX_ODDS_VAL.match(t):
            teams.append({"name": t})
        i += 1

    if len(teams) < 2 or len(odds) < 2:
        return None
    teams = teams[:2]
    for k, s in enumerate(scores[:2]):
        teams[k]["score"] = s
    bet = {"path": path, "teams": teams, "odds": odds[:3]}
    if meta and RX_LIVE.search(meta):
        bet["live"] = meta
    else:
        bet["time"] = meta or ""
    return bet


def fetch_bets():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            viewport={"width": 430, "height": 950},
            user_agent=("Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36"),
        )
        page.goto(SOURCE_URL, wait_until="domcontentloaded", timeout=60000)
        try:
            page.get_by_text(HEADING, exact=False).first.wait_for(timeout=45000)
        except Exception:
            pass  # heading text may differ; the card scan below still runs
        page.wait_for_timeout(4000)  # let the odds socket populate

        if DEBUG:
            with open("debug_dump.html", "w", encoding="utf-8") as f:
                f.write(page.content())

        raw = page.evaluate(JS_EXTRACT) or []
        browser.close()

    bets = []
    for tokens in raw:
        b = parse_card(tokens)
        if b:
            bets.append(b)
        if len(bets) >= MAX_BETS:
            break
    return bets


def main():
    bets = fetch_bets()
    if not bets:
        print("no bets extracted; feed.json left unchanged"
              + ("" if DEBUG else " (re-run with --debug and send debug_dump.html)"))
        return
    payload = {
        "updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "bets": bets,
    }
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, OUT)
    print("feed.json updated with %d bets" % len(bets))


if __name__ == "__main__":
    main()
