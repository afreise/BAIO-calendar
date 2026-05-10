import os
import json
from datetime import datetime, timedelta, timezone
from google.oauth2 import service_account
from googleapiclient.discovery import build

CALENDAR_ID = os.environ.get("CALENDAR_ID", "2e2273452749e5e648690f91f782fb2cccc1e1f0e125f4857b420d6d4e7c75ea@group.calendar.google.com")
SCOPES = ["https://www.googleapis.com/auth/calendar"]

def get_calendar_service():
    creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if not creds_json:
        raise ValueError("GOOGLE_CREDENTIALS_JSON environment variable not set")
    creds_dict = json.loads(creds_json)
    creds = service_account.Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return build("calendar", "v3", credentials=creds)


def add_to_calendar(event):
    service = get_calendar_service()

    start = event.get("start")
    end = event.get("end")

    # If no start time, create as an all-day event for today
    if not start:
        today = datetime.now(timezone.utc).date().isoformat()
        cal_start = {"date": today}
        cal_end = {"date": today}
    else:
        # Determine if datetime includes time or is date-only
        if "T" in str(start):
            cal_start = {"dateTime": start, "timeZone": "UTC"}
            if end:
                cal_end = {"dateTime": end, "timeZone": "UTC"}
            else:
                # Default to 1 hour duration
                from dateutil import parser as dp
                dt = dp.parse(start)
                cal_end = {"dateTime": (dt + timedelta(hours=1)).isoformat(), "timeZone": "UTC"}
        else:
            cal_start = {"date": start}
            cal_end = {"date": end or start}

    description = event.get("description", "")
    source_url = event.get("source_url", "")
    if source_url:
        description = f"{description}\n\nSource: {source_url}".strip()

    body = {
        "summary": event["title"],
        "description": description,
        "start": cal_start,
        "end": cal_end,
    }

    if event.get("location"):
        body["location"] = event["location"]

    created = service.events().insert(calendarId=CALENDAR_ID, body=body).execute()
    return created.get("htmlLink", "")
