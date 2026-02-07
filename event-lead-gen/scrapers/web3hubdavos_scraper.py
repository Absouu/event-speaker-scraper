"""Custom scraper for Web3 Hub Davos (WordPress site with Load More button)."""

import logging
import re
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


def scrape_web3hubdavos_speakers(url: str) -> list[Speaker]:
    """Scrape speakers from Web3 Hub Davos."""
    if not PLAYWRIGHT_AVAILABLE:
        logger.warning("Playwright not available")
        return []

    # Normalize URL to /speakers/ page
    if "speakers-2025" in url or "speakers-2024" in url:
        url = "https://web3hubdavos.com/speakers/"

    logger.info(f"Scraping Web3 Hub Davos speakers from: {url}")

    speakers = []
    seen = set()

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=90000)
            time.sleep(5)  # Wait for JS

            # Click 'Load more' until all speakers loaded
            clicks = 0
            for i in range(30):
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

            # Get full HTML for parsing
            html = page.content()
            browser.close()

    except Exception as e:
        logger.error(f"Failed to load page: {e}")
        return []

    soup = BeautifulSoup(html, "html.parser")

    # Find speaker cards - they contain name, title, and company in structured way
    # Looking for links with speaker-thumb images and text data
    skip_texts = ["become a speaker", "stay updated", "speakers", "web3 hub davos",
                  "meet our", "all speakers", "2026 speakers", "2025 speakers"]

    # Find all speaker grid items or card containers
    # The speakers appear to be in anchor tags with image + text structure
    speaker_links = soup.find_all("a", href="#")

    for link in speaker_links:
        try:
            # Get all text content
            text = link.get_text(separator="\n", strip=True)
            if not text or len(text) < 5:
                continue

            # Skip section headers
            if any(s in text.lower() for s in skip_texts):
                continue

            # Parse the structured text (Name, Title, Company format)
            lines = [line.strip() for line in text.split("\n") if line.strip()]
            if len(lines) < 2:
                continue

            # First line is name
            name = lines[0].strip()
            if not name or len(name) < 2:
                continue
            if name.lower() in seen:
                continue

            # Second line is typically title, third is company
            # But sometimes title and company are on same line
            title = ""
            company = ""

            if len(lines) >= 3:
                title = lines[1].strip()
                company = lines[2].strip()
            elif len(lines) == 2:
                # Could be "Title Company" or just one of them
                second = lines[1].strip()
                # Try to detect if it looks like a company (common patterns)
                if any(kw in second.lower() for kw in ["ceo", "founder", "head", "director", "chief", "partner", "chairman", "president", "manager", "officer"]):
                    title = second
                else:
                    company = second

            seen.add(name.lower())
            speakers.append(Speaker(
                name=name,
                title=title,
                company=company,
                source_url=url
            ))

        except Exception:
            continue

    # Also try parsing H2 elements with adjacent text
    if len(speakers) < 10:
        logger.info("Few speakers from link parsing, trying H2 approach...")
        h2s = soup.find_all("h2")

        for h2 in h2s:
            name = h2.get_text(strip=True)
            if not name or len(name) < 2:
                continue
            if any(s in name.lower() for s in skip_texts):
                continue
            if name.lower() in seen:
                continue

            # Look for title/company in parent or adjacent elements
            title = ""
            company = ""
            parent = h2.parent
            if parent:
                # Get text from sibling elements
                for sibling in h2.find_next_siblings():
                    text = sibling.get_text(strip=True)
                    if text and text != name and len(text) > 2 and len(text) < 150:
                        if not title:
                            title = text
                        elif not company:
                            company = text
                            break

            seen.add(name.lower())
            speakers.append(Speaker(
                name=name,
                title=title,
                company=company,
                source_url=url
            ))

    logger.info(f"Extracted {len(speakers)} speakers from Web3 Hub Davos")
    return speakers
