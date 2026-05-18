from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout


def _normalize_url(url: str) -> str:
    return url.replace("x.com", "twitter.com")


def _safe_text(page, selector: str) -> str | None:
    try:
        el = page.query_selector(selector)
        return el.inner_text().strip() if el else None
    except Exception:
        return None


def scrape_twitter(url: str) -> dict:
    """
    Scrape a public Twitter/X profile using Playwright.

    Works on public profiles without login. May be rate-limited for heavy use.
    """
    url = _normalize_url(url)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
        )
        page = context.new_page()

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_selector('[data-testid="UserName"]', timeout=12000)
        except PlaywrightTimeout:
            browser.close()
            return {
                "platform": "Twitter/X",
                "url": url,
                "status": "blocked",
                "error": "Profile did not load — account may be protected or login required.",
            }

        name = _safe_text(page, '[data-testid="UserName"] span:first-child')
        handle = _safe_text(page, '[data-testid="UserName"] span:last-child')
        bio = _safe_text(page, '[data-testid="UserDescription"]')
        location = _safe_text(page, '[data-testid="UserLocation"]')
        website = _safe_text(page, '[data-testid="UserUrl"] a')

        followers, following = None, None
        try:
            for a in page.query_selector_all("a[href]"):
                href = a.get_attribute("href") or ""
                if not href:
                    continue
                count_el = a.query_selector("span > span")
                if not count_el:
                    continue
                count = count_el.inner_text().strip()
                if not count:
                    continue
                if href.endswith("/following"):
                    following = count
                elif href.endswith("/followers") or href.endswith("/verified_followers"):
                    followers = count
        except Exception:
            pass

        browser.close()

    return {
        "platform": "Twitter/X",
        "url": url,
        "name": name,
        "handle": handle,
        "bio": bio,
        "location": location,
        "website": website,
        "followers": followers,
        "following": following,
    }
