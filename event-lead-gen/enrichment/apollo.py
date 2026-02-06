"""Apollo.io People Enrichment API integration."""

import logging
import time
from typing import Optional

import requests

from config import APOLLO_API_KEY
from models import Speaker

logger = logging.getLogger(__name__)

APOLLO_BULK_MATCH_URL = "https://api.apollo.io/v1/people/bulk_match"
BATCH_SIZE = 10  # Apollo allows up to 10 per request
RATE_LIMIT_DELAY = 3.0  # Seconds between batches (avoid rate limits)


def enrich_speakers(speakers: list[Speaker]) -> list[Speaker]:
    """
    Enrich speakers with email and LinkedIn data from Apollo.

    Args:
        speakers: List of Speaker objects to enrich

    Returns:
        Same list with email and linkedin_url populated where found
    """
    if not APOLLO_API_KEY:
        logger.error("APOLLO_API_KEY not configured. Skipping enrichment.")
        return speakers

    if not speakers:
        return speakers

    logger.info(f"Enriching {len(speakers)} speakers via Apollo...")

    # Process in batches
    enriched_count = 0
    for i in range(0, len(speakers), BATCH_SIZE):
        batch = speakers[i:i + BATCH_SIZE]
        batch_num = (i // BATCH_SIZE) + 1
        total_batches = (len(speakers) + BATCH_SIZE - 1) // BATCH_SIZE

        logger.info(f"Processing batch {batch_num}/{total_batches}...")

        try:
            _enrich_batch(batch)
            enriched_count += sum(1 for s in batch if s.email)
        except Exception as e:
            logger.error(f"Error enriching batch {batch_num}: {e}")

        # Rate limiting between batches
        if i + BATCH_SIZE < len(speakers):
            time.sleep(RATE_LIMIT_DELAY)

    logger.info(f"Enrichment complete. Found emails for {enriched_count}/{len(speakers)} speakers.")
    return speakers


def _enrich_batch(speakers: list[Speaker]) -> None:
    """Enrich a single batch of speakers (up to 10)."""
    # Build request payload
    details = []
    for speaker in speakers:
        detail = {
            "first_name": speaker.first_name or "",
            "last_name": speaker.last_name or "",
        }
        if speaker.company:
            detail["organization_name"] = speaker.company
        details.append(detail)

    payload = {
        "reveal_personal_emails": True,
        "details": details
    }

    headers = {
        "Content-Type": "application/json",
        "Cache-Control": "no-cache",
        "x-api-key": APOLLO_API_KEY
    }

    try:
        response = requests.post(
            APOLLO_BULK_MATCH_URL,
            json=payload,
            headers=headers,
            timeout=30
        )
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.HTTPError as e:
        if response.status_code == 429:
            logger.warning("Rate limited by Apollo. Waiting 60 seconds...")
            time.sleep(60)
            # Retry once
            response = requests.post(
                APOLLO_BULK_MATCH_URL,
                json=payload,
                headers=headers,
                timeout=30
            )
            response.raise_for_status()
            data = response.json()
        else:
            raise
    except requests.RequestException as e:
        logger.error(f"Apollo API request failed: {e}")
        return

    # Parse results and update speakers
    matches = data.get("matches", [])

    for i, match in enumerate(matches):
        if i >= len(speakers):
            break

        if match:
            # Extract email (prefer work email, then personal)
            email = match.get("email")
            if not email:
                personal_emails = match.get("personal_emails", [])
                if personal_emails:
                    email = personal_emails[0]

            if email:
                speakers[i].email = email

            # Extract LinkedIn URL
            linkedin = match.get("linkedin_url")
            if linkedin:
                speakers[i].linkedin_url = linkedin

            # Update name if Apollo has better data
            if match.get("first_name"):
                speakers[i].first_name = match.get("first_name")
            if match.get("last_name"):
                speakers[i].last_name = match.get("last_name")


def enrich_single_speaker(speaker: Speaker) -> Speaker:
    """
    Enrich a single speaker (convenience wrapper).
    Less efficient than batch, use for testing only.
    """
    return enrich_speakers([speaker])[0]
