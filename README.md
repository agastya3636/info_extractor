# Profile Scraper MCP

An MCP server that takes your resume and finds your presence all over the internet — using direct links from the resume and targeted web discovery.

---

## Sprints

### Sprint 1 — Foundation ✅
- [x] MCP server scaffolded with FastMCP
- [x] `parse_resume` — parse PDF/DOCX resume into structured JSON
  - Extracts: name, email, phone, location, headline, links, skills, experience, education, certifications, projects
  - Uses Claude Sonnet to parse unstructured text

### Sprint 2 — Platform Scrapers ✅
- [x] `scrape_github` — bio, follower counts, top repos by stars via GitHub REST API
- [x] `scrape_linkedin` — name, headline, experience, education via Playwright + Claude Haiku extraction
- [x] `scrape_twitter` — name, handle, bio, location, follower/following counts via Playwright
- [x] `scrape_instagram` — full profile via API interception: name, handle, bio, profile pic, follower/following counts, verified/business status, and recent posts (captions, likes, comments, timestamps, video views). `max_posts` param scrolls for pagination beyond 12. Optional Tor IP rotation.
- [x] `scrape_instagram_batch` — parallel scraping of multiple Instagram profiles with checkpoint/resume, retry on block, and configurable concurrency + Tor pool rotation.

### Sprint 3 — Web Discovery ✅
- [x] `search_web` — find profiles and mentions not listed in resume
  - Searches **40+ platforms** across 5 categories:
    - **Professional/Tech**: GitHub, LinkedIn, Stack Overflow, Kaggle, HackerNews, Google Scholar, ResearchGate, Wellfound, Crunchbase, Product Hunt, Indie Hackers
    - **Social**: Instagram, Twitter/X, Facebook, TikTok, Reddit, Quora, Pinterest, Snapchat
    - **Content/Writing**: YouTube, Medium, Dev.to, Substack, Tumblr, WordPress, Hashnode
    - **Creative/Portfolio**: Behance, Dribbble, ArtStation, DeviantArt, Vimeo, SoundCloud, Bandcamp, Flickr, 500px
    - **Interests/Hobbies**: Goodreads, Letterboxd, Strava, Chess.com
  - Searches 4 discovery categories: talks/conferences, blogs/portfolio, news/press, open source contributions
  - Deduplicates results and skips URLs already in the resume
  - `context` param for disambiguation (e.g. `"photographer in Mumbai"` for common names)

### Sprint 4 — Report Generation ✅
- [x] `generate_report` — full end-to-end pipeline in one tool call
  - Parses resume → scrapes known links (concurrent) → discovers new profiles → auto-scrapes top discovered → AI summary
  - AI summary covers: professional overview, platform presence, notable highlights, gaps & recommendations
  - `include_discovery` flag to skip web search if you only want scraped data
  - Auto-builds disambiguation context from resume headline + company + location
- [x] `summarize_presence` — same pipeline but **no resume required** — just a name (and optional context)

---

## Setup

### 1. Create a virtual environment and install dependencies
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

### 2. Configure environment
```bash
cp .env.example .env
```

Edit `.env`:
```
ANTHROPIC_API_KEY=your_anthropic_api_key

# Optional: increases GitHub rate limit from 60/hr to 5000/hr
GITHUB_TOKEN=your_github_token

# LinkedIn auth — pick one of three options:
# Option 1 (fastest): single li_at cookie from browser DevTools
#   DevTools → Application → Cookies → linkedin.com → li_at
LINKEDIN_COOKIE=your_li_at_cookie_value

# Option 2: full cookies JSON exported via EditThisCookie Chrome extension
LINKEDIN_COOKIES_PATH=/path/to/linkedin_cookies.json

# Option 3: auto-login with email and password
LINKEDIN_EMAIL=your_linkedin_email
LINKEDIN_PASSWORD=your_linkedin_password

# Tor IP rotation — only needed if use_tor=True on Instagram scrapers
# Leave blank for CookieAuthentication (default on most distros)
# Set this if your torrc uses HashedControlPassword
TOR_CONTROL_PASSWORD=
```

### 3. Register with Claude Desktop

Add to `~/.config/claude/claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "profile-scraper": {
      "command": "/home/agastya/Desktop/info_scraper/.venv/bin/python",
      "args": ["/home/agastya/Desktop/info_scraper/server.py"]
    }
  }
}
```

---

## Tools

### `parse_resume(file_path)`
Parse a resume file (PDF or DOCX) into structured profile data.

**Input:** Absolute path to the file

**Output:**
```json
{
  "name": "John Doe",
  "email": "john@example.com",
  "phone": "+1-555-0100",
  "location": "San Francisco, CA",
  "headline": "Senior Software Engineer",
  "links": [
    { "platform": "GitHub", "url": "https://github.com/johndoe" },
    { "platform": "LinkedIn", "url": "https://linkedin.com/in/johndoe" }
  ],
  "skills": ["Python", "TypeScript", "Docker"],
  "experience": [{ "company": "Acme Corp", "role": "Engineer", "duration": "2022–Present", "description": null }],
  "education": [{ "institution": "MIT", "degree": "B.S. Computer Science", "year": "2022" }],
  "certifications": [],
  "projects": []
}
```

---

### `scrape_github(url)`
Fetch a GitHub profile and top repositories via the GitHub REST API.

**Input:** GitHub profile URL — `https://github.com/username`

**Output:**
```json
{
  "platform": "GitHub",
  "username": "johndoe",
  "name": "John Doe",
  "bio": "Building things.",
  "location": "San Francisco, CA",
  "followers": 1200,
  "following": 80,
  "public_repos": 34,
  "top_repos": [
    { "name": "cool-project", "stars": 450, "forks": 32, "language": "Python", "url": "..." }
  ]
}
```

---

### `scrape_linkedin(url)`
Scrape a LinkedIn profile using Playwright + Claude Haiku for extraction.

**Input:** LinkedIn profile URL — `https://linkedin.com/in/username`

**LinkedIn Auth Setup:**
LinkedIn blocks unauthenticated scrapers. Set one of the following in `.env` (in order of preference):
1. **`LINKEDIN_COOKIE`** — fastest. Copy the `li_at` cookie value from browser DevTools → Application → Cookies → linkedin.com
2. **`LINKEDIN_COOKIES_PATH`** — export all cookies via the [EditThisCookie](https://chrome.google.com/webstore/detail/editthiscookie) Chrome extension, save as JSON, set the path
3. **`LINKEDIN_EMAIL` + `LINKEDIN_PASSWORD`** — auto-login via Playwright (slower, more detectable)

**Output:**
```json
{
  "platform": "LinkedIn",
  "name": "John Doe",
  "headline": "Senior Software Engineer at Acme",
  "location": "San Francisco Bay Area",
  "about": "...",
  "experience": [{ "company": "Acme", "role": "Engineer", "duration": "2022–Present" }],
  "education": [{ "institution": "MIT", "degree": "B.S. CS", "year": "2022" }],
  "skills": ["Python", "System Design"]
}
```

---

### `scrape_twitter(url)`
Scrape a public Twitter/X profile using Playwright.

**Input:** Twitter/X profile URL — `https://x.com/username` or `https://twitter.com/username`

**Output:**
```json
{
  "platform": "Twitter/X",
  "name": "John Doe",
  "handle": "@johndoe",
  "bio": "Engineer. Building things.",
  "location": "San Francisco",
  "website": "https://johndoe.dev",
  "followers": "12.5K",
  "following": "300"
}
```

---

### `scrape_instagram(url, max_posts, use_tor)`
Scrape a public Instagram profile using Playwright with API interception.

**Args:**
- `url` — Instagram profile URL, e.g. `https://www.instagram.com/username/`
- `max_posts` *(default: 12)* — Number of posts to collect; set higher (e.g. `48`) to scroll and paginate
- `use_tor` *(default: false)* — Route through Tor SOCKS5 with circuit rotation (requires Tor on port 9050)

**Output:**
```json
{
  "platform": "Instagram",
  "username": "johndoe",
  "full_name": "John Doe",
  "bio": "Building things.",
  "followers": 4800,
  "following": 320,
  "posts_count": 87,
  "verified": false,
  "is_business": false,
  "business_category": null,
  "external_url": "https://johndoe.dev",
  "profile_pic_url": "https://...",
  "posts": [
    {
      "shortcode": "ABC123",
      "caption": "Latest post caption",
      "likes": 210,
      "comments": 14,
      "timestamp": "2026-04-01T12:00:00",
      "thumbnail": "https://...",
      "video_views": null
    }
  ]
}
```

---

### `scrape_instagram_batch(urls, checkpoint_path, use_tor, workers, delay, max_retries)`
Scrape a list of Instagram profiles in parallel with checkpoint/resume support.

**Args:**
- `urls` — List of Instagram profile URLs
- `checkpoint_path` *(default: `instagram_batch_progress.json`)* — File to save/resume progress
- `use_tor` *(default: false)* — Route through Tor with per-worker circuit rotation
- `workers` *(default: 3)* — Parallel browser contexts (max recommended: 5)
- `delay` *(default: 3.0)* — Seconds between requests per worker
- `max_retries` *(default: 2)* — Retry attempts on block before marking failed

**Output:**
```json
{
  "scraped": 5,
  "results": [
    { "username": "nasa", "followers": 98000000, "posts": [...] },
    { "username": "natgeo", "followers": 21000000, "posts": [...] }
  ]
}
```

---

### `search_web(name, known_links, context)`
Search the web for profiles and mentions not already in the resume.

**Args:**
- `name` — Full name of the person
- `known_links` *(optional)* — URLs from the resume to exclude from results
- `context` *(optional)* — Disambiguation text, e.g. `"Python developer at Google, San Francisco"`

**Output:**
```json
{
  "name": "Linus Torvalds",
  "total_discovered": 41,
  "profiles": [
    { "platform": "LinkedIn", "url": "https://linkedin.com/in/linustorvalds", "title": "...", "snippet": "..." }
  ],
  "mentions": [
    { "category": "Talk/Conference", "url": "https://computerhistory.org/profile/linus-torvalds/", "title": "...", "snippet": "..." }
  ]
}
```

---

### `generate_report(resume_path, include_discovery, context)`
Full end-to-end pipeline — one call does everything.

**Args:**
- `resume_path` — Absolute path to resume (PDF or DOCX)
- `include_discovery` *(default: true)* — Also run web discovery across 40+ platforms
- `context` *(optional)* — Disambiguation hint; auto-built from resume if omitted

**Pipeline:**
```
parse_resume → scrape known links concurrently (GitHub, LinkedIn, Twitter, Instagram)
             → search_web (40+ platforms + 4 discovery queries, parallelized)
             → auto-scrape top discovered profiles (GitHub, Twitter, Instagram)
             → Claude Sonnet AI summary
```

**Output:**
```json
{
  "generated_at": "2026-05-16T10:30:00Z",
  "name": "John Doe",
  "resume": { ... },
  "scraped_profiles": {
    "GitHub":   { "followers": 1200, "top_repos": [...] },
    "LinkedIn": { "headline": "...", "experience": [...] },
    "Twitter":  { "followers": "12.5K", "bio": "..." }
  },
  "discovered": {
    "total_discovered": 38,
    "profiles": [ { "platform": "Instagram", "url": "..." } ],
    "mentions": [ { "category": "Talk/Conference", "url": "..." } ]
  },
  "summary": "John Doe is a Senior Software Engineer...\n\n**Platform Presence**..."
}
```

---

### `summarize_presence(name, context)`
Internet presence report from a name alone — **no resume needed**.

**Args:**
- `name` — Full name of the person, e.g. `"Linus Torvalds"`
- `context` *(optional)* — Disambiguation hint, e.g. `"Linux kernel creator, Finland"`

**Pipeline:**
```
search_web (40+ platforms + 4 discovery queries)
→ auto-scrape top discovered profiles (GitHub, Twitter, Instagram)
→ Claude Sonnet AI summary
```

**Output:** Same shape as `generate_report` but without the `resume` key.

---

## Project Structure

```
info_scraper/
├── server.py                       ← MCP server entry point
├── tools/
│   ├── __init__.py
│   ├── parse_resume.py             ← Resume parser (PDF/DOCX → structured JSON)
│   ├── scrape_github.py            ← GitHub REST API scraper
│   ├── scrape_linkedin.py          ← LinkedIn Playwright scraper
│   ├── scrape_twitter.py           ← Twitter/X Playwright scraper
│   ├── scrape_instagram.py         ← Instagram API-interception scraper
│   ├── scrape_instagram_batch.py   ← Parallel Instagram batch scraper
│   ├── tor_proxy.py                ← Tor SOCKS5 proxy + circuit rotation
│   ├── search_web.py               ← Web discovery (DuckDuckGo, 40+ platforms, parallelized)
│   └── generate_report.py          ← End-to-end pipeline + AI summary
├── requirements.txt
├── .env.example
└── README.md
```
