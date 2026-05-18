import os
import requests
from urllib.parse import urlparse


def _username_from_url(url: str) -> str:
    path = urlparse(url).path.strip("/")
    return path.split("/")[0]


def scrape_github(url: str) -> dict:
    """Fetch a GitHub profile and top repos via the GitHub REST API."""
    username = _username_from_url(url)

    headers = {"Accept": "application/vnd.github.v3+json"}
    if token := os.getenv("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"

    user_resp = requests.get(
        f"https://api.github.com/users/{username}", headers=headers, timeout=10
    )
    user_resp.raise_for_status()
    u = user_resp.json()

    repos_resp = requests.get(
        f"https://api.github.com/users/{username}/repos",
        params={"sort": "stars", "per_page": 10, "type": "owner"},
        headers=headers,
        timeout=10,
    )
    repos = repos_resp.json() if repos_resp.ok else []

    return {
        "platform": "GitHub",
        "url": f"https://github.com/{username}",
        "username": username,
        "name": u.get("name"),
        "bio": u.get("bio"),
        "location": u.get("location"),
        "blog": u.get("blog") or None,
        "company": u.get("company"),
        "followers": u.get("followers"),
        "following": u.get("following"),
        "public_repos": u.get("public_repos"),
        "top_repos": [
            {
                "name": r["name"],
                "description": r.get("description"),
                "stars": r["stargazers_count"],
                "forks": r["forks_count"],
                "language": r.get("language"),
                "url": r["html_url"],
            }
            for r in repos
        ],
    }
