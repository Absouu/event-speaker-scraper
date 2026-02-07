"""Custom scraper for ETH Denver."""

import logging
import re
import time
from typing import Optional

import requests
from bs4 import BeautifulSoup

from models import Speaker

logger = logging.getLogger(__name__)

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


def scrape_ethdenver_speakers(url: str) -> list[Speaker]:
    """Scrape speakers from ETH Denver (WordPress site with infinite scroll)."""
    if not PLAYWRIGHT_AVAILABLE:
        logger.warning("Playwright not available for ETH Denver")
        return []

    logger.info(f"Scraping ETH Denver speakers from: {url}")

    # Use Playwright to scroll and load all speakers
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until="networkidle", timeout=60000)

            # Keep scrolling to load all speakers
            last_count = 0
            for i in range(50):
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(2)

                count = page.locator('a[href*="/speakers/"]').count()
                if i > 0 and i % 10 == 0:
                    logger.info(f"  Scrolled {i} times, {count} links found...")

                if count == last_count and i > 5:
                    break
                last_count = count

            html = page.content()
            browser.close()

    except Exception as e:
        logger.error(f"Failed to load page: {e}")
        return []

    # Extract speaker URLs
    speaker_urls = set(re.findall(r'href="(https://ethdenver\.com/speakers/[^/"]+/)"', html))
    speaker_urls = [u for u in speaker_urls if "/feed/" not in u and "/page/" not in u]

    logger.info(f"Found {len(speaker_urls)} speaker URLs, scraping details...")

    # Scrape each speaker page
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
    speakers = []

    for i, speaker_url in enumerate(speaker_urls):
        if i > 0 and i % 50 == 0:
            logger.info(f"  Scraped {i}/{len(speaker_urls)} speakers...")

        try:
            r = requests.get(speaker_url, headers=headers, timeout=15)
            if r.status_code != 200:
                continue

            soup = BeautifulSoup(r.text, "html.parser")

            # Find name from H3 or title
            name = None
            for h3 in soup.find_all("h3"):
                text = h3.get_text(strip=True)
                if text and len(text) > 2 and text not in ["Venue:", "Follow us:", "Contributor agreement"]:
                    name = text
                    break

            if not name:
                title_tag = soup.find("title")
                if title_tag:
                    name = title_tag.get_text(strip=True).split(" - ")[0].strip()

            if not name or len(name) < 2:
                continue

            # Extract name from URL as fallback
            if name == "LVC at the National Western Center":
                url_name = speaker_url.rstrip("/").split("/")[-1]
                name = url_name.replace("-", " ").title()

            # Find social links
            twitter_url = None
            linkedin_url = None
            for a in soup.find_all("a", href=True):
                href = a.get("href", "")
                if "twitter.com/" in href or "x.com/" in href:
                    twitter_url = href
                elif "linkedin.com/" in href:
                    linkedin_url = href

            speakers.append(Speaker(
                name=name,
                twitter_url=twitter_url,
                linkedin_url=linkedin_url,
                source_url=speaker_url
            ))

        except Exception:
            continue

    logger.info(f"Extracted {len(speakers)} speakers from ETH Denver")
    return speakers
