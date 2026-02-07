"""Custom scraper for Web3 Hub Davos (Elementor site with Load More button)."""

import logging
import time
from typing import Optional

from models import Speaker

logger = logging.getLogger(__name__)

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


def scrape_web3hubdavos_speakers(url: str) -> list[Speaker]:
    """Scrape speakers from Web3 Hub Davos (Elementor with Load More)."""
    if not PLAYWRIGHT_AVAILABLE:
        logger.warning("Playwright not available")
        return []

    logger.info(f"Scraping Web3 Hub Davos speakers from: {url}")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=90000)
            time.sleep(5)  # Wait for JS

            # Click 'Load more' until all speakers loaded
            clicks = 0
            for i in range(20):
                try:
                    more_btn = page.locator("text=/load more/i").first
                    if more_btn.is_visible():
                        more_btn.click()
                        clicks += 1
                        time.sleep(1.5)
                    else:
                        break
                except Exception:
                    break

            logger.info(f"Clicked 'Load more' {clicks} times")

            # Extract speaker names directly from Playwright DOM
            h2_texts = page.locator("h2").all_text_contents()

            browser.close()

    except Exception as e:
        logger.error(f"Failed to load page: {e}")
        return []

    # Filter to speaker names (exclude section headers)
    skip_texts = ["become a speaker", "stay updated", "speakers", "web3 hub davos"]
    speakers = []
    seen = set()

    for text in h2_texts:
        name = text.strip()
        if not name or len(name) < 2:
            continue
        if any(s in name.lower() for s in skip_texts):
            continue
        if name.lower() in seen:
            continue
        seen.add(name.lower())

        speakers.append(Speaker(
            name=name,
            source_url=url
        ))

    logger.info(f"Extracted {len(speakers)} speakers from Web3 Hub Davos")
    return speakers
