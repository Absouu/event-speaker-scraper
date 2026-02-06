#!/usr/bin/env python3
"""
Event Speaker Lead Gen Tool

Scrapes event speaker pages, enriches with emails via Apollo,
and outputs to Google Sheet in HubSpot-ready format.

Usage:
    python main.py "https://event.com/speakers/"
    python main.py URL --dry-run
    python main.py URL --output speakers.csv
    python main.py URL --skip-enrichment
    python main.py URL --sheet-name "Event Name 2026"
    python main.py URL --spreadsheet-id "1abc123..." --sheet-name "Event Name"
"""

import argparse
import csv
import logging
import sys
from urllib.parse import urlparse

from models import Speaker
from scrapers.generic import scrape_speakers
from enrichment.apollo import enrich_speakers
from output.sheets import export_to_sheet, export_to_existing_sheet
from config import validate_apollo_config, validate_google_config

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)


def extract_event_name(url: str) -> str:
    """Extract a reasonable event name from URL."""
    parsed = urlparse(url)

    # Try to get from path
    path_parts = [p for p in parsed.path.split("/") if p]
    if path_parts:
        # Skip common words like 'speakers', 'speaker'
        for part in path_parts:
            if part.lower() not in ["speakers", "speaker", "schedule", "agenda"]:
                # Clean up and title case
                name = part.replace("-", " ").replace("_", " ").title()
                return name

    # Fall back to domain name
    domain = parsed.netloc.replace("www.", "")
    name = domain.split(".")[0].replace("-", " ").title()
    return name


def export_to_csv(speakers: list[Speaker], filename: str, source_event: str) -> None:
    """Export speakers to CSV file."""
    headers = [
        "First Name", "Last Name", "Email", "Job Title",
        "Company Name", "LinkedIn URL", "Source Event"
    ]

    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)

        for speaker in speakers:
            writer.writerow([
                speaker.first_name or "",
                speaker.last_name or "",
                speaker.email or "",
                speaker.title or "",
                speaker.company or "",
                speaker.linkedin_url or "",
                source_event
            ])

    logger.info(f"Exported {len(speakers)} speakers to {filename}")


def print_speakers_table(speakers: list[Speaker]) -> None:
    """Print speakers in a formatted table."""
    print("\n" + "=" * 80)
    print(f"{'Name':<25} {'Title':<30} {'Company':<20}")
    print("=" * 80)

    for speaker in speakers:
        name = (speaker.name or "")[:24]
        title = (speaker.title or "")[:29]
        company = (speaker.company or "")[:19]
        print(f"{name:<25} {title:<30} {company:<20}")

    print("=" * 80)
    print(f"Total: {len(speakers)} speakers\n")


def main():
    parser = argparse.ArgumentParser(
        description="Scrape event speakers and enrich with contact data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py "https://event.com/speakers/"
  python main.py URL --dry-run
  python main.py URL --output speakers.csv
  python main.py URL --skip-enrichment
  python main.py URL --sheet-name "DAF London 2026"
        """
    )

    parser.add_argument(
        "url",
        help="URL of the event speakers page"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview scraped data without saving"
    )
    parser.add_argument(
        "--output", "-o",
        help="Export to CSV file instead of Google Sheet"
    )
    parser.add_argument(
        "--skip-enrichment",
        action="store_true",
        help="Skip Apollo enrichment (scrape only)"
    )
    parser.add_argument(
        "--sheet-name",
        help="Custom name for Google Sheet (default: derived from URL)"
    )
    parser.add_argument(
        "--spreadsheet-id",
        help="Add to existing spreadsheet by ID instead of creating new"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging"
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Validate URL
    parsed_url = urlparse(args.url)
    if not parsed_url.scheme or not parsed_url.netloc:
        logger.error("Invalid URL. Please provide a complete URL (https://...)")
        sys.exit(1)

    # Extract event name for sheet naming
    event_name = args.sheet_name or extract_event_name(args.url)
    logger.info(f"Event: {event_name}")

    # Step 1: Scrape speakers
    logger.info("Step 1: Scraping speakers...")
    speakers = scrape_speakers(args.url)

    if not speakers:
        logger.error("No speakers found. The page structure may not be supported.")
        sys.exit(1)

    # Data quality check
    missing_title = sum(1 for s in speakers if not s.title)
    missing_company = sum(1 for s in speakers if not s.company)
    if missing_title > len(speakers) * 0.1 or missing_company > len(speakers) * 0.1:
        logger.warning(f"Data quality issue: {missing_title} missing titles, {missing_company} missing companies")
        logger.warning("Consider checking if the scraper is extracting all fields correctly")

    print_speakers_table(speakers)

    # Step 2: Enrich with Apollo (unless skipped)
    if not args.skip_enrichment:
        if not validate_apollo_config():
            logger.warning("APOLLO_API_KEY not set. Skipping enrichment.")
            logger.info("Set APOLLO_API_KEY in .env file to enable email enrichment.")
        else:
            logger.info("Step 2: Enriching with Apollo...")
            speakers = enrich_speakers(speakers)

            # Show enrichment results
            enriched = sum(1 for s in speakers if s.email)
            logger.info(f"Enriched {enriched}/{len(speakers)} speakers with emails")
    else:
        logger.info("Step 2: Skipping enrichment (--skip-enrichment)")

    # Step 3: Output
    if args.dry_run:
        logger.info("Dry run - not saving output")
        print("\nEnriched data preview:")
        for speaker in speakers[:5]:  # Show first 5
            print(f"  {speaker.name}: {speaker.email or 'No email'} | {speaker.linkedin_url or 'No LinkedIn'}")
        if len(speakers) > 5:
            print(f"  ... and {len(speakers) - 5} more")

    elif args.output:
        # Export to CSV
        logger.info(f"Step 3: Exporting to CSV...")
        export_to_csv(speakers, args.output, event_name)
        print(f"\nCSV saved: {args.output}")

    else:
        # Export to Google Sheet
        if not validate_google_config():
            logger.error(f"Google credentials not found at configured path.")
            logger.error("Set GOOGLE_CREDENTIALS_PATH in .env or use --output for CSV export.")
            sys.exit(1)

        logger.info("Step 3: Exporting to Google Sheet...")
        if args.spreadsheet_id:
            # Add to existing spreadsheet
            export_to_existing_sheet(
                speakers,
                args.spreadsheet_id,
                event_name,
                event_name
            )
        else:
            # Create new spreadsheet
            sheet_name = f"Event Leads - {event_name}"
            export_to_sheet(speakers, sheet_name, event_name)

    logger.info("Done!")


if __name__ == "__main__":
    main()
