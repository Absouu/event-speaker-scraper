"""Custom scraper for DC Blockchain Summit."""

import logging
import time
from typing import Optional

from bs4 import BeautifulSoup

from models import Speaker

logger = logging.getLogger(__name__)

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


def scrape_dcblockchainsummit_speakers(url: str) -> list[Speaker]:
    """Scrape speakers from DC Blockchain Summit."""
    if not PLAYWRIGHT_AVAILABLE:
        logger.warning("Playwright not available")
        return []

    logger.info(f"Scraping DC Blockchain Summit speakers from: {url}")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until="networkidle", timeout=60000)

            # Scroll to load all content
            for i in range(15):
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(0.8)

            html = page.content()
            browser.close()

    except Exception as e:
        logger.error(f"Failed to load page: {e}")
        return []

    soup = BeautifulSoup(html, "html.parser")

    # Find all H2 elements (speaker names)
    h2s = soup.find_all("h2")
    logger.info(f"Found {len(h2s)} H2 elements")

    speakers = []
    for h2 in h2s:
        name = h2.get_text(strip=True)

        # Skip non-name entries
        if not name or name.upper() == "SPEAKERS" or len(name) < 3:
            continue

        # Try to find title/company in surrounding elements
        title = None
        parent = h2.parent
        if parent:
            # Look for paragraph or div with title info
            for elem in parent.find_all(["p", "div", "span"]):
                text = elem.get_text(strip=True)
                if text and text != name and len(text) < 150 and len(text) > 3:
                    title = text
                    break

        # Look for social links
        twitter_url = None
        linkedin_url = None
        if parent:
            for a in parent.find_all("a", href=True):
                href = a.get("href", "")
                if "twitter.com" in href or "x.com" in href:
                    twitter_url = href
                elif "linkedin.com" in href:
                    linkedin_url = href

        speakers.append(Speaker(
            name=name,
            title=title,
            twitter_url=twitter_url,
            linkedin_url=linkedin_url,
            source_url=url
        ))

    logger.info(f"Extracted {len(speakers)} speakers from DC Blockchain Summit")
    return speakers
