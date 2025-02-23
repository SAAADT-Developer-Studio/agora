from datetime import datetime, timedelta
from app import config

def is_recent(date: datetime) -> bool:
    """Check if the date is from the last 24 hours."""
    return date > datetime.now(date.tzinfo) - timedelta(**config.TIME_WINDOW)