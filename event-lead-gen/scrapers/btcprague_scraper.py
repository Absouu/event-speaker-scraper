"""Custom scraper for BTC Prague."""

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


def scrape_btcprague_speakers(url: str) -> list[Speaker]:
    """Scrape speakers from BTC Prague (WordPress site)."""
    if not PLAYWRIGHT_AVAILABLE:
        logger.warning("Playwright not available")
        return []

    logger.info(f"Scraping BTC Prague speakers from: {url}")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until="networkidle", timeout=60000)

            # Scroll to load all content
            for i in range(25):
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(0.8)

            html = page.content()
            browser.close()

    except Exception as e:
        logger.error(f"Failed to load page: {e}")
        return []

    soup = BeautifulSoup(html, "html.parser")

    # Find speaker links and cards
    speaker_data = []
    seen_urls = set()

    # Pattern 1: Links to individual speaker pages
    for link in soup.find_all("a", href=re.compile(r"btcprague\.com/speakers/[^/]+")):
        href = link.get("href", "")
        title = link.get("title", "")

        if not href or href in seen_urls or "/speakers/page/" in href:
            continue
        seen_urls.add(href)

        # Get the name from title attribute or link text
        name = title or link.get_text(strip=True)
        if not name or len(name) < 2:
            continue

        # Skip non-speaker entries (cookie popups, UI elements)
        skip_patterns = ["manage", "cookie", "vendor", "options", "services", "privacy", "consent"]
        if any(p in name.lower() for p in skip_patterns):
            continue

        # Try to find role in parent card
        role = ""
        card = link.find_parent("div", class_=re.compile(r"b-cream|speaker|card"))
        if card:
            role_elem = card.find("div", class_="fs-xs")
            if role_elem:
                role = role_elem.get_text(strip=True)

        # Find social links in card
        twitter_url = None
        linkedin_url = None
        if card:
            for a in card.find_all("a", href=True):
                h = a.get("href", "")
                if "twitter.com" in h or "x.com" in h:
                    twitter_url = h
                elif "linkedin.com" in h:
                    linkedin_url = h

        speaker_data.append({
            "name": name,
            "title": role,
            "url": href,
            "twitter": twitter_url,
            "linkedin": linkedin_url
        })

    # Also check for featured speaker (Michael Saylor style card)
    featured = soup.find("h1", class_=re.compile(r"h2|heading"))
    if featured:
        name = featured.get_text(strip=True)
        if name and name not in [s["name"] for s in speaker_data]:
            # Find role
            role_div = featured.find_next("div")
            role = role_div.get_text(strip=True) if role_div else ""

            speaker_data.append({
                "name": name,
                "title": role,
                "url": url,
                "twitter": None,
                "linkedin": None
            })

    logger.info(f"Found {len(speaker_data)} speakers from page")

    # If we found speaker URLs, scrape individual pages for more details
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
    speakers = []

    for data in speaker_data:
        name = data["name"]
        title = data["title"]
        twitter_url = data["twitter"]
        linkedin_url = data["linkedin"]

        # Try to get more details from individual page
        if data["url"] and data["url"] != url:
            try:
                r = requests.get(data["url"], headers=headers, timeout=10)
                if r.status_code == 200:
                    page_soup = BeautifulSoup(r.text, "html.parser")

                    # Get title from page if not already found
                    if not title:
                        title_div = page_soup.find("div", class_="fs-xs")
                        if not title_div:
                            # Look for text after H1
                            h1 = page_soup.find("h1")
                            if h1:
                                next_div = h1.find_next("div")
                                if next_div:
                                    title = next_div.get_text(strip=True)
                        else:
                            title = title_div.get_text(strip=True)

                    # Get social links if not found
                    for a in page_soup.find_all("a", href=True):
                        h = a.get("href", "")
                        if not twitter_url and ("twitter.com" in h or "x.com" in h):
                            twitter_url = h
                        elif not linkedin_url and "linkedin.com" in h:
                            linkedin_url = h

            except Exception:
                pass

        speakers.append(Speaker(
            name=name,
            title=title,
            twitter_url=twitter_url,
            linkedin_url=linkedin_url,
            source_url=data["url"] or url
        ))

    logger.info(f"Extracted {len(speakers)} speakers from BTC Prague")
    return speakers
