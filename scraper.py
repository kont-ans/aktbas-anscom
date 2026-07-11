import re
import time
import logging
import requests
from bs4 import BeautifulSoup
from typing import Optional
from config import BASE_URL, USER_AGENT, HTTP_TIMEOUT, REQUEST_DELAY

logger = logging.getLogger(__name__)

_SESSION = requests.Session()
_SESSION.headers.update({
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
})

_LAST_REQUEST_AT = 0.0


def _polite_get(url: str) -> Optional[requests.Response]:
    """GET with delay + error handling. Returns None on failure."""
    global _LAST_REQUEST_AT
    elapsed = time.time() - _LAST_REQUEST_AT
    if elapsed < REQUEST_DELAY:
        time.sleep(REQUEST_DELAY - elapsed)
    try:
        resp = _SESSION.get(url, timeout=HTTP_TIMEOUT)
        _LAST_REQUEST_AT = time.time()
        if resp.status_code == 200:
            return resp
        logger.warning("HTTP %s for %s", resp.status_code, url)
    except requests.RequestException as e:
        logger.warning("Request failed for %s: %s", url, e)
    return None


# ── Countries ─────────────────────────────────────────────────────────────────

def get_countries() -> list[dict]:
    """
    Returns list of {slug, name, count} for all countries.
    Falls back to a curated list of popular countries if scraping fails.
    """
    url = f"{BASE_URL}/countries"
    resp = _polite_get(url)
    countries = []
    seen = set()

    if resp:
        try:
            soup = BeautifulSoup(resp.text, "lxml")
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if "/countries/" not in href:
                    continue
                slug = href.split("/countries/")[-1].strip("/")
                if not slug or "/" in slug or slug in seen:
                    continue
                seen.add(slug)
                raw_text = a.get_text(" ", strip=True)
                # Clean text like "TrendingUnited States+1555 numbers"
                name = re.sub(r"^Trending", "", raw_text).strip()
                # Remove trailing "+code...numbers" stuff
                name = re.sub(r"\s*\+?\d+.*$", "", name).strip()
                if not name:
                    name = slug.replace("-", " ").title()
                # Try to extract count
                count_match = re.search(r"(\d+)\s*number", raw_text)
                count = int(count_match.group(1)) if count_match else 0
                countries.append({"slug": slug, "name": name, "count": count})
        except Exception as e:
            logger.error("Country parse error: %s", e)

    if not countries:
        # Fallback popular countries
        fallback = [
            ("united-states", "United States"),
            ("united-kingdom", "United Kingdom"),
            ("canada", "Canada"),
            ("germany", "Germany"),
            ("france", "France"),
            ("netherlands", "Netherlands"),
            ("sweden", "Sweden"),
            ("finland", "Finland"),
            ("spain", "Spain"),
            ("italy", "Italy"),
            ("brazil", "Brazil"),
            ("india", "India"),
        ]
        countries = [{"slug": s, "name": n, "count": 0} for s, n in fallback]

    return countries


# ── Numbers ───────────────────────────────────────────────────────────────────

def get_numbers_by_country(country_slug: str, limit: int = 30) -> list[dict]:
    """
    Returns list of {phone, url} for numbers available in given country.
    """
    url = f"{BASE_URL}/countries/{country_slug}"
    resp = _polite_get(url)
    if not resp:
        return []

    numbers = []
    seen = set()
    try:
        soup = BeautifulSoup(resp.text, "lxml")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            # Pattern: /temporary-numbers/{country}/{phone}
            m = re.search(r"/temporary-numbers/([^/]+)/(\d{6,})", href)
            if not m:
                continue
            phone_digits = m.group(2)
            if phone_digits in seen:
                continue
            seen.add(phone_digits)
            phone_display = f"+{phone_digits}"
            if href.startswith("/"):
                full_url = BASE_URL + href
            elif href.startswith("http"):
                full_url = href
            else:
                full_url = f"{BASE_URL}/{href}"
            numbers.append({
                "phone": phone_display,
                "phone_digits": phone_digits,
                "url": full_url,
            })
            if len(numbers) >= limit:
                break
    except Exception as e:
        logger.error("Number parse error for %s: %s", country_slug, e)

    return numbers


# ── Messages ──────────────────────────────────────────────────────────────────

def get_messages_by_number(country_slug: str, phone_digits: str,
                           limit: int = 20) -> list[dict]:
    """
    Returns list of {sender, time, body} for messages received by given number.
    """
    url = f"{BASE_URL}/temporary-numbers/{country_slug}/{phone_digits}"
    resp = _polite_get(url)
    if not resp:
        return []

    messages = []
    try:
        soup = BeautifulSoup(resp.text, "lxml")
        cards = soup.find_all("article", class_="msg-card")
        if not cards:
            # Fallback: any element with msg-card class
            cards = soup.find_all(class_=lambda x: x and "msg-card" in x)
        for card in cards[:limit]:
            try:
                # Sender
                sender_el = card.find(class_="msg-from")
                if sender_el:
                    spans = sender_el.find_all("span")
                    sender = spans[-1].get_text(strip=True) if spans else sender_el.get_text(strip=True)
                else:
                    sender = "Unknown"

                # Time
                time_el = card.find("time", class_="msg-time")
                if not time_el:
                    time_el = card.find(class_="msg-time")
                time_str = time_el.get_text(strip=True) if time_el else ""

                # Body
                body_el = card.find(class_="msg-body")
                body = body_el.get_text(" ", strip=True) if body_el else ""

                if body:
                    messages.append({
                        "sender": sender,
                        "time": time_str,
                        "body": body,
                    })
            except Exception as e:
                logger.warning("Card parse error: %s", e)
                continue
    except Exception as e:
        logger.error("Message parse error for %s: %s", phone_digits, e)

    return messages
