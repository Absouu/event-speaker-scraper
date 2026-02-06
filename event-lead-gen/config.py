"""Configuration management for event lead generation."""

import os

# Load environment variables (dotenv is optional)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv not installed, use system env vars

# =============================================================================
# API CONFIGURATION
# =============================================================================

APOLLO_API_KEY = os.getenv("APOLLO_API_KEY", "")
GOOGLE_CREDENTIALS_PATH = os.getenv(
    "GOOGLE_CREDENTIALS_PATH",
    "/Users/abhinavgaur/Desktop/announcement_scraper/config/google-credentials.json"
)

# =============================================================================
# VALIDATION
# =============================================================================

def validate_apollo_config() -> bool:
    """Check if Apollo API is configured."""
    return bool(APOLLO_API_KEY)

def validate_google_config() -> bool:
    """Check if Google credentials exist."""
    return os.path.exists(GOOGLE_CREDENTIALS_PATH)
