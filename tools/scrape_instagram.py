import json
import re
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from tools.tor_proxy import is_tor_running, rotate_exit_node, proxy_args


def scrape_instagram(
    url: str,
    max_posts: int = 12,
    use_tor: bool = False,
    rotate_tor: bool = True,
    proxy: dict | None = None,
) -> dict:
    """
    Scrape a public Instagram profile using Playwright.

    Intercepts Instagram's internal web_profile_info API call to extract:
    full name, username, bio, profile picture, follower/following/post counts,
    verified status, business category, external link, and recent post previews.

    Scrolls the page to trigger pagination and collect up to max_posts posts.
    Falls back to meta tag parsing if the API call isn't captured.

    Args:
        url: Instagram profile URL.
        max_posts: Maximum number of posts to collect (default 12, set higher to paginate).
        use_tor: Route through Tor SOCKS5 proxy for IP rotation.
        rotate_tor: Request a new Tor circuit before scraping (default True).
                    Set False when batch mode manages rotation externally.
    """
    if use_tor:
        if not is_tor_running():
            return {
                "platform": "Instagram",
                "url": url,
                "error": "Tor is not running. Start it with: sudo service tor start",
            }
        if rotate_tor:
            rotate_exit_node()

    username = _username_from_url(url)
    captured_profile: dict = {}
    captured_posts: list[dict] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context_kwargs = dict(
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
            locale="en-US",
        )
        effective_proxy = proxy or (proxy_args() if use_tor else None)
        if effective_proxy:
            context_kwargs["proxy"] = effective_proxy
        context = browser.new_context(**context_kwargs)
        page = context.new_page()

        def on_response(response):
            try:
                if "web_profile_info" in response.url or "userInfo" in response.url:
                    data = response.json()
                    captured_profile.update(data)
                elif "api/v1/feed/user" in response.url or (
                    "graphql" in response.url and "edge_owner_to_timeline_media" in response.text()
                ):
                    data = response.json()
                    edges = (
                        data.get("data", {})
                        .get("user", {})
                        .get("edge_owner_to_timeline_media", {})
                        .get("edges", [])
                    )
                    captured_posts.extend(edges)
            except Exception:
                pass

        page.on("response", on_response)

        try:
            page.goto(url, wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(2000)
        except PlaywrightTimeout:
            browser.close()
            return {"platform": "Instagram", "url": url, "error": "Page load timed out"}

        if "accounts/login" in page.url:
            browser.close()
            return {
                "platform": "Instagram",
                "url": url,
                "status": "blocked",
                "error": "Instagram requires login to view this profile.",
            }

        meta = _extract_meta(page)
        try:
            profile_pic = page.get_attribute('meta[property="og:image"]', "content", timeout=5000)
        except PlaywrightTimeout:
            profile_pic = None
        try:
            page_text = page.inner_text("body", timeout=5000)
        except PlaywrightTimeout:
            page_text = ""

        # Scroll to load more posts if max_posts > 12
        if max_posts > 12:
            _scroll_for_posts(page, max_posts)

        browser.close()

    api_user = (
        captured_profile.get("data", {}).get("user", {})
    )

    if api_user:
        initial_edges = api_user.get("edge_owner_to_timeline_media", {}).get("edges", [])
        all_edges = {e["node"]["shortcode"]: e for e in initial_edges}
        for e in captured_posts:
            all_edges[e["node"]["shortcode"]] = e

        posts = [
            _format_post(e)
            for e in list(all_edges.values())[:max_posts]
        ]

        total_posts = api_user.get("edge_owner_to_timeline_media", {}).get("count", 0)

        return {
            "platform": "Instagram",
            "url": url,
            "username": "@" + api_user.get("username", username),
            "name": api_user.get("full_name"),
            "bio": api_user.get("biography"),
            "external_link": api_user.get("external_url") or None,
            "profile_pic": api_user.get("profile_pic_url_hd") or profile_pic,
            "followers": api_user.get("edge_followed_by", {}).get("count"),
            "following": api_user.get("edge_follow", {}).get("count"),
            "total_posts": total_posts,
            "posts_scraped": len(posts),
            "is_verified": api_user.get("is_verified", False),
            "is_business": api_user.get("is_business_account", False),
            "business_category": api_user.get("business_category_name") or None,
            "recent_posts": posts,
        }

    # Fallback: meta tags
    bio = _extract_bio_from_text(page_text, meta.get("username", "").lstrip("@"))
    return {
        "platform": "Instagram",
        "url": url,
        "username": meta.get("username"),
        "name": meta.get("name"),
        "bio": bio or meta.get("bio"),
        "profile_pic": profile_pic,
        "followers": meta.get("followers"),
        "following": meta.get("following"),
        "total_posts": meta.get("posts"),
        "source": "meta_tags",
    }


def _username_from_url(url: str) -> str:
    return url.rstrip("/").split("/")[-1].lstrip("@")


def _extract_meta(page) -> dict:
    data = {}
    try:
        title = page.get_attribute('meta[property="og:title"]', "content") or ""
        desc = page.get_attribute('meta[property="og:description"]', "content") or ""

        name_match = re.match(r"^(.+?)\s*\(@", title)
        if name_match:
            data["name"] = name_match.group(1).strip()
        handle_match = re.search(r"\(@([^)]+)\)", title)
        if handle_match:
            data["username"] = "@" + handle_match.group(1)

        counts = re.findall(r"([\d,\.KkMm]+)\s+(Followers|Following|Posts)", desc)
        for val, label in counts:
            data[label.lower()] = val

        bio_match = re.search(r"\d+\s+Posts?\s*[-–]\s*(.+)", desc, re.DOTALL)
        if bio_match:
            raw = bio_match.group(1).strip()
            if "See Instagram" not in raw:
                data["bio"] = raw
    except Exception:
        pass
    return data


def _extract_bio_from_text(page_text: str, username: str) -> str | None:
    """Try to find bio in raw page text by looking near the username."""
    try:
        lines = [l.strip() for l in page_text.splitlines() if l.strip()]
        for i, line in enumerate(lines):
            if username.lower() in line.lower() and i + 1 < len(lines):
                candidate = lines[i + 1]
                if not re.match(r"^\d", candidate) and len(candidate) > 5:
                    return candidate
    except Exception:
        pass
    return None


def _scroll_for_posts(page, max_posts: int) -> None:
    """Scroll the page in batches to trigger Instagram's pagination API calls."""
    collected = 0
    prev_height = 0
    max_scrolls = max(1, (max_posts // 12) + 2)

    for _ in range(max_scrolls):
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(1800)
        new_height = page.evaluate("document.body.scrollHeight")
        if new_height == prev_height:
            break
        prev_height = new_height


def _format_post(edge: dict) -> dict:
    node = edge.get("node", {})
    caption_edges = node.get("edge_media_to_caption", {}).get("edges", [])
    caption = caption_edges[0]["node"]["text"] if caption_edges else None

    return {
        "url": f"https://www.instagram.com/p/{node.get('shortcode', '')}/",
        "type": node.get("__typename", "GraphImage").replace("Graph", "").lower(),
        "likes": node.get("edge_liked_by", {}).get("count"),
        "comments": node.get("edge_media_to_comment", {}).get("count"),
        "caption": caption[:200] if caption else None,
        "thumbnail": node.get("thumbnail_src") or node.get("display_url"),
        "timestamp": node.get("taken_at_timestamp"),
        "is_video": node.get("is_video", False),
        "video_views": node.get("video_view_count") if node.get("is_video") else None,
    }
