# Event Calendar

A web app that scrapes event details from URLs and adds them to a public Google Calendar.

## Setup

### Environment Variables

Set these in Railway (or your `.env` for local dev):

| Variable | Description |
|---|---|
| `APP_PASSWORD` | Password users enter to access the app |
| `GOOGLE_CREDENTIALS_JSON` | The full contents of your Google service account JSON key file |
| `CALENDAR_ID` | Your Google Calendar ID (already set in code, but can override here) |
| `SECRET_KEY` | Any random string, used to secure sessions |

### Deploy to Railway

1. Push this folder to a GitHub repo
2. Go to railway.app and create a new project from that repo
3. Under **Variables**, add the four environment variables above
4. Railway will detect the Procfile and deploy automatically

### Local Development

```bash
pip install -r requirements.txt
export APP_PASSWORD=yourpassword
export GOOGLE_CREDENTIALS_JSON='<paste full JSON here>'
export SECRET_KEY=anyrandomstring
python app.py
```

Then open http://localhost:5000

## Supported Sources

- Eventbrite
- Luma (lu.ma)
- Meetup
- Partiful (uses headless browser)
- Facebook Events (uses headless browser — public events only; login-gated events won't work)
- Any site with JSON-LD Event schema markup
- Generic fallback for other pages (title + description, no date)

> **Note on Facebook**: Facebook requires you to be logged in to see most event details. The scraper will extract what it can from the public-facing page, but date/location may be missing for private or login-gated events.
