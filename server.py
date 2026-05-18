import os
import json
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from tools.parse_resume import parse_resume as _parse_resume
from tools.scrape_github import scrape_github as _scrape_github
from tools.scrape_linkedin import scrape_linkedin as _scrape_linkedin
from tools.scrape_twitter import scrape_twitter as _scrape_twitter
from tools.search_web import search_web as _search_web
from tools.scrape_instagram import scrape_instagram as _scrape_instagram
from tools.scrape_instagram_batch import scrape_instagram_batch as _scrape_instagram_batch
from tools.generate_report import generate_report as _generate_report
from tools.generate_report import summarize_presence as _summarize_presence

load_dotenv()

mcp = FastMCP("profile-scraper")


@mcp.tool()
def parse_resume(file_path: str) -> str:
    """
    Parse a resume file (PDF or DOCX) and extract structured profile data.

    Returns JSON with: name, email, phone, location, headline, links (with platform
    and URL), skills, experience, education, certifications, and projects.

    Args:
        file_path: Absolute path to the resume file (PDF or DOCX).
    """
    return json.dumps(_parse_resume(file_path), indent=2)


@mcp.tool()
def scrape_github(url: str) -> str:
    """
    Scrape a GitHub profile using the GitHub REST API.

    Returns name, bio, location, follower/following counts, public repo count,
    and top 10 repos ranked by stars (with description, language, stars, forks).

    Optionally set GITHUB_TOKEN in .env for higher rate limits (5000/hr vs 60/hr).

    Args:
        url: GitHub profile URL, e.g. https://github.com/username
    """
    return json.dumps(_scrape_github(url), indent=2)


@mcp.tool()
def scrape_linkedin(url: str) -> str:
    """
    Scrape a LinkedIn profile using Playwright and Claude extraction.

    Extracts name, headline, location, about, experience, education, and skills.
    Requires LinkedIn login cookies for full access — set LINKEDIN_COOKIES_PATH
    in .env pointing to an exported cookies JSON file.

    Args:
        url: LinkedIn profile URL, e.g. https://linkedin.com/in/username
    """
    return json.dumps(_scrape_linkedin(url), indent=2)


@mcp.tool()
def scrape_twitter(url: str) -> str:
    """
    Scrape a public Twitter/X profile using Playwright.

    Extracts name, handle, bio, location, website, follower and following counts.
    Works on public profiles without login. Both twitter.com and x.com URLs work.

    Args:
        url: Twitter/X profile URL, e.g. https://x.com/username
    """
    return json.dumps(_scrape_twitter(url), indent=2)


@mcp.tool()
def search_web(
    name: str,
    known_links: list[str] | None = None,
    context: str | None = None,
) -> str:
    """
    Search the web for a person's profiles and mentions not already in their resume.

    Runs targeted DuckDuckGo queries for 13 platforms (GitHub, LinkedIn, Twitter,
    Medium, Dev.to, Stack Overflow, Kaggle, YouTube, ResearchGate, HackerNews,
    Google Scholar, Behance, Dribbble) plus 4 discovery categories (talks,
    blogs/portfolio, news/press, open source contributions).

    Already-known URLs are excluded so only new discoveries are returned.

    Args:
        name: Full name of the person.
        known_links: List of URLs already found in the resume (optional).
        context: Disambiguation context to narrow searches for common names,
                 e.g. "Python developer at Google, San Francisco" (optional).
    """
    return json.dumps(_search_web(name, known_links, context), indent=2)


@mcp.tool()
def scrape_instagram(url: str, max_posts: int = 12, use_tor: bool = False) -> str:
    """
    Scrape a public Instagram profile using Playwright.

    Intercepts Instagram's internal API to extract: full name, username, bio,
    profile picture, follower/following/post counts, verified status, business
    category, external link, and recent posts (captions, likes, comments,
    timestamps, thumbnails, video views).

    Scrolls the page to paginate beyond the initial 12 posts.

    Args:
        url: Instagram profile URL, e.g. https://www.instagram.com/username/
        max_posts: Number of posts to collect (default 12). Set higher to scroll
                   and paginate — e.g. 48 for ~4 pages of posts.
        use_tor: Route through Tor for IP rotation (requires Tor running on port 9050).
                 Rotates exit node before each request. Set TOR_CONTROL_PASSWORD in .env
                 if your torrc uses HashedControlPassword (leave blank for CookieAuthentication).
    """
    return json.dumps(_scrape_instagram(url, max_posts, use_tor), indent=2)


@mcp.tool()
def generate_report(
    resume_path: str,
    include_discovery: bool = True,
    context: str | None = None,
) -> str:
    """
    Full end-to-end internet presence report from a resume file.

    Pipeline:
      1. Parse resume (PDF or DOCX) → extract profile data and known links
      2. Scrape each known platform link (GitHub API, LinkedIn via Playwright, Twitter via Playwright)
      3. Run web discovery across 39 platforms to find profiles not in the resume
      4. Generate an AI-written presence report covering overview, platforms, highlights, and gaps

    Args:
        resume_path: Absolute path to the resume file (PDF or DOCX).
        include_discovery: Run web discovery in addition to scraping known links (default True).
        context: Disambiguation context for common names, e.g. "photographer in Mumbai".
                 Auto-built from resume headline + company + location if not provided.
    """
    return json.dumps(_generate_report(resume_path, include_discovery, context), indent=2)


@mcp.tool()
def scrape_instagram_batch(
    urls: list[str],
    checkpoint_path: str = "instagram_batch_progress.json",
    use_tor: bool = False,
    workers: int = 3,
    delay: float = 3.0,
    max_retries: int = 2,
) -> str:
    """
    Scrape a list of Instagram profile URLs in parallel with retry and checkpoint/resume.

    Runs up to 3 browser contexts concurrently, retries on IP block, and saves progress
    to a JSON checkpoint so interrupted runs resume where they left off.

    Args:
        urls: List of Instagram profile URLs, e.g. ["https://www.instagram.com/nasa/", ...]
        checkpoint_path: File to save/resume progress (default: instagram_batch_progress.json).
        use_tor: Route through Tor SOCKS5 with circuit rotation between requests.
        workers: Parallel browser contexts (default 3, max recommended 5).
        delay: Seconds between requests per worker (default 3.0).
        max_retries: Retry attempts on block before marking failed (default 2).
    """
    results = _scrape_instagram_batch(urls, checkpoint_path, use_tor, workers, delay, max_retries)
    return json.dumps({"scraped": len(results), "results": results}, indent=2)


@mcp.tool()
def summarize_presence(
    name: str,
    context: str | None = None,
) -> str:
    """
    Internet presence report from a name alone — no resume needed.

    Runs web discovery across 40+ platforms, auto-scrapes top found profiles
    (GitHub, Twitter/X, Instagram), and generates an AI-written presence summary
    covering professional overview, platform stats, highlights, and gaps.

    Args:
        name: Full name of the person, e.g. "Linus Torvalds".
        context: Disambiguation hint for common names,
                 e.g. "Linux kernel creator, Finland" (optional).
    """
    return json.dumps(_summarize_presence(name, context), indent=2)


if __name__ == "__main__":
    mcp.run()
