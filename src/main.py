#!/usr/bin/env python3
"""
1xBet Esports Odds Scraper — v1.1 (2026-06-07)

Schema: SCHEMA-LOCK-2026-06-07.md — all actors must conform.
Changes in v1.1:
  - Added `game` field (canonical name via normalise_game)

Flow:
  1. Playwright opens 1xbet.com/en/esports, waits 12s for CF JS + page hydration
  2. API calls via page.evaluate(fetch...) — uses browser's live session/cookies
  3. cyber-api leftmenu → subSport IDs → gamesBySport per subSport (prematch + live)
  4. Extract Match Winner odds, push to dataset
"""
import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from apify import Actor
from playwright.async_api import async_playwright
from normalise import normalise_game

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("1xbet-scraper")

BASE_URL = "https://1xbet.com"
PARAMS = "cfView=3&fcountry=12&gr=285&lng=en&ref=1"


def extract_record(game: dict, sport_name: str, now: str) -> Optional[Dict]:
    team1 = (game.get("opponent1") or {}).get("fullName", "").strip()
    team2 = (game.get("opponent2") or {}).get("fullName", "").strip()
    if not team1 or not team2:
        return None

    liga = (game.get("liga") or {}).get("name", "")
    match_id = game.get("id", "")
    start_time = game.get("startTime") or ""
    match_url = f"{BASE_URL}/en/esports/{match_id}" if match_id else ""

    p1 = p2 = p_draw = None
    for eg in (game.get("eventGroups") or [])[:1]:
        for outcome_list in eg.get("events", []):
            for o in outcome_list:
                t = o.get("type")
                try:
                    odds = float(o.get("cf", 0))
                except (TypeError, ValueError):
                    continue
                if not (1.01 <= odds <= 500):
                    continue
                if t == 1:
                    p1 = odds
                elif t == 3:
                    p2 = odds
                elif t == 2:
                    p_draw = odds

    if p1 is None or p2 is None:
        return None

    return {
        "bookmaker": "1xbet",
        "game_raw": sport_name,
        "game": normalise_game(sport_name),
        "tournament_name": liga,
        "team1": team1,
        "team2": team2,
        "match_start_time": start_time,
        "match_url": match_url,
        "market_name": "Match Winner",
        "price_team1": p1,
        "price_team2": p2,
        "price_draw": p_draw,
        "scraped_at": now,
    }


async def main() -> None:
    async with Actor() as actor:
        now = datetime.now(timezone.utc).isoformat()
        seen: set = set()
        all_records: List[Dict] = []

        actor.log.info("1xBet esports scraper v1.1 | Playwright + cyber-api")

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                ],
            )
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1920, "height": 1080},
                locale="en-US",
            )
            await context.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
            )
            page = await context.new_page()

            actor.log.info("Loading 1xbet.com/en/esports ...")
            await page.goto(f"{BASE_URL}/en/esports", wait_until="domcontentloaded", timeout=30000)

            actor.log.info("Waiting for CF challenge + page hydration (12s)...")
            await asyncio.sleep(12)

            title = await page.title()
            actor.log.info(f"Page title: {title!r}")

            # ── PREMATCH ──────────────────────────────────────────────
            actor.log.info("Fetching prematch leftmenu...")
            pm_menu_raw = await page.evaluate(f"""
                async () => {{
                    const r = await fetch('/cyber-api/mainfeedline/web/cyber/v3/leftmenu/real?fcountry=12&gr=285&lng=en&ref=1');
                    return await r.text();
                }}
            """)
            pm_menu = json.loads(pm_menu_raw)
            pm_ids = [item["subSportId"] for item in pm_menu if "subSportId" in item]
            actor.log.info(f"Prematch subSports: {pm_ids}")

            for ss_id in pm_ids:
                raw = await page.evaluate(f"""
                    async () => {{
                        const r = await fetch('/cyber-api/mainfeedline/web/cyber/v3/gamesBySport/real?{PARAMS}&subSport={ss_id}');
                        return await r.text();
                    }}
                """)
                try:
                    data = json.loads(raw)
                except Exception:
                    continue

                games = data.get("games", [])
                sport_name = (data.get("subSport") or {}).get("name", f"ss_{ss_id}")
                t_recs = 0
                for g in games:
                    rec = extract_record(g, sport_name, now)
                    if not rec:
                        continue
                    key = f"{rec['team1'].lower()}||{rec['team2'].lower()}"
                    if key in seen:
                        continue
                    seen.add(key)
                    all_records.append(rec)
                    t_recs += 1

                if t_recs:
                    actor.log.info(f"  [prematch] {sport_name}: {t_recs}")

            actor.log.info(f"Prematch done: {len(all_records)} records so far")

            # ── LIVE ──────────────────────────────────────────────────
            actor.log.info("Fetching live leftmenu...")
            lv_menu_raw = await page.evaluate(f"""
                async () => {{
                    const r = await fetch('/cyber-api/mainfeedlive/web/cyber/v3/leftmenu/real?fcountry=12&gr=285&lng=en&ref=1');
                    return await r.text();
                }}
            """)
            lv_menu = json.loads(lv_menu_raw)
            lv_ids = [item["subSportId"] for item in lv_menu if "subSportId" in item]
            actor.log.info(f"Live subSports: {lv_ids}")

            for ss_id in lv_ids:
                raw = await page.evaluate(f"""
                    async () => {{
                        const r = await fetch('/cyber-api/mainfeedlive/web/cyber/v3/gamesBySport/real?{PARAMS}&subSport={ss_id}');
                        return await r.text();
                    }}
                """)
                try:
                    data = json.loads(raw)
                except Exception:
                    continue

                games = data.get("games", [])
                sport_name = (data.get("subSport") or {}).get("name", f"ss_{ss_id}")
                t_recs = 0
                for g in games:
                    rec = extract_record(g, sport_name, now)
                    if not rec:
                        continue
                    key = f"{rec['team1'].lower()}||{rec['team2'].lower()}"
                    if key in seen:
                        continue
                    seen.add(key)
                    all_records.append(rec)
                    t_recs += 1

                if t_recs:
                    actor.log.info(f"  [live] {sport_name}: {t_recs}")

            await browser.close()

        actor.log.info(f"Grand total: {len(all_records)} records")

        for rec in all_records:
            await actor.push_data(rec)

        await actor.push_data({
            "_meta": True,
            "bookmaker": "1xbet",
            "records_total": len(all_records),
            "method": "playwright_cyber_api",
            "scraped_at": now,
        })


if __name__ == "__main__":
    asyncio.run(main())
