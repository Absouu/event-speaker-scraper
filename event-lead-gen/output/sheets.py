"""Google Sheets export for HubSpot-ready speaker data."""

import logging
from typing import Optional

from config import GOOGLE_CREDENTIALS_PATH
from models import Speaker

logger = logging.getLogger(__name__)

# HubSpot-compatible column headers
HEADERS = [
    "First Name",
    "Last Name",
    "Email",
    "Job Title",
    "Company Name",
    "LinkedIn URL",
    "Twitter URL",
    "Source Event"
]


def get_sheets_client():
    """Get authenticated Google Sheets client."""
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError:
        raise ImportError(
            "gspread not installed. Run: pip install gspread google-auth"
        )

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    credentials = Credentials.from_service_account_file(
        GOOGLE_CREDENTIALS_PATH,
        scopes=scopes
    )

    return gspread.authorize(credentials)


def sanitize_for_sheets(text) -> str:
    """Sanitize any value for Google Sheets."""
    if text is None:
        return ""
    text = str(text)
    # Replace newlines, tabs, carriage returns with spaces
    text = text.replace("\n", " ").replace("\r", " ").replace("\t", " ")
    # Remove multiple spaces
    text = " ".join(text.split())
    # Limit length
    if len(text) > 500:
        text = text[:500]
    return text


def format_speakers_for_sheets(
    speakers: list[Speaker],
    source_event: str
) -> list[list[str]]:
    """Format speakers as rows for Google Sheets."""
    rows = []
    for speaker in speakers:
        row = [
            sanitize_for_sheets(speaker.first_name),
            sanitize_for_sheets(speaker.last_name),
            sanitize_for_sheets(speaker.email),
            sanitize_for_sheets(speaker.title),
            sanitize_for_sheets(speaker.company),
            sanitize_for_sheets(speaker.linkedin_url),
            sanitize_for_sheets(speaker.twitter_url),
            sanitize_for_sheets(source_event),
        ]
        rows.append(row)
    return rows


def export_to_sheet(
    speakers: list[Speaker],
    sheet_name: str,
    source_event: Optional[str] = None
) -> int:
    """
    Export speakers to a new Google Sheet.

    Args:
        speakers: List of Speaker objects to export
        sheet_name: Name for the new spreadsheet
        source_event: Event name to include in Source Event column

    Returns:
        Number of speakers exported
    """
    import gspread

    if not speakers:
        logger.info("No speakers to export")
        return 0

    source_event = source_event or sheet_name

    logger.info(f"Exporting {len(speakers)} speakers to Google Sheet: {sheet_name}")

    try:
        client = get_sheets_client()
    except Exception as e:
        logger.error(f"Failed to authenticate with Google: {e}")
        raise

    # Create new spreadsheet
    try:
        spreadsheet = client.create(sheet_name)
        logger.info(f"Created spreadsheet: {spreadsheet.url}")
    except Exception as e:
        logger.error(f"Failed to create spreadsheet: {e}")
        raise

    # Get the first worksheet
    sheet = spreadsheet.sheet1
    sheet.update_title("Speakers")

    # Add headers
    sheet.append_row(HEADERS)

    # Format and add speaker rows
    rows = format_speakers_for_sheets(speakers, source_event)
    if rows:
        sheet.append_rows(rows)

    # Make spreadsheet accessible
    try:
        spreadsheet.share(None, perm_type='anyone', role='reader')
        logger.info("Made spreadsheet publicly readable")
    except Exception as e:
        logger.warning(f"Could not share spreadsheet: {e}")

    logger.info(f"Exported {len(speakers)} speakers to: {spreadsheet.url}")
    print(f"\nGoogle Sheet URL: {spreadsheet.url}")

    return len(speakers)


def export_to_existing_sheet(
    speakers: list[Speaker],
    spreadsheet_id: str,
    worksheet_name: str,
    source_event: Optional[str] = None
) -> int:
    """
    Export speakers to an existing Google Sheet (adds as new worksheet).

    Args:
        speakers: List of Speaker objects to export
        spreadsheet_id: ID of existing spreadsheet
        worksheet_name: Name for the new worksheet
        source_event: Event name to include in Source Event column

    Returns:
        Number of speakers exported
    """
    import gspread

    if not speakers:
        logger.info("No speakers to export")
        return 0

    source_event = source_event or worksheet_name

    logger.info(f"Adding worksheet '{worksheet_name}' to existing spreadsheet...")

    try:
        client = get_sheets_client()
        spreadsheet = client.open_by_key(spreadsheet_id)
    except Exception as e:
        logger.error(f"Failed to open spreadsheet: {e}")
        raise

    # Create new worksheet or get existing
    try:
        sheet = spreadsheet.worksheet(worksheet_name)
        logger.info(f"Worksheet '{worksheet_name}' already exists, appending...")
    except gspread.WorksheetNotFound:
        sheet = spreadsheet.add_worksheet(
            title=worksheet_name,
            rows=max(1000, len(speakers) + 100),
            cols=len(HEADERS)
        )
        # Add headers for new sheet
        sheet.append_row(HEADERS)

    # Format and add speaker rows
    rows = format_speakers_for_sheets(speakers, source_event)
    if rows:
        sheet.append_rows(rows)

    logger.info(f"Exported {len(speakers)} speakers to worksheet '{worksheet_name}'")
    print(f"\nGoogle Sheet URL: {spreadsheet.url}")

    return len(speakers)
