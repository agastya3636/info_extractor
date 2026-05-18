import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from anthropic import Anthropic

from tools.parse_resume import parse_resume
from tools.scrape_github import scrape_github
from tools.scrape_instagram import scrape_instagram
from tools.scrape_linkedin import scrape_linkedin
from tools.scrape_twitter import scrape_twitter
from tools.search_web import search_web

client = Anthropic()
MODEL = "claude-sonnet-4-6"

# Platforms we can auto-scrape when discovered in web search
_DOMAIN_SCRAPER = {
    "github.com": scrape_github,
    "twitter.com": scrape_twitter,
    "x.com": scrape_twitter,
    "instagram.com": scrape_instagram,
}


def _scrape_link(link: dict) -> tuple[str, dict]:
    url = link.get("url", "")
    platform = link.get("platform", "Other")
    try:
        if "github.com" in url:
            return platform, scrape_github(url)
        elif "linkedin.com" in url:
            return platform, scrape_linkedin(url)
        elif "twitter.com" in url or "x.com" in url:
            return platform, scrape_twitter(url)
        elif "instagram.com" in url:
            return platform, scrape_instagram(url)
        else:
            return platform, {"platform": platform, "url": url, "status": "not_scraped"}
    except Exception as e:
        return platform, {"platform": platform, "url": url, "error": str(e)}


def _scrape_discovered(profiles: list, known_urls: set) -> dict:
    """Scrape top discovered profiles that we have dedicated scrapers for."""
    seen_platforms: set = set()
    to_scrape: list = []

    for p in profiles:
        url = p.get("url", "")
        platform = p.get("platform", "")
        if not url or url in known_urls or platform in seen_platforms:
            continue
        for domain, fn in _DOMAIN_SCRAPER.items():
            if domain in url:
                to_scrape.append((platform, url, fn))
                seen_platforms.add(platform)
                break

    if not to_scrape:
        return {}

    extra: dict = {}
    with ThreadPoolExecutor(max_workers=min(len(to_scrape), 3)) as executor:
        futures = {
            executor.submit(fn, url): (platform_key, url)
            for platform_key, url, fn in to_scrape
        }
        for future in as_completed(futures):
            platform_key, url = futures[future]
            try:
                extra[platform_key] = future.result()
            except Exception as e:
                extra[platform_key] = {"platform": platform_key, "url": url, "error": str(e)}

    return extra


def _build_context(resume: dict) -> str:
    parts = []
    if resume.get("headline"):
        parts.append(resume["headline"])
    if resume.get("experience"):
        company = resume["experience"][0].get("company")
        if company:
            parts.append(f"at {company}")
    if resume.get("location"):
        parts.append(resume["location"])
    if resume.get("skills"):
        parts.append(", ".join(resume["skills"][:5]))
    return " ".join(parts)


def _generate_summary(name: str, resume: dict, scraped: dict, discovered: dict) -> str:
    snapshot = {
        "name": name,
        "headline": resume.get("headline"),
        "location": resume.get("location"),
        "skills": resume.get("skills", [])[:10],
        "experience": resume.get("experience", [])[:3],
        "education": resume.get("education", [])[:2],
        "scraped_profiles": {
            k: {ek: ev for ek, ev in v.items() if ek != "top_repos"}
            for k, v in scraped.items()
        },
        "top_repos": next(
            (v.get("top_repos", [])[:3] for v in scraped.values() if "top_repos" in v), []
        ),
        "discovered_profile_count": len(discovered.get("profiles", [])),
        "discovered_mention_count": len(discovered.get("mentions", [])),
        "top_discovered": [
            {"platform": p["platform"], "url": p["url"]}
            for p in discovered.get("profiles", [])[:6]
        ],
        "top_mentions": [
            {"category": m["category"], "title": m.get("title"), "url": m["url"]}
            for m in discovered.get("mentions", [])[:5]
        ],
    }

    response = client.messages.create(
        model=MODEL,
        max_tokens=1200,
        system=[{
            "type": "text",
            "text": "You write concise, factual internet presence reports. Use only the data provided. No filler phrases.",
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[
            {
                "role": "user",
                "content": f"""Write an internet presence report for {name} using the data below.

Structure it in 4 sections:
1. **Professional Overview** — role, top skills, experience highlights
2. **Platform Presence** — which platforms they're on, key stats (followers, repos, etc.)
3. **Notable Highlights** — best repos, talks, press mentions, articles
4. **Gaps & Recommendations** — platforms worth claiming, areas to grow presence

Data:
{json.dumps(snapshot, indent=2)}""",
            }
        ],
    )
    return response.content[0].text.strip()


def generate_report(
    resume_path: str,
    include_discovery: bool = True,
    context: str | None = None,
) -> dict:
    """
    Full end-to-end profile report: parse resume → scrape known links concurrently
    → discover new profiles → auto-scrape top discovered → AI-generated summary.
    """
    # 1. Parse resume
    resume = parse_resume(resume_path)
    name = resume.get("name", "Unknown")

    # 2. Scrape each known platform link concurrently
    links = [link for link in resume.get("links", []) if link.get("url")]
    known_urls = {link["url"] for link in links}
    scraped: dict = {}

    with ThreadPoolExecutor(max_workers=min(len(links), 5) or 1) as executor:
        futures = {executor.submit(_scrape_link, link): link for link in links}
        for future in as_completed(futures):
            platform_key, data = future.result()
            scraped[platform_key] = data

    # 3. Discover profiles and mentions not in the resume
    discovered: dict = {"profiles": [], "mentions": []}
    if include_discovery:
        search_context = context or _build_context(resume)
        discovered = search_web(name, list(known_urls), search_context)

    # 4. Auto-scrape top discovered profiles we have scrapers for
    extra = _scrape_discovered(discovered.get("profiles", []), known_urls)
    scraped.update(extra)

    # 5. AI summary
    summary = _generate_summary(name, resume, scraped, discovered)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "name": name,
        "resume": resume,
        "scraped_profiles": scraped,
        "discovered": discovered,
        "summary": summary,
    }


def summarize_presence(
    name: str,
    context: str | None = None,
) -> dict:
    """
    Internet presence report from a name alone — no resume needed.

    Runs web discovery across 40+ platforms, auto-scrapes top found profiles
    (GitHub, Twitter/X, Instagram), and generates an AI-written presence summary.
    """
    discovered = search_web(name, [], context)
    scraped = _scrape_discovered(discovered.get("profiles", []), set())
    summary = _generate_summary(name, {}, scraped, discovered)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "name": name,
        "scraped_profiles": scraped,
        "discovered": discovered,
        "summary": summary,
    }
