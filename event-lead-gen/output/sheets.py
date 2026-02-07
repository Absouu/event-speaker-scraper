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


def update_existing_worksheet(
    speakers: list[Speaker],
    spreadsheet_id: str,
    worksheet_name: str,
    source_event: Optional[str] = None
) -> int:
    """
    Update an existing worksheet (clears and replaces all data).

    Args:
        speakers: List of Speaker objects to export
        spreadsheet_id: ID of existing spreadsheet
        worksheet_name: Name of the worksheet to update
        source_event: Event name to include in Source Event column

    Returns:
        Number of speakers exported
    """
    import gspread

    if not speakers:
        logger.info("No speakers to export")
        return 0

    source_event = source_event or worksheet_name

    logger.info(f"Updating worksheet '{worksheet_name}'...")

    try:
        client = get_sheets_client()
        spreadsheet = client.open_by_key(spreadsheet_id)
    except Exception as e:
        logger.error(f"Failed to open spreadsheet: {e}")
        raise

    # Get existing worksheet
    try:
        sheet = spreadsheet.worksheet(worksheet_name)
    except gspread.WorksheetNotFound:
        logger.error(f"Worksheet '{worksheet_name}' not found")
        raise

    # Clear existing data
    sheet.clear()

    # Add headers
    sheet.append_row(HEADERS)

    # Format and add speaker rows
    rows = format_speakers_for_sheets(speakers, source_event)
    if rows:
        sheet.append_rows(rows)

    logger.info(f"Updated {len(speakers)} speakers in worksheet '{worksheet_name}'")

    return len(speakers)


def read_speakers_from_worksheet(
    spreadsheet_id: str,
    worksheet_name: str
) -> list[Speaker]:
    """
    Read speakers from an existing worksheet.

    Args:
        spreadsheet_id: ID of the spreadsheet
        worksheet_name: Name of the worksheet to read

    Returns:
        List of Speaker objects
    """
    import gspread

    try:
        client = get_sheets_client()
        spreadsheet = client.open_by_key(spreadsheet_id)
        sheet = spreadsheet.worksheet(worksheet_name)
    except Exception as e:
        logger.error(f"Failed to open worksheet: {e}")
        raise

    # Get all values
    values = sheet.get_all_values()
    if len(values) < 2:
        return []

    headers = values[0]
    speakers = []

    # Find column indices
    col_map = {h: i for i, h in enumerate(headers)}

    for row in values[1:]:
        if not row or not any(row):
            continue

        first_name = row[col_map.get("First Name", 0)] if col_map.get("First Name") is not None and len(row) > col_map.get("First Name", 0) else ""
        last_name = row[col_map.get("Last Name", 1)] if col_map.get("Last Name") is not None and len(row) > col_map.get("Last Name", 1) else ""
        email = row[col_map.get("Email", 2)] if col_map.get("Email") is not None and len(row) > col_map.get("Email", 2) else ""
        title = row[col_map.get("Job Title", 3)] if col_map.get("Job Title") is not None and len(row) > col_map.get("Job Title", 3) else ""
        company = row[col_map.get("Company Name", 4)] if col_map.get("Company Name") is not None and len(row) > col_map.get("Company Name", 4) else ""
        linkedin = row[col_map.get("LinkedIn URL", 5)] if col_map.get("LinkedIn URL") is not None and len(row) > col_map.get("LinkedIn URL", 5) else ""
        twitter = row[col_map.get("Twitter URL", 6)] if col_map.get("Twitter URL") is not None and len(row) > col_map.get("Twitter URL", 6) else ""

        name = f"{first_name} {last_name}".strip()

        speakers.append(Speaker(
            name=name,
            title=title,
            company=company,
            email=email,
            linkedin_url=linkedin,
            twitter_url=twitter
        ))

    return speakers
