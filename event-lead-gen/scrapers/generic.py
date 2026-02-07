"""Generic speaker scraper for event websites."""

import json
import logging
import re
import time
from typing import Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from models import Speaker

logger = logging.getLogger(__name__)

# Check if Playwright is available
try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    logger.debug("Playwright not installed - JS-rendered sites with infinite scroll won't be fully supported")


def _extract_social_links(card) -> tuple[Optional[str], Optional[str]]:
    """Extract Twitter and LinkedIn URLs from a card element."""
    twitter_url = None
    linkedin_url = None

    # Find all links in the card
    links = card.find_all("a", href=True)
    for link in links:
        href = link.get("href", "")
        if "twitter.com/" in href or "x.com/" in href:
            twitter_url = href
        elif "linkedin.com/" in href:
            linkedin_url = href

    return twitter_url, linkedin_url


def _scrape_with_playwright(url: str, scroll_pause: float = 1.0, max_scrolls: int = 50) -> list[Speaker]:
    """
    Use Playwright to scrape JS-rendered pages with infinite scroll.
    Extracts speaker data including social links.
    """
    if not PLAYWRIGHT_AVAILABLE:
        logger.warning("Playwright not available for JS rendering")
        return []

    logger.info(f"Using Playwright to scrape: {url}")
    speakers = []

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until="networkidle", timeout=60000)

            # Scroll to load all content - use image count as indicator
            scroll_count = 0
            last_card_count = 0
            while scroll_count < max_scrolls:
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(scroll_pause)

                # Count profile images as proxy for loaded content
                try:
                    card_count = page.locator("img[src*='profile'], img[alt*='Profile'], img[alt*='Speaker'], .speaker-card, .speaker").count()
                except Exception:
                    card_count = 0

                if card_count == last_card_count and scroll_count > 5:
                    # No new content after multiple scrolls
                    break
                last_card_count = card_count
                scroll_count += 1

                if scroll_count % 10 == 0:
                    logger.info(f"  Scrolled {scroll_count} times, {card_count} cards loaded...")

            logger.info(f"Finished scrolling after {scroll_count} scrolls, {last_card_count} cards")

            # Get the fully loaded HTML
            html = page.content()
            browser.close()

            soup = BeautifulSoup(html, "html.parser")

            # Try EthCC-style cards first (directional-hover-card with profile photos)
            cards = soup.find_all("div", class_=lambda x: x and "directional-hover-card" in x and "group" in x)
            if cards:
                logger.info(f"Found {len(cards)} EthCC-style speaker cards")
                for card in cards:
                    speaker = _extract_ethcc_speaker(card, url)
                    if speaker:
                        speakers.append(speaker)
                if speakers:
                    return _dedupe_speakers(speakers)

            # Try to extract from Next.js streamed data
            streamed = _extract_nextjs_streamed_speakers(html, url)
            if streamed:
                return streamed

            # Fall back to standard DOM parsing
            for selector in SPEAKER_SELECTORS:
                found_cards = soup.select(selector)
                if len(found_cards) >= 3:
                    for card in found_cards:
                        speaker = _extract_speaker_from_card(card, url)
                        if speaker and speaker.name:
                            twitter, linkedin = _extract_social_links(card)
                            speaker.twitter_url = twitter
                            if linkedin:
                                speaker.linkedin_url = linkedin
                            speakers.append(speaker)
                    break

    except Exception as e:
        logger.error(f"Playwright scraping failed: {e}")
        return []

    return _dedupe_speakers(speakers)


def _extract_ethcc_speaker(card, source_url: str) -> Optional[Speaker]:
    """Extract speaker from EthCC-style card (directional-hover-card with profile photo)."""
    # Get profile image to extract name
    img = card.find("img", alt=lambda x: x and "Profile photo of" in str(x))
    if not img:
        return None

    name = img.get("alt", "").replace("Profile photo of", "").strip()
    if not name:
        return None

    # Get text content - format is {track}{name}{org}
    text = card.get_text(strip=True)

    # Find org - it comes after the name in the text
    company = None
    if name in text:
        idx = text.find(name) + len(name)
        company = text[idx:].strip()

    # Get social links
    twitter_url = None
    linkedin_url = None
    for link in card.find_all("a", href=True):
        href = link.get("href", "")
        if "twitter.com" in href or "x.com" in href:
            twitter_url = href.strip()
        elif "linkedin.com" in href:
            linkedin_url = href.strip()

    return Speaker(
        name=name,
        company=company,
        twitter_url=twitter_url,
        linkedin_url=linkedin_url,
        source_url=source_url
    )


def _dedupe_speakers(speakers: list[Speaker]) -> list[Speaker]:
    """Deduplicate speakers by name."""
    seen = set()
    unique = []
    for s in speakers:
        key = s.name.lower().strip()
        if key not in seen:
            seen.add(key)
            unique.append(s)
    logger.info(f"Deduplicated to {len(unique)} unique speakers")
    return unique


def _extract_nextjs_streamed_speakers(html: str, url: str) -> list[Speaker]:
    """
    Extract speakers from Next.js React Server Component streamed data.
    This handles sites like EthCC that stream JSON in script tags.
    """
    speakers = []

    # Find displayName, organization, and socialProfiles patterns
    # Pattern for speaker objects in streamed data
    speaker_pattern = re.compile(
        r'"displayName":"([^"]+)".*?"organization":"([^"]*)".*?"trackSlug":"([^"]*)".*?"socialProfiles":\[([^\]]*)\]',
        re.DOTALL
    )

    # Also try simpler pattern if the above doesn't match well
    name_matches = re.findall(r'"displayName":"([^"]+)"', html)
    org_matches = re.findall(r'"organization":"([^"]+)"', html)
    social_matches = re.findall(r'"socialProfiles":\[([^\]]*)\]', html)

    if not name_matches:
        return []

    logger.info(f"Found {len(name_matches)} speakers in Next.js streamed data")

    for i, name in enumerate(name_matches):
        org = org_matches[i] if i < len(org_matches) else None
        socials = social_matches[i] if i < len(social_matches) else ""

        # Parse social links
        twitter_url = None
        linkedin_url = None
        social_links = re.findall(r'"(https?://[^"]+)"', socials)
        for link in social_links:
            if "twitter.com/" in link or "x.com/" in link:
                twitter_url = link.strip()
            elif "linkedin.com/" in link:
                linkedin_url = link.strip()

        speakers.append(Speaker(
            name=name,
            company=org,
            twitter_url=twitter_url,
            linkedin_url=linkedin_url,
            source_url=url
        ))

    return speakers


def _extract_wordpress_paginated_speakers(base_url: str, headers: dict) -> list[Speaker]:
    """Extract speakers from WordPress sites with paginated speaker archive pages."""
    speakers = []
    speaker_urls = set()

    # Parse base URL to construct pagination URLs
    parsed = urlparse(base_url)
    base_path = parsed.path.rstrip('/')

    logger.info(f"Checking for WordPress pagination at {base_url}")

    for page in range(1, 50):  # Max 50 pages
        if page == 1:
            page_url = base_url
        else:
            page_url = f"{parsed.scheme}://{parsed.netloc}{base_path}/page/{page}/"

        try:
            r = requests.get(page_url, headers=headers, timeout=30, allow_redirects=True)
            if r.status_code != 200:
                break
        except requests.RequestException:
            break

        # Find individual speaker page URLs
        matches = re.findall(rf'href="({parsed.scheme}://{parsed.netloc}{base_path}/[^/]+/)"', r.text)
        new_urls = set(matches) - speaker_urls
        if not new_urls:
            break  # No new speakers found
        speaker_urls.update(new_urls)
        logger.info(f"Page {page}: {len(new_urls)} new speakers (total: {len(speaker_urls)})")

    if not speaker_urls:
        return []

    logger.info(f"Found {len(speaker_urls)} speaker pages, scraping...")

    # Scrape individual speaker pages
    for i, url in enumerate(speaker_urls):
        if i > 0 and i % 20 == 0:
            logger.info(f"  Scraped {i}/{len(speaker_urls)} speakers...")

        try:
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code != 200:
                continue

            soup = BeautifulSoup(r.text, "html.parser")

            # Try to find name from H1 or title
            h1 = soup.find("h1")
            name = h1.get_text(strip=True) if h1 else None
            if not name:
                title_tag = soup.find("title")
                if title_tag:
                    name = title_tag.get_text(strip=True).split(" - ")[0].strip()

            if not name or len(name) < 2:
                continue

            # Try to find title/company from various elements
            title = None
            company = None

            # Look for common WordPress speaker meta patterns
            for selector in [".speaker-title", ".job-title", ".position", ".role"]:
                elem = soup.select_one(selector)
                if elem:
                    title = elem.get_text(strip=True)
                    break

            for selector in [".speaker-company", ".company", ".organization"]:
                elem = soup.select_one(selector)
                if elem:
                    company = elem.get_text(strip=True)
                    break

            # Find social links
            twitter_url = None
            linkedin_url = None
            for link in soup.find_all("a", href=True):
                href = link.get("href", "")
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
                source_url=url
            ))

        except requests.RequestException:
            continue

    return speakers


def _extract_sitemap_speakers(base_url: str, headers: dict) -> list[Speaker]:
    """Extract speakers from sitemap (for JS-rendered sites like Coindesk events)."""
    parsed = urlparse(base_url)
    sitemap_url = f"{parsed.scheme}://{parsed.netloc}/sitemap.xml"

    try:
        r = requests.get(sitemap_url, headers=headers, timeout=30)
        if r.status_code != 200:
            return []
    except requests.RequestException:
        return []

    # Find sitemap index
    sitemap_match = re.search(r'<loc>([^<]+sitemap[^<]+\.xml)</loc>', r.text)
    if sitemap_match:
        sitemap_url = sitemap_match.group(1)
        try:
            r = requests.get(sitemap_url, headers=headers, timeout=30)
        except requests.RequestException:
            return []

    # Find speaker page URLs (pattern: /agenda/speaker/ or /speaker/)
    speaker_urls = re.findall(r'<loc>([^<]*/(?:agenda/)?speaker/[^<]+)</loc>', r.text)
    # Filter out non-individual pages
    speaker_urls = [u for u in speaker_urls if u.count('/') > 4]

    if not speaker_urls:
        return []

    logger.info(f"Found {len(speaker_urls)} speaker pages in sitemap, scraping...")

    speakers = []
    for i, url in enumerate(speaker_urls):
        if i > 0 and i % 50 == 0:
            logger.info(f"  Scraped {i}/{len(speaker_urls)} speakers...")

        try:
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code != 200:
                continue

            soup = BeautifulSoup(resp.text, "html.parser")

            # Extract name from H1
            h1 = soup.find("h1")
            if not h1:
                continue
            name = h1.get_text(strip=True)
            if not name or len(name) < 2:
                continue

            # Extract title and company from H2 elements
            h2s = soup.find_all("h2")
            h2_texts = [h.get_text(strip=True) for h in h2s if h.get_text(strip=True)]

            title = h2_texts[0] if h2_texts else None
            company = h2_texts[1] if len(h2_texts) > 1 else None

            # Fallback: extract company from meta description
            if not company:
                meta = soup.find("meta", {"name": "description"})
                if meta:
                    desc = meta.get("content", "")
                    match = re.search(r'(?:of|at|from)\s+([^,\.]+)', desc)
                    if match:
                        company = match.group(1).strip()

            speakers.append(Speaker(
                name=name,
                title=title,
                company=company,
                source_url=url
            ))

        except requests.RequestException:
            continue

    return speakers


def _extract_nextjs_speakers(html: str, url: str) -> list[Speaker]:
    """Extract speakers from Next.js __NEXT_DATA__ JSON."""
    match = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        html,
        re.DOTALL
    )
    if not match:
        return []

    try:
        data = json.loads(match.group(1))
        props = data.get("props", {}).get("pageProps", {})
    except json.JSONDecodeError:
        return []

    speakers_data = props.get("speakers", [])
    if not speakers_data:
        return []

    logger.info(f"Found Next.js data with {len(speakers_data)} speakers")

    speakers = []
    for s in speakers_data:
        name = s.get("title") or s.get("name") or s.get("fullName")
        if not name:
            continue

        # Handle custom_fields structure (Blockworks pattern)
        cf = s.get("custom_fields", {})

        job_field = cf.get("speaker_job", {})
        title = job_field.get("value") if isinstance(job_field, dict) else None

        company_field = cf.get("speaker_company", {})
        company = company_field.get("value") if isinstance(company_field, dict) else None

        # Fallback to direct fields
        if not title:
            title = s.get("tagLine") or s.get("title_position") or s.get("jobTitle")
        if not company:
            company = s.get("company") or s.get("organization")

        speakers.append(Speaker(
            name=name,
            title=title,
            company=company,
            source_url=url
        ))

    return speakers

# Common CSS selectors for speaker sections
SPEAKER_SELECTORS = [
    # Class-based patterns
    ".speaker",
    ".speaker-card",
    ".speaker-item",
    ".speakers-item",
    ".team-member",
    ".speaker-box",
    ".speaker-block",
    ".person",
    ".person-card",
    # ID-based patterns
    "[class*='speaker']",
    "[class*='Speaker']",
    # Semantic patterns
    "article.speaker",
    "div[data-speaker]",
    # Elementor patterns (common in WordPress sites)
    ".elementor-col-16",
    ".elementor-col-20",
    ".elementor-col-25",
    ".elementor-col-33",
]

# Patterns for name extraction
NAME_SELECTORS = [
    ".speaker-name",
    ".name",
    "h3",
    "h4",
    "h2",
    ".title",
    "[class*='name']",
    "strong",
]

# Patterns for title/role extraction
TITLE_SELECTORS = [
    ".speaker-title",
    ".speaker-role",
    ".role",
    ".position",
    ".job-title",
    "[class*='title']",
    "[class*='role']",
    "[class*='position']",
    "p",
    "span",
]

# Patterns for company extraction
COMPANY_SELECTORS = [
    ".speaker-company",
    ".company",
    ".organization",
    ".org",
    "[class*='company']",
    "[class*='organization']",
]


def scrape_speakers(url: str) -> list[Speaker]:
    """
    Scrape speaker information from an event page.

    Args:
        url: The URL of the speakers page

    Returns:
        List of Speaker objects with name, title, and company
    """
    logger.info(f"Scraping speakers from: {url}")

    # Check for site-specific scrapers
    if "coindesk.com" in url:
        from scrapers.consensus_scraper import scrape_consensus_speakers
        speakers = scrape_consensus_speakers(url)
        if speakers:
            return speakers

    if "dcblockchainsummit.com" in url:
        from scrapers.dcblockchainsummit_scraper import scrape_dcblockchainsummit_speakers
        speakers = scrape_dcblockchainsummit_speakers(url)
        if speakers:
            return speakers

    if "btcprague.com" in url:
        from scrapers.btcprague_scraper import scrape_btcprague_speakers
        speakers = scrape_btcprague_speakers(url)
        if speakers:
            return speakers

    if "ethdenver.com" in url:
        from scrapers.ethdenver_scraper import scrape_ethdenver_speakers
        speakers = scrape_ethdenver_speakers(url)
        if speakers:
            return speakers

    # Use realistic browser headers to avoid blocks
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        session = requests.Session()
        response = session.get(url, headers=headers, timeout=30, allow_redirects=True)
        response.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"Failed to fetch URL: {e}")
        return []

    # Try Next.js data extraction first (for React-based sites)
    nextjs_speakers = _extract_nextjs_speakers(response.text, url)
    if nextjs_speakers:
        logger.info(f"Extracted {len(nextjs_speakers)} speakers from Next.js data")
        return nextjs_speakers

    soup = BeautifulSoup(response.text, "html.parser")
    speakers = []

    # Try each selector pattern to find speaker cards
    speaker_cards = []
    for selector in SPEAKER_SELECTORS:
        try:
            cards = soup.select(selector)
            if cards:
                logger.debug(f"Found {len(cards)} elements with selector: {selector}")
                speaker_cards = cards
                break
        except Exception:
            continue

    if not speaker_cards:
        logger.warning("No speaker cards found with standard selectors. Trying fallback...")
        speaker_cards = _fallback_speaker_detection(soup)

    for card in speaker_cards:
        speaker = _extract_speaker_from_card(card, url)
        if speaker and speaker.name:
            speakers.append(speaker)

    # Deduplicate by name
    seen_names = set()
    unique_speakers = []
    for speaker in speakers:
        normalized_name = speaker.name.lower().strip()
        if normalized_name not in seen_names:
            seen_names.add(normalized_name)
            unique_speakers.append(speaker)

    # Check if page might have more content (JS-rendered with infinite scroll)
    # Indicators: few speakers found, or page has script tags suggesting React/Next.js
    is_js_heavy = "__NEXT" in response.text or "react" in response.text.lower() or "firebase" in response.text.lower()
    has_pagination = 'rel="next"' in response.text or "/page/2" in response.text

    # If few speakers or JS-heavy page, try additional extraction methods
    if len(unique_speakers) <= 50 or (is_js_heavy and len(unique_speakers) < 100):
        # Try sitemap extraction first (faster, for sites like Coindesk)
        if len(unique_speakers) <= 5:
            logger.info("Few speakers found. Trying sitemap extraction...")
            sitemap_speakers = _extract_sitemap_speakers(url, headers)
            if sitemap_speakers and len(sitemap_speakers) > len(unique_speakers):
                logger.info(f"Extracted {len(sitemap_speakers)} speakers from sitemap")
                return sitemap_speakers

            # Try WordPress pagination
            if has_pagination:
                logger.info("WordPress pagination detected. Trying paginated extraction...")
                wp_speakers = _extract_wordpress_paginated_speakers(url, headers)
                if wp_speakers and len(wp_speakers) > len(unique_speakers):
                    logger.info(f"Extracted {len(wp_speakers)} speakers from paginated pages")
                    return wp_speakers

        # Try Playwright for JS-rendered sites with infinite scroll
        if PLAYWRIGHT_AVAILABLE and is_js_heavy:
            logger.info("JS-heavy page detected. Trying Playwright for full content...")
            playwright_speakers = _scrape_with_playwright(url)
            if playwright_speakers and len(playwright_speakers) > len(unique_speakers):
                logger.info(f"Playwright extracted {len(playwright_speakers)} speakers (vs {len(unique_speakers)} initial)")
                return playwright_speakers

    logger.info(f"Extracted {len(unique_speakers)} unique speakers")
    return unique_speakers


def _fallback_speaker_detection(soup: BeautifulSoup) -> list:
    """
    Fallback detection for non-standard speaker layouts.
    Looks for repeated structures with person-like content.
    """
    candidates = []

    # Look for divs/articles with images and text that could be speakers
    for container in soup.find_all(["div", "article", "li", "section"]):
        # Check if it has an image and some text
        has_image = container.find("img") is not None
        text_content = container.get_text(strip=True)

        # Heuristic: speaker cards usually have 20-500 chars of text
        if has_image and 20 < len(text_content) < 500:
            # Check if parent has multiple similar children (grid pattern)
            parent = container.parent
            if parent:
                siblings = parent.find_all(container.name, recursive=False)
                if len(siblings) >= 3:  # Likely a speaker grid
                    candidates.extend(siblings)
                    break

    return candidates


def _extract_speaker_from_card(card, source_url: str) -> Optional[Speaker]:
    """Extract speaker information from a card element."""
    name = None
    title = None
    company = None

    # Check if this is an Elementor column (WordPress page builder)
    is_elementor = any("elementor" in c for c in card.get("class", []))

    if is_elementor:
        # Elementor pattern: H2[0] = Name, Text widget = Title, H2[1] = Company
        h2_elements = card.find_all("h2", class_="elementor-heading-title")
        h2_texts = [h.get_text(strip=True).rstrip("\u200b") for h in h2_elements]

        # Get text widget content (job titles)
        text_widgets = card.select(".elementor-widget-text-editor")
        widget_texts = [w.get_text(strip=True) for w in text_widgets if w.get_text(strip=True)]

        # First H2 is always the name
        if h2_texts:
            name = h2_texts[0]

        # Second H2 is always the company (if exists)
        if len(h2_texts) > 1:
            company = h2_texts[1]

        # Text widget is the job title
        if widget_texts:
            title = widget_texts[0]

        if not name:
            return None

        return Speaker(
            name=name,
            title=title,
            company=company,
            source_url=source_url
        )

    # Standard extraction for non-Elementor sites
    # Extract name
    for selector in NAME_SELECTORS:
        try:
            elem = card.select_one(selector)
            if elem:
                text = elem.get_text(strip=True)
                # Name should be 2-50 chars and look like a name
                if 2 < len(text) < 50 and _looks_like_name(text):
                    name = text
                    break
        except Exception:
            continue

    # If no name found via selectors, try first significant text
    if not name:
        for elem in card.find_all(["h2", "h3", "h4", "strong", "b"]):
            text = elem.get_text(strip=True)
            if 2 < len(text) < 50 and _looks_like_name(text):
                name = text
                break

    if not name:
        return None

    # Extract title and company
    all_text_parts = []
    for elem in card.find_all(["p", "span", "div"]):
        text = elem.get_text(strip=True)
        if text and text != name and len(text) < 200:
            all_text_parts.append(text)

    # Try specific selectors for title
    for selector in TITLE_SELECTORS:
        try:
            elem = card.select_one(selector)
            if elem:
                text = elem.get_text(strip=True)
                if text and text != name and len(text) < 100:
                    title = text
                    break
        except Exception:
            continue

    # Try specific selectors for company
    for selector in COMPANY_SELECTORS:
        try:
            elem = card.select_one(selector)
            if elem:
                text = elem.get_text(strip=True)
                if text and text != name and text != title:
                    company = text
                    break
        except Exception:
            continue

    # If no explicit company, try to parse from title (common format: "CEO at Company")
    if not company and title:
        company = _extract_company_from_title(title)

    # If still no title/company, use first text parts
    if not title and all_text_parts:
        title = all_text_parts[0]
    if not company and len(all_text_parts) > 1:
        company = all_text_parts[1]

    return Speaker(
        name=name,
        title=title,
        company=company,
        source_url=source_url
    )


def _looks_like_name(text: str) -> bool:
    """Check if text looks like a person's name."""
    # Should have at least 2 words (first + last name)
    words = text.split()
    if len(words) < 2:
        return False

    # Should not be too long (likely a title or description)
    if len(words) > 5:
        return False

    # Should not contain common non-name words
    non_name_words = ["the", "and", "of", "at", "for", "in", "on", "@", "&", "|"]
    if any(w.lower() in non_name_words for w in words):
        return False

    # Should not contain company-related words
    company_words = [
        "capital", "management", "labs", "ventures", "partners", "group",
        "inc", "corp", "llc", "ltd", "foundation", "fund", "bank", "finance",
        "consulting", "advisory", "holdings", "investments", "asset", "assets",
        "digital", "crypto", "blockchain", "network", "protocol", "exchange",
        "technology", "technologies", "solutions", "services", "global",
        "international", "institute", "association", "council", "chamber",
    ]
    if any(w.lower() in company_words for w in words):
        return False

    # Should start with capital letter
    if not text[0].isupper():
        return False

    return True


def _extract_company_from_title(title: str) -> Optional[str]:
    """Extract company name from title like 'CEO at Company' or 'CEO, Company'."""
    patterns = [
        r"(?:at|@)\s+(.+)$",           # "CEO at Company"
        r",\s+(.+)$",                   # "CEO, Company"
        r"\|\s*(.+)$",                  # "CEO | Company"
        r"-\s+(.+)$",                   # "CEO - Company"
    ]

    for pattern in patterns:
        match = re.search(pattern, title, re.IGNORECASE)
        if match:
            return match.group(1).strip()

    return None
