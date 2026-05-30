#!/usr/bin/env python3
"""
1xBet — Esports Odds Scraper (LineFeed REST API)
Target: https://1xbet.com/en/live/esports

1xBet has an internal LineFeed API at:
  /service-api/LiveFeed/GetGames?...  (live matches)
  /service-api/LiveFeed/Get1x2_VZip?...  (simple odds)
  /service-api/LineFeed/GetSportsShort?...  (sport list)

Key endpoint for esports: sports=43 (generally e-sports category)
CHL parameter = championship/tournament group.

The API returns gzipped JSON. Headers need a valid session/cookie context.
This scraper is designed to work inside a Playwright browser context
that establishes the session first, then extracts cookies for subsequent API calls.
"""

import json
import gzip
import logging
import requests
from datetime import datetime, timezone
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

API_BASE = "https://1xbet.com/service-api"
SPORT_ID = 43  # Esports


def fetch_live_feed(session: requests.Session, sport_id: int = SPORT_ID,
                     count: int = 200) -> List[Dict]:
    """
    Fetch live matches + upcoming via LiveFeed GetGames.
    Returns list of match dicts with embedded events.
    """
    url = f"{API_BASE}/LiveFeed/GetGames"
    params = {
        "sports": sport_id,
        "count": count,
        "mode": 4,      # Simple mode?  
        "country": 1,
        # "partner": 1,
        # "grId": 0,
        # "sortBy": 1,
    }

    resp = session.get(url, params=params, timeout=30)
    resp.raise_for_status()

    # Response may be gzipped even without Content-Encoding: gzip
    try:
        data = json.loads(resp.content)
    except json.JSONDecodeError:
        # Try decompress
        try:
            decompressed = gzip.decompress(resp.content)
            data = json.loads(decompressed)
        except Exception:
            logger.error("Failed to parse 1xBet response (not valid JSON/gzip)")
            return []

    return data.get("Value", [])


def fetch_match_odds(session: requests.Session, match_id: int) -> Optional[Dict]:
    """
    Fetch odds for a specific match via Get1x2_VZip.
    Returns dict with outcomes/odds or None.
    """
    url = f"{API_BASE}/LiveFeed/Get1x2_VZip"
    params = {"games": match_id}

    resp = session.get(url, params=params, timeout=15)
    try:
        if resp.headers.get("Content-Encoding") == "gzip":
            data = json.loads(gzip.decompress(resp.content))
        else:
            data = resp.json()
    except Exception as e:
        logger.warning(f"Failed to parse odds for match {match_id}: {e}")
        return None

    return data.get("Value", {})


def parse_match_to_record(match: Dict, odds_data: Optional[Dict] = None,
                          now: Optional[str] = None) -> Optional[Dict]:
    """
    Convert 1xBet match dict to canonical odds snapshot record.

    1xBet match structure (GetGames):
      O1  -> team 1 name
      O2  -> team 2 name
      S   -> sport ID
      LE  -> league/championship name
      L   -> league ID
      D   -> start time (Unix seconds? Milliseconds?)
      I   -> match ID
      O1I -> team1 ID
      O2I -> team2 ID
      E   -> list of events (markets) sometimes embedded
      EG  -> game ID or category?
    """
    team1 = match.get("O1", "")
    team2 = match.get("O2", "")
    game_raw = "Esports"  # Need to infer from sport/L subcategories
    tournament_name = match.get("LE", "")

    # Timestamp — 1xBet often uses Unix timestamps in ms or s
    ts_raw = match.get("D", 0)
    if ts_raw > 1e12:
        # milliseconds
        match_start = datetime.fromtimestamp(ts_raw / 1000, tz=timezone.utc).isoformat()
    elif ts_raw > 1e9:
        match_start = datetime.fromtimestamp(ts_raw, tz=timezone.utc).isoformat()
    else:
        match_start = ""

    match_id = match.get("I", "")
    match_url = f"https://1xbet.com/en/live/esports/{match_id}" if match_id else ""

    # Odds extraction
    price_team1 = None
    price_team2 = None
    price_draw = None

    # Odds may be in odds_data response or in match["E"] events
    if odds_data:
        outcomes = odds_data.get("E", [])
        for outcome in outcomes:
            # E structure: [{"T": 1, "C": 1.85}, ...]  T=type, C=coefficient
            o_type = outcome.get("T")
            coeff = outcome.get("C")
            if o_type == 1:       # Home/Team1 win
                price_team1 = coeff
            elif o_type == 2:     # Draw
                price_draw = coeff
            elif o_type == 3:     # Away/Team2 win
                price_team2 = coeff
    else:
        # Try embedded events in match
        events = match.get("E", [])
        # 1xBet "main" market is often events with G=0 or G=1
        # This needs live inspection to confirm
        for event in events:
            g = event.get("G", 0)
            if g == 1:  # Main 1X2
                for outcome in event.get("E", []):
                    o_type = outcome.get("T")
                    coeff = outcome.get("C")
                    if o_type == 1:
                        price_team1 = coeff
                    elif o_type == 2:
                        price_draw = coeff
                    elif o_type == 3:
                        price_team2 = coeff

    now = now or datetime.now(timezone.utc).isoformat()

    return {
        "bookmaker": "1xbet",
        "game_raw": game_raw,
        "tournament_name": tournament_name,
        "team1": team1,
        "team2": team2,
        "match_start_time": match_start,
        "match_url": match_url,
        "price_team1": price_team1,
        "price_team2": price_team2,
        "price_draw": price_draw,
        "handicap_line": None,
        "total_maps_line": None,
        "price_over": None,
        "price_under": None,
        "scraped_at": now,
    }


def scrape_1xbet(session: requests.Session, max_matches: int = 200) -> List[Dict]:
    """
    Full scrape: fetch all esports matches, get odds per match.
    """
    all_records = []
    matches = fetch_live_feed(session, sport_id=SPORT_ID, count=max_matches)
    logger.info(f"1xBet: fetched {len(matches)} matches")

    now = datetime.now(timezone.utc).isoformat()

    for match in matches[:max_matches]:
        match_id = match.get("I")
        odds = None
        if match_id:
            odds = fetch_match_odds(session, match_id)

        rec = parse_match_to_record(match, odds_data=odds, now=now)
        if rec and (rec["price_team1"] or rec["price_team2"]):
            all_records.append(rec)

    logger.info(f"1xBet: {len(all_records)} snapshot records ready")
    return all_records


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import sys
    sys.path.insert(0, "/Users/novaruptaair/Sonus Dropbox/Kevin Pitstock/CoWorld/esportbet/esports-odds/shared")
    from normalise import normalise_game

    with requests.Session() as s:
        # Need to seed session with cookies from a browser visit first
        # For testing, manually copy cookies from browser:
        # s.cookies.update({"SESSION": "...", "visit": "..."})
        records = scrape_1xbet(s, max_matches=50)
        for r in records[:5]:
            r["game"] = normalise_game(r["game_raw"])
            print(json.dumps(r, indent=2))
