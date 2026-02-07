#!/usr/bin/env python3
"""
Enrich existing worksheets with Apollo emails.

Usage:
    python enrich_existing.py "Worksheet Name"
    python enrich_existing.py --all  # Enrich all worksheets with 0 emails
"""

import argparse
import logging
import sys
import time

from output.sheets import (
    get_sheets_client,
    read_speakers_from_worksheet,
    update_existing_worksheet
)
from enrichment.apollo import enrich_speakers
from config import validate_apollo_config

# Spreadsheet ID
SPREADSHEET_ID = "1cGwhcZjMpz34BwSAGDZhytey8VZlBjLgzZ8WNmkLDKo"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)


def get_worksheets_needing_enrichment():
    """Find worksheets with speakers but no emails."""
    client = get_sheets_client()
    spreadsheet = client.open_by_key(SPREADSHEET_ID)

    needs_enrichment = []

    for ws in spreadsheet.worksheets():
        try:
            vals = ws.get_all_values()
            row_count = len(vals) - 1 if vals else 0
            if row_count < 1:
                continue

            headers = vals[0]
            email_idx = headers.index("Email") if "Email" in headers else -1

            if email_idx < 0:
                continue

            emails_filled = 0
            for row in vals[1:]:
                if len(row) > email_idx and row[email_idx]:
                    emails_filled += 1

            # If less than 10% have emails, needs enrichment
            if emails_filled < row_count * 0.1:
                needs_enrichment.append({
                    "name": ws.title,
                    "speakers": row_count,
                    "emails": emails_filled
                })
        except Exception as e:
            logger.warning(f"Error checking {ws.title}: {e}")

    return needs_enrichment


def enrich_worksheet(worksheet_name: str) -> int:
    """Read speakers from worksheet, enrich with Apollo, update worksheet."""
    logger.info(f"Enriching worksheet: {worksheet_name}")

    # Read existing speakers
    speakers = read_speakers_from_worksheet(SPREADSHEET_ID, worksheet_name)
    if not speakers:
        logger.warning(f"No speakers found in {worksheet_name}")
        return 0

    logger.info(f"Read {len(speakers)} speakers from {worksheet_name}")

    # Count already enriched
    already_enriched = sum(1 for s in speakers if s.email)
    logger.info(f"Already have emails for {already_enriched}/{len(speakers)} speakers")

    # Enrich with Apollo
    speakers = enrich_speakers(speakers)

    # Count new enrichment
    now_enriched = sum(1 for s in speakers if s.email)
    logger.info(f"After enrichment: {now_enriched}/{len(speakers)} speakers have emails")

    # Update worksheet
    update_existing_worksheet(speakers, SPREADSHEET_ID, worksheet_name, worksheet_name)

    return now_enriched - already_enriched


def main():
    parser = argparse.ArgumentParser(description="Enrich existing worksheets with Apollo emails")
    parser.add_argument("worksheet", nargs="?", help="Name of worksheet to enrich")
    parser.add_argument("--all", action="store_true", help="Enrich all worksheets with 0 emails")
    parser.add_argument("--list", action="store_true", help="List worksheets needing enrichment")

    args = parser.parse_args()

    if not validate_apollo_config():
        logger.error("APOLLO_API_KEY not set in .env")
        sys.exit(1)

    if args.list:
        worksheets = get_worksheets_needing_enrichment()
        print("\nWorksheets needing enrichment:")
        for ws in worksheets:
            print(f"  {ws['name']}: {ws['speakers']} speakers, {ws['emails']} with emails")
        return

    if args.all:
        worksheets = get_worksheets_needing_enrichment()
        print(f"\nFound {len(worksheets)} worksheets needing enrichment")

        for ws in worksheets:
            print(f"\n{'='*60}")
            print(f"Processing: {ws['name']} ({ws['speakers']} speakers)")
            print('='*60)

            try:
                new_emails = enrich_worksheet(ws['name'])
                print(f"Added {new_emails} new emails")
            except Exception as e:
                logger.error(f"Failed to enrich {ws['name']}: {e}")

            # Rate limit between worksheets
            time.sleep(2)

        print("\nDone!")
        return

    if args.worksheet:
        enrich_worksheet(args.worksheet)
        print("\nDone!")
        return

    parser.print_help()


if __name__ == "__main__":
    main()
