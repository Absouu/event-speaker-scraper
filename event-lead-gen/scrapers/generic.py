"""Generic speaker scraper for event websites."""

import json
import logging
import re
from typing import Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from models import Speaker

logger = logging.getLogger(__name__)


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

    # If no speakers found, try sitemap extraction (for JS-rendered sites)
    if len(unique_speakers) <= 1:
        logger.info("Trying sitemap extraction for JS-rendered site...")
        sitemap_speakers = _extract_sitemap_speakers(url, headers)
        if sitemap_speakers:
            logger.info(f"Extracted {len(sitemap_speakers)} speakers from sitemap")
            return sitemap_speakers

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
