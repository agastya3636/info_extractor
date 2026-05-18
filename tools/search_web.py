import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from ddgs import DDGS

# Platform-specific queries — each finds profile pages
PLATFORM_QUERIES = [
    # --- Professional & Tech ---
    ("GitHub",          'site:github.com "{name}"'),
    ("LinkedIn",        'site:linkedin.com/in "{name}"'),
    ("Stack Overflow",  'site:stackoverflow.com/users "{name}"'),
    ("Kaggle",          'site:kaggle.com "{name}"'),
    ("HackerNews",      'site:news.ycombinator.com/user "{name}"'),
    ("Google Scholar",  'site:scholar.google.com "{name}"'),
    ("ResearchGate",    'site:researchgate.net "{name}"'),
    ("Wellfound",       'site:wellfound.com/u "{name}"'),
    ("Crunchbase",      'site:crunchbase.com/person "{name}"'),
    ("Product Hunt",    'site:producthunt.com "@{name}"'),
    ("Indie Hackers",   'site:indiehackers.com "{name}"'),

    # --- Social ---
    ("Instagram",       'site:instagram.com "{name}"'),
    ("Twitter/X",       '(site:twitter.com OR site:x.com) "{name}"'),
    ("Facebook",        'site:facebook.com "{name}"'),
    ("TikTok",          'site:tiktok.com "@{name}"'),
    ("Reddit",          'site:reddit.com/user "{name}"'),
    ("Quora",           'site:quora.com/profile "{name}"'),
    ("Pinterest",       'site:pinterest.com "{name}"'),
    ("Snapchat",        'site:snapchat.com/add "{name}"'),

    # --- Content & Writing ---
    ("YouTube",         'site:youtube.com "{name}"'),
    ("Medium",          'site:medium.com "{name}"'),
    ("Dev.to",          'site:dev.to "{name}"'),
    ("Substack",        'site:substack.com "{name}"'),
    ("Tumblr",          'site:tumblr.com "{name}"'),
    ("WordPress",       'site:wordpress.com "{name}"'),
    ("Hashnode",        'site:hashnode.dev "{name}"'),

    # --- Creative & Portfolio ---
    ("Behance",         'site:behance.net "{name}"'),
    ("Dribbble",        'site:dribbble.com "{name}"'),
    ("ArtStation",      'site:artstation.com "{name}"'),
    ("DeviantArt",      'site:deviantart.com "{name}"'),
    ("Vimeo",           'site:vimeo.com "{name}"'),
    ("SoundCloud",      'site:soundcloud.com "{name}"'),
    ("Bandcamp",        'site:bandcamp.com "{name}"'),
    ("Flickr",          'site:flickr.com/people "{name}"'),
    ("500px",           'site:500px.com "{name}"'),

    # --- Interests & Hobbies ---
    ("Goodreads",       'site:goodreads.com "{name}"'),
    ("Letterboxd",      'site:letterboxd.com "{name}"'),
    ("Strava",          'site:strava.com/athletes "{name}"'),
    ("Chess.com",       'site:chess.com/member "{name}"'),
]

# General discovery queries — talks, news, blogs
DISCOVERY_QUERIES = [
    ("Talk/Conference", '"{name}" (speaker OR keynote OR "gave a talk" OR "presented at")'),
    ("Blog/Portfolio",  '"{name}" (blog OR portfolio OR "personal website" OR "my projects")'),
    ("News/Press",      '"{name}" (interview OR "was featured" OR "press release")'),
    ("Open Source",     '"{name}" (contributor OR "pull request" OR "open source")'),
]

# Cap concurrent DuckDuckGo requests to avoid rate limiting
_sem = threading.Semaphore(5)


def _run_query(query: str) -> list[dict]:
    with _sem:
        try:
            results = DDGS().text(query, max_results=3) or []
            time.sleep(0.2)
            return results
        except Exception:
            return []


def _is_relevant(hit: dict, name: str) -> bool:
    """Require at least 2 name parts (or 1 for single-word names) in the result text."""
    parts = name.lower().split()
    text = f"{hit.get('title', '')} {hit.get('body', '')}".lower()
    return sum(p in text for p in parts) >= min(2, len(parts))


def search_web(
    name: str,
    known_links: list[str] | None = None,
    context: str | None = None,
) -> dict:
    """
    Search the web for a person's profiles and mentions across platforms.

    Runs targeted queries for 40+ platforms across 5 categories — professional/tech
    (GitHub, LinkedIn, Stack Overflow, Wellfound, Crunchbase…), social (Instagram,
    TikTok, Facebook, Reddit, Quora, Pinterest…), content (YouTube, Medium, Substack,
    WordPress…), creative (Behance, ArtStation, SoundCloud, Vimeo…), and hobbies
    (Goodreads, Letterboxd, Strava, Chess.com…). Plus 4 discovery searches for
    talks, blogs, news, and open source mentions. Known links from the resume are
    excluded so only new discoveries are returned.

    Args:
        name: Full name of the person to search for.
        known_links: URLs already known from the resume — excluded from results.
        context: Disambiguation text added to discovery queries, e.g.
                 "Python developer at Google, San Francisco". Crucial for
                 common names like "John Smith".
    """
    known = {_normalize(u) for u in (known_links or [])}
    # Context is only appended to open-ended discovery queries, not platform-scoped
    # site: queries where it can hurt recall (e.g. site:chess.com "John" "Engineer at Google")
    disc_suffix = f" {context}" if context else ""

    profiles: list[dict] = []
    mentions: list[dict] = []
    seen_urls: set[str] = set()

    # Build all (label, kind, query) tasks
    tasks: list[tuple[str, str, str]] = [
        (platform, "profile", template.format(name=name))
        for platform, template in PLATFORM_QUERIES
    ] + [
        (category, "mention", template.format(name=name) + disc_suffix)
        for category, template in DISCOVERY_QUERIES
    ]

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {
            executor.submit(_run_query, query): (label, kind)
            for label, kind, query in tasks
        }
        for future in as_completed(futures):
            label, kind = futures[future]
            for hit in future.result():
                url = hit.get("href", "")
                norm = _normalize(url)
                if not url or norm in known or norm in seen_urls:
                    continue
                if not _is_relevant(hit, name):
                    continue
                seen_urls.add(norm)
                entry = {
                    "url": url,
                    "title": hit.get("title"),
                    "snippet": hit.get("body"),
                }
                if kind == "profile":
                    profiles.append({"platform": label, **entry})
                else:
                    mentions.append({"category": label, **entry})

    return {
        "name": name,
        "context": context,
        "total_discovered": len(profiles) + len(mentions),
        "profiles": profiles,
        "mentions": mentions,
    }


def _normalize(url: str) -> str:
    return url.rstrip("/").lower().replace("https://", "").replace("http://", "")
