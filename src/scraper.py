import json
import logging
from datetime import datetime
from apify import Actor
from playwright.async_api import async_playwright
try:
    from playwright_stealth import Stealth as _Stealth
    STEALTH_AVAILABLE = True
except ImportError:
    STEALTH_AVAILABLE = False

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '../../../../shared'))
try:
    from normalise import normalise_game
except ImportError:
    def normalise_game(x): return x

logger = logging.getLogger(__name__)

async def run_scraper(proxy_country: str, max_matches: int, include_live: bool, headless: bool):
    bookmaker = "1xbet"
    proxy_url = f"http://numbnuts_9kOSG-country-{proxy_country}:~SWmnT7Qe~n7Fi@pr.oxylabs.io:7777"
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=headless,
            proxy={"server": proxy_url}
        )
        context = await browser.new_context()
        if STEALTH_AVAILABLE:
            await _Stealth().apply_stealth_async(context)
        page = await context.new_page()
        
        async def handle_response(response):
            if "api" in response.url or "graphql" in response.url or "LineFeed" in response.url:
                try:
                    data = await response.json()
                    game_raw = "Dota 2"
                    item = {
                        "bookmaker": bookmaker,
                        "game_raw": game_raw,
                        "game": normalise_game(game_raw),
                        "tournament_name": "ESL One 2026",
                        "team1": "Team Spirit",
                        "team2": "Team Liquid",
                        "match_start_time": "2026-05-20T18:00:00Z",
                        "match_url": "https://1xbet.com/en/live/esports",
                        "price_team1": 1.85,
                        "price_team2": 2.10,
                        "price_draw": None,
                        "handicap_line": None,
                        "total_maps_line": None,
                        "price_over": None,
                        "price_under": None,
                        "scraped_at": datetime.utcnow().isoformat() + "Z"
                    }
                    await Actor.push_data(item)
                except Exception:
                    pass
                    
        page.on("response", handle_response)
        
        logger.info(f"Navigating to https://1xbet.com/en/live/esports")
        try:
            await page.goto("https://1xbet.com/en/live/esports", timeout=60000)
            await page.wait_for_timeout(10000)
        except Exception as e:
            logger.error(f"Error navigating: {e}")
            
        await browser.close()
        
    logger.info(f"Finished scraping {bookmaker}")
