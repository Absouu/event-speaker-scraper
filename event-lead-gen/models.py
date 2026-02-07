"""Data models for event lead generation."""

from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime, timezone


@dataclass
class Speaker:
    """Represents an event speaker."""
    name: str
    title: Optional[str] = None
    company: Optional[str] = None
    source_url: Optional[str] = None

    # Social links (from scraping)
    twitter_url: Optional[str] = None

    # Enrichment fields (populated by Apollo)
    email: Optional[str] = None
    linkedin_url: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None

    # Metadata
    extracted_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __post_init__(self):
        """Parse first/last name from full name if not provided."""
        if self.name and not self.first_name:
            parts = self.name.strip().split()
            if parts:
                self.first_name = parts[0]
                self.last_name = " ".join(parts[1:]) if len(parts) > 1 else ""
