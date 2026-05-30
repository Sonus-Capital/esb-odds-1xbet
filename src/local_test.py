#!/usr/bin/env python3
"""Test 1xBet LineFeed API directly — no Apify needed.

Usage:
  pip install requests
  python src/local_test.py
"""
import json
import gzip
import logging
import sys

import requests
sys.path.insert(0, "../../shared")
from normalise import normalise_game

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("test")

API_BASE = "https://1xbet.com/service-api"
SPORT_ID = 43

HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://1xbet.com",
    "Referer": "https://1xbet.com/en/live/esports",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126.0.0.0 Safari/537.36",
}


def test_basic():
    url = f"{API_BASE}/LiveFeed/GetGames?sports={SPORT_ID}&count=50&mode=4&country=1"
    logger.info(f"GET {url}")

    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
    except Exception as e:
        logger.error(f"Request failed: {type(e).__name__}: {e}")
        return

    logger.info(f"Status: {resp.status_code}")
    logger.info(f"Content-Encoding: {resp.headers.get('Content-Encoding', 'none')}")
    logger.info(f"Content-Type: {resp.headers.get('Content-Type', 'N/A')}")

    # Save raw
    raw_file = "1xbet_raw.bin"
    with open(raw_file, "wb") as f:
        f.write(resp.content)
    logger.info(f"Raw saved: {raw_file} ({len(resp.content)} bytes)")

    if resp.status_code != 200:
        logger.error(f"Non-200. Body[:500]: {resp.text[:500]}")
        return

    # Try parse
    try:
        text = resp.text
        if resp.content[:2] == b"\x1f\x8b":
            decompressed = gzip.decompress(resp.content)
            text = decompressed.decode("utf-8")
            logger.info("Detected gzip encoding, decompressed")
        data = json.loads(text)
    except Exception as e:
        logger.error(f"Parse failed: {e}")
        logger.error(f"Raw text[:200]: {resp.text[:200]}")
        return

    matches = data.get("Value", [])
    logger.info(f"✓ Got {len(matches)} matches")

    if matches:
        logger.info(f"First match keys: {list(matches[0].keys())}")
        logger.info("Sample match:\n" + json.dumps(matches[0], indent=2)[:2000])

    # Count matches with odds
    with_odds = sum(1 for m in matches if m.get("E"))
    logger.info(f"Matches with embedded events (odds): {with_odds}")

    return matches


def main():
    logger.info("=" * 60)
    logger.info("1XBET LINEFEED API TEST")
    logger.info("=" * 60)
    matches = test_basic()
    if matches:
        logger.info("\n✓ SUCCESS — inspect 1xbet_raw.bin and logs")
    else:
        logger.error("\n✗ FAILED — check 1xbet_raw.bin for raw response")


if __name__ == "__main__":
    main()
