"""UTC storage and explicit interpretation of pre-UTC records; no data rewrite."""
import os
import re
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).with_name('.env'))
from datetime import datetime, timedelta, timezone

# Existing records from the verified Windows trial were written in UTC+09:00.
# An installation importing other legacy data must set its original offset.
offset = os.getenv('LEGACY_TIMEZONE_OFFSET', '+09:00')
if not re.fullmatch(r'[+-](?:0\d|1[0-4]):[0-5]\d', offset):
    raise ValueError('LEGACY_TIMEZONE_OFFSET must use a valid offset such as +09:00')
LEGACY_TZ = timezone((1 if offset[0]=='+' else -1)*timedelta(hours=int(offset[1:3]),minutes=int(offset[4:6])))
DISPLAY_TZ = timezone(timedelta(hours=8))


def parse_time(value):
    parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=LEGACY_TZ)


def utc_time(value):
    if not value:
        return None
    try:
        return parse_time(value).astimezone(timezone.utc).isoformat(timespec='seconds').replace('+00:00','Z')
    except (ValueError, TypeError):
        return value


def timestamp(value):
    try:
        return parse_time(value).timestamp()
    except (ValueError, TypeError):
        return 0


def normalize_interview(row):
    result = dict(row)
    for key in ('started_at', 'ended_at'):
        if key in result:
            result[key] = utc_time(result[key])
    return result


def display_time(value):
    try:
        return parse_time(value).astimezone(DISPLAY_TZ).strftime('%Y-%m-%d %H:%M') + '（北京时间）'
    except (ValueError, TypeError):
        return '时间未知'
