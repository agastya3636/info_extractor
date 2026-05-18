import asyncio
import json
import os

from linkedin_scraper import (
    BrowserManager,
    PersonScraper,
    AuthenticationError,
    login_with_credentials,
    login_with_cookie,
)


def scrape_linkedin(url: str) -> dict:
    """
    Scrape a LinkedIn profile using the linkedin_scraper library.

    Auth priority:
      1. LINKEDIN_COOKIE env var (li_at cookie value — fastest, most reliable)
      2. li_at extracted from LINKEDIN_COOKIES_PATH cookies JSON file
      3. LINKEDIN_EMAIL + LINKEDIN_PASSWORD auto-login
      4. Blocked — returns error with setup instructions

    Returns structured dict with: name, location, about, open_to_work,
    experience, education, interests, accomplishments, contacts.
    """
    try:
        return asyncio.run(_scrape_async(url))
    except RuntimeError:
        # Already inside a running event loop (e.g. async MCP host, Jupyter).
        # Spin up a dedicated thread with its own loop to avoid the conflict.
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(lambda: asyncio.run(_scrape_async(url))).result()


async def _scrape_async(url: str) -> dict:
    li_at = os.getenv("LINKEDIN_COOKIE")
    cookies_path = os.getenv("LINKEDIN_COOKIES_PATH", ".linkedin_cookies.json")
    email = os.getenv("LINKEDIN_EMAIL")
    password = os.getenv("LINKEDIN_PASSWORD")

    # Extract li_at from an existing Playwright cookies JSON if available
    if not li_at and os.path.exists(cookies_path):
        try:
            with open(cookies_path) as f:
                for c in json.load(f):
                    if c.get("name") == "li_at":
                        li_at = c["value"]
                        break
        except Exception:
            pass

    if not li_at and not (email and password):
        return {
            "platform": "LinkedIn",
            "url": url,
            "status": "blocked",
            "error": (
                "LinkedIn requires authentication. Set LINKEDIN_COOKIE (li_at cookie value) "
                "or LINKEDIN_EMAIL + LINKEDIN_PASSWORD in your .env file."
            ),
        }

    async with BrowserManager(
        headless=True,
        user_agent=(
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
    ) as browser:
        try:
            if li_at:
                await login_with_cookie(browser.page, li_at)
            else:
                await login_with_credentials(browser.page, email, password)
        except AuthenticationError as e:
            return {
                "platform": "LinkedIn",
                "url": url,
                "status": "login_failed",
                "error": str(e),
            }

        try:
            person = await PersonScraper(browser.page).scrape(url)
        except AuthenticationError as e:
            return {"platform": "LinkedIn", "url": url, "status": "login_failed", "error": str(e)}
        except Exception as e:
            return {"platform": "LinkedIn", "url": url, "error": str(e)}

    return _to_dict(person)


def _to_dict(person) -> dict:
    return {
        "platform": "LinkedIn",
        "url": person.linkedin_url,
        "name": person.name,
        "location": person.location,
        "about": person.about,
        "open_to_work": person.open_to_work,
        "experience": [
            {
                "company": e.institution_name,
                "role": e.position_title,
                "from": e.from_date,
                "to": e.to_date,
                "duration": e.duration,
                "location": e.location,
                "description": e.description,
            }
            for e in person.experiences
        ],
        "education": [
            {
                "institution": e.institution_name,
                "degree": e.degree,
                "from": e.from_date,
                "to": e.to_date,
                "description": e.description,
            }
            for e in person.educations
        ],
        "interests": [
            {"name": i.name, "category": i.category} for i in person.interests
        ],
        "accomplishments": [
            {
                "category": a.category,
                "title": a.title,
                "issuer": a.issuer,
                "issued_date": a.issued_date,
                "credential_id": a.credential_id,
                "description": a.description,
            }
            for a in person.accomplishments
        ],
        "contacts": [
            {"type": c.type, "value": c.value, "label": c.label}
            for c in person.contacts
        ],
    }
