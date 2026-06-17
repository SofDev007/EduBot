"""
Timezone Utility Module
Handles all timezone conversions globally for the project
"""

from datetime import datetime, timezone, timedelta
from pytz import timezone as pytz_timezone
import os

# Default timezone - set to IST (Asia/Kolkata)
# Can be overridden via .env: TZ_NAME=Asia/Kolkata
DEFAULT_TZ_NAME = os.environ.get('TZ_NAME', 'Asia/Kolkata')
LOCAL_TIMEZONE = pytz_timezone(DEFAULT_TZ_NAME)

def get_local_time():
    """
    Get current time in local timezone (IST by default)
    
    Returns:
        datetime: Current datetime in local timezone (timezone-aware)
    """
    utc_now = datetime.now(timezone.utc)
    return utc_now.astimezone(LOCAL_TIMEZONE)

def utc_to_local(utc_dt):
    """
    Convert UTC datetime to local timezone
    
    Args:
        utc_dt: datetime object in UTC
        
    Returns:
        datetime: datetime object in local timezone
    """
    if utc_dt is None:
        return None
    
    # If already timezone-aware, convert to UTC first
    if utc_dt.tzinfo is not None:
        utc_dt = utc_dt.astimezone(timezone.utc).replace(tzinfo=None)
    
    # Make it UTC-aware and convert to local timezone
    utc_aware = utc_dt.replace(tzinfo=timezone.utc)
    return utc_aware.astimezone(LOCAL_TIMEZONE)

def format_time(dt, format_str='%d %b %Y, %I:%M %p'):
    """
    Format datetime with timezone conversion
    
    Args:
        dt: datetime object to format
        format_str: format string (default: '09 Jun 2026, 12:28 PM')
        
    Returns:
        str: formatted time string in local timezone
    """
    if dt is None:
        return 'N/A'
    
    local_dt = utc_to_local(dt)
    return local_dt.strftime(format_str)

def format_time_short(dt):
    """Format datetime in short format: 09 Jun 2026, 12:28"""
    return format_time(dt, '%d %b %Y, %H:%M')

def format_time_long(dt):
    """Format datetime in long format: 09 Jun 2026, 12:28 PM"""
    return format_time(dt, '%d %b %Y, %I:%M %p')

def format_date_only(dt):
    """Format date only: 09 Jun 2026"""
    return format_time(dt, '%d %b %Y')
