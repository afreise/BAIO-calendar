import re
import json
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from dateutil import parser as dateparser

from urllib.parse import urlparse

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

def scrape_event(url):
    """Try platform-specific scrapers first, then fall back to generic."""
    domain = urlparse(url).netloc.lower()

    if "eventbrite" in domain:
        return scrape_eventbrite(url)
    elif "lu.ma" in domain or "luma" in domain:
        return scrape_luma(url)
    elif "meetup.com" in domain:
        return scrape_meetup(url)
    elif "partiful.com" in domain:
        return scrape_with_playwright(url, extract_partiful)
    elif "facebook.com" in domain or "fb.com" in domain:
        return scrape_with_playwright(url, extract_facebook)
    else:
        return scrape_generic(url)


def scrape_with_playwright(url, extractor_fn):
    """Load a JS-rendered page with Playwright, then run extractor_fn on the HTML."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError("Playwright is not installed. Run: pip install playwright && playwright install chromium")

    with sync_playwright() as p:
        # Use system Chromium if available (Railway), otherwise let Playwright find its own
        import shutil
        chromium_path = shutil.which("chromium") or shutil.which("chromium-browser")
        launch_kwargs = {"headless": True}
        if chromium_path:
            launch_kwargs["executable_path"] = chromium_path
        browser = p.chromium.launch(**launch_kwargs)
        context = browser.new_context(
            user_agent=HEADERS["User-Agent"],
            locale="en-US",
        )
        page = context.new_page()
        try:
            page.goto(url, wait_until="networkidle", timeout=30000)
            html = page.content()
            return extractor_fn(html, url, page)
        finally:
            browser.close()


def extract_partiful(html, url, page):
    """Extract event data from a fully-rendered Partiful page."""
    soup = BeautifulSoup(html, "html.parser")

    # Try JSON-LD first (Partiful sometimes includes it)
    event = extract_structured_data(html, url)
    if event and event.get("start"):
        return event

    # Partiful-specific DOM extraction
    title = None
    h1 = soup.find("h1")
    if h1:
        title = h1.get_text(strip=True)

    # Date/time — Partiful renders these as visible text, look for time elements or labeled sections
    start_dt = None
    end_dt = None
    time_els = soup.find_all("time")
    if time_els:
        datetimes = [el.get("datetime") for el in time_els if el.get("datetime")]
        if datetimes:
            start_dt = datetimes[0]
            end_dt = datetimes[1] if len(datetimes) > 1 else None

    if not start_dt:
        # Look for date text patterns like "Saturday, June 14 · 7:00 PM"
        text = soup.get_text(separator=" ")
        date_match = re.search(
            r'((?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+'
            r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{1,2}'
            r'(?:,?\s+\d{4})?'
            r'(?:\s*[·•]\s*\d{1,2}:\d{2}\s*(?:AM|PM))?)',
            text, re.IGNORECASE
        )
        if date_match:
            try:
                start_dt = dateparser.parse(date_match.group(1)).isoformat()
            except Exception:
                pass

    location = None
    # Look for address or location-like elements
    loc_candidates = soup.find_all(class_=re.compile(r'location|address|venue|where', re.I))
    for el in loc_candidates:
        text = el.get_text(strip=True)
        if text and len(text) < 300:
            location = text
            break

    description = None
    desc_el = soup.find(class_=re.compile(r'description|about|details', re.I))
    if desc_el:
        description = desc_el.get_text(separator="\n", strip=True)[:2000]

    return build_event(title, start_dt, end_dt, location, description, url)


def extract_facebook(html, url, page):
    """Extract event data from a fully-rendered Facebook event page."""
    soup = BeautifulSoup(html, "html.parser")

    # Try JSON-LD — Facebook does embed this on event pages
    event = extract_structured_data(html, url)
    if event and event.get("start"):
        return event

    # Facebook-specific: event data is often in a <script type="application/json"> blob
    for script in soup.find_all("script", type="application/json"):
        try:
            data = json.loads(script.string or "")
            result = _search_fb_json(data, url)
            if result:
                return result
        except (json.JSONDecodeError, TypeError):
            continue

    # Fallback: visible text extraction
    title = None
    # Facebook event titles are usually in an h1 or a specific aria role
    h1 = soup.find("h1")
    if h1:
        title = h1.get_text(strip=True)

    # Try og:title
    if not title:
        og = soup.find("meta", property="og:title")
        if og:
            title = og.get("content", "").strip()

    description = None
    og_desc = soup.find("meta", property="og:description")
    if og_desc:
        description = og_desc.get("content", "").strip()

    # Facebook renders dates as visible text; try to find them
    start_dt = None
    time_els = soup.find_all("time")
    for t in time_els:
        dt = t.get("datetime") or t.get_text(strip=True)
        if dt:
            try:
                start_dt = dateparser.parse(dt).isoformat()
                break
            except Exception:
                continue

    location = None
    loc_el = soup.find("a", href=re.compile(r"maps|places", re.I))
    if loc_el:
        location = loc_el.get_text(strip=True)

    return build_event(title, start_dt, None, location, description, url)


def _search_fb_json(obj, url, depth=0):
    """Recursively search Facebook's JSON blobs for event-shaped data."""
    if depth > 8 or not isinstance(obj, (dict, list)):
        return None
    if isinstance(obj, dict):
        # Look for objects that have event-like keys
        if obj.get("event") and isinstance(obj["event"], dict):
            ev = obj["event"]
            title = ev.get("name")
            start_dt = ev.get("start_time") or ev.get("startDate")
            end_dt = ev.get("end_time") or ev.get("endDate")
            location = None
            place = ev.get("place") or ev.get("location")
            if isinstance(place, dict):
                location = place.get("name")
                loc_data = place.get("location", {})
                if isinstance(loc_data, dict):
                    city = loc_data.get("city", "")
                    state = loc_data.get("state", "")
                    if city or state:
                        location = f"{location}, {city}, {state}".strip(", ")
            description = ev.get("description")
            if title:
                return build_event(title, start_dt, end_dt, location, description, url)
        for v in obj.values():
            result = _search_fb_json(v, url, depth + 1)
            if result:
                return result
    elif isinstance(obj, list):
        for item in obj:
            result = _search_fb_json(item, url, depth + 1)
            if result:
                return result
    return None


def scrape_eventbrite(url):
    """Scrape Eventbrite event page."""
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    # Try structured data first
    event = extract_structured_data(resp.text, url)
    if event:
        return event

    # Fallback: Eventbrite-specific selectors
    title = soup.find("h1", class_=re.compile("event-title|listing-hero-title", re.I))
    title = title.get_text(strip=True) if title else None

    start_dt = None
    end_dt = None
    time_tag = soup.find("time")
    if time_tag and time_tag.get("datetime"):
        start_dt = time_tag["datetime"]

    location = None
    loc_el = soup.find(class_=re.compile("location|venue", re.I))
    if loc_el:
        location = loc_el.get_text(separator=" ", strip=True)[:200]

    description = None
    desc_el = soup.find(class_=re.compile("event-description|description", re.I))
    if desc_el:
        description = desc_el.get_text(separator="\n", strip=True)[:1000]

    return build_event(title, start_dt, end_dt, location, description, url)


def scrape_luma(url):
    """Scrape Luma event page."""
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()

    # Luma embeds event data in a <script id="__NEXT_DATA__"> tag
    soup = BeautifulSoup(resp.text, "html.parser")
    next_data = soup.find("script", id="__NEXT_DATA__")
    if next_data:
        try:
            data = json.loads(next_data.string)
            props = data.get("props", {}).get("pageProps", {})
            ev = props.get("initialData", {}).get("data", {}).get("event", {})
            if not ev:
                ev = props.get("event", {})
            if ev:
                title = ev.get("name") or ev.get("title")
                start_dt = ev.get("start_at") or ev.get("startDate")
                end_dt = ev.get("end_at") or ev.get("endDate")
                location = ev.get("location") or ev.get("geo_address_info", {}).get("full_address")
                description = ev.get("description") or ev.get("summary")
                if isinstance(description, dict):
                    description = description.get("text", "")
                return build_event(title, start_dt, end_dt, location, description, url)
        except (json.JSONDecodeError, AttributeError):
            pass

    # Fall back to structured data
    event = extract_structured_data(resp.text, url)
    if event:
        return event

    return scrape_generic_from_soup(soup, url)


def scrape_meetup(url):
    """Scrape Meetup event page."""
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()

    event = extract_structured_data(resp.text, url)
    if event:
        return event

    soup = BeautifulSoup(resp.text, "html.parser")
    return scrape_generic_from_soup(soup, url)


def scrape_generic(url):
    """Generic scraper using structured data and meta tags."""
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()

    event = extract_structured_data(resp.text, url)
    if event:
        return event

    soup = BeautifulSoup(resp.text, "html.parser")
    return scrape_generic_from_soup(soup, url)


def extract_structured_data(html, url):
    """Extract JSON-LD Event schema and OpenGraph tags using BeautifulSoup only."""
    try:
        soup = BeautifulSoup(html, "html.parser")

        # Try JSON-LD scripts
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
                items = data if isinstance(data, list) else [data]
                for item in items:
                    result = parse_schema_event(item, url)
                    if result:
                        return result
            except (json.JSONDecodeError, TypeError):
                continue

        # Try OpenGraph as fallback
        og_title = soup.find("meta", property="og:title")
        og_desc = soup.find("meta", property="og:description")
        title = og_title.get("content", "").strip() if og_title else None
        description = og_desc.get("content", "").strip() if og_desc else None
        if title:
            return build_event(title, None, None, None, description, url)

    except Exception:
        pass
    return None


def parse_schema_event(item, url):
    """Parse a JSON-LD item if it's an Event type."""
    if not isinstance(item, dict):
        return None
    item_type = item.get("@type", "")
    if isinstance(item_type, list):
        is_event = any("event" in t.lower() for t in item_type)
    else:
        is_event = "event" in item_type.lower()

    if not is_event:
        return None

    title = item.get("name")
    start_dt = item.get("startDate")
    end_dt = item.get("endDate")
    description = item.get("description")

    location = None
    loc = item.get("location")
    if isinstance(loc, dict):
        name = loc.get("name", "")
        addr = loc.get("address", {})
        if isinstance(addr, dict):
            parts = [addr.get("streetAddress"), addr.get("addressLocality"),
                     addr.get("addressRegion"), addr.get("postalCode")]
            addr_str = ", ".join(p for p in parts if p)
        else:
            addr_str = str(addr) if addr else ""
        location = f"{name} {addr_str}".strip() or None
    elif isinstance(loc, str):
        location = loc

    return build_event(title, start_dt, end_dt, location, description, url)


def scrape_generic_from_soup(soup, url):
    """Last-resort: grab title and meta tags from any page."""
    title = None
    if soup.find("h1"):
        title = soup.find("h1").get_text(strip=True)
    if not title:
        og_title = soup.find("meta", property="og:title")
        if og_title:
            title = og_title.get("content", "").strip()
    if not title and soup.title:
        title = soup.title.get_text(strip=True)

    description = None
    og_desc = soup.find("meta", property="og:description")
    if og_desc:
        description = og_desc.get("content", "").strip()
    if not description:
        meta_desc = soup.find("meta", attrs={"name": "description"})
        if meta_desc:
            description = meta_desc.get("content", "").strip()

    return build_event(title, None, None, None, description, url)


def build_event(title, start_dt, end_dt, location, description, url):
    """Normalize and return event dict, or None if missing critical data."""
    if not title:
        return None

    def parse_dt(val):
        if not val:
            return None
        if isinstance(val, datetime):
            return val.isoformat()
        try:
            dt = dateparser.parse(str(val))
            return dt.isoformat() if dt else None
        except Exception:
            return None

    return {
        "title": title,
        "start": parse_dt(start_dt),
        "end": parse_dt(end_dt),
        "location": location,
        "description": (description or "")[:2000],
        "source_url": url,
    }
