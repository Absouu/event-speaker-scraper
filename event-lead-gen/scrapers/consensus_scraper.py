"""Custom scraper for Consensus (Coindesk) events."""

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


def scrape_consensus_speakers(url: str) -> list[Speaker]:
    """
    Scrape speakers from Consensus (Coindesk Bizzabo) events.

    Works for:
    - consensus.coindesk.com
    - consensus-hongkong.coindesk.com
    """
    if not PLAYWRIGHT_AVAILABLE:
        logger.warning("Playwright not available for Consensus scraping")
        return []

    logger.info(f"Scraping Consensus speakers from: {url}")

    # First get all speaker URLs from the main page using Playwright
    speaker_urls = set()

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until="networkidle", timeout=60000)

            # Scroll to load all speakers
            for i in range(40):
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(0.8)

            html = page.content()
            browser.close()

        soup = BeautifulSoup(html, "html.parser")

        # Find speaker links - pattern: /agenda/speaker/-name or /speaker/-name
        for link in soup.find_all("a", href=re.compile(r"/(?:agenda/)?speaker/-")):
            href = link.get("href", "")
            if href:
                # Make absolute URL
                if href.startswith("/"):
                    from urllib.parse import urlparse
                    parsed = urlparse(url)
                    href = f"{parsed.scheme}://{parsed.netloc}{href}"
                speaker_urls.add(href)

        logger.info(f"Found {len(speaker_urls)} speaker URLs")

    except Exception as e:
        logger.error(f"Failed to get speaker URLs: {e}")
        return []

    if not speaker_urls:
        return []

    # Scrape each speaker page
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    }
    speakers = []

    for i, speaker_url in enumerate(speaker_urls):
        if i > 0 and i % 20 == 0:
            logger.info(f"Scraped {i}/{len(speaker_urls)} speakers...")

        try:
            r = requests.get(speaker_url, headers=headers, timeout=15)
            if r.status_code != 200:
                continue

            page_soup = BeautifulSoup(r.text, "html.parser")

            # H1 = Name
            h1 = page_soup.find("h1")
            name = h1.get_text(strip=True) if h1 else None
            if not name or len(name) < 2:
                continue

            # H2s = Title, Company
            h2s = page_soup.find_all("h2")
            h2_texts = [h.get_text(strip=True) for h in h2s if h.get_text(strip=True)]

            title = h2_texts[0] if h2_texts else None
            company = h2_texts[1] if len(h2_texts) > 1 else None

            # Find social links
            twitter_url = None
            linkedin_url = None
            for a in page_soup.find_all("a", href=True):
                href = a.get("href", "")
                if "twitter.com/" in href or "x.com/" in href:
                    twitter_url = href
                elif "linkedin.com/" in href:
                    linkedin_url = href

            speakers.append(Speaker(
                name=name,
                title=title,
                company=company,
                twitter_url=twitter_url,
                linkedin_url=linkedin_url,
                source_url=speaker_url
            ))

        except Exception as e:
            continue

    logger.info(f"Extracted {len(speakers)} speakers from Consensus")
    return speakers
