#!/usr/bin/env python3
"""
Auto-update the "My Contributions" section of the profile README.

Discovers every repository Naeem-Shuvo has contributed to (own repos AND
external/open-source repos) via the GitHub Search API, then rewrites the
table between the CONTRIBUTIONS:START / CONTRIBUTIONS:END markers.

Runs inside GitHub Actions with the built-in GITHUB_TOKEN — no personal
access token needed. Future contributions appear automatically.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import date

USERNAME = "Naeem-Shuvo"
README_PATH = "README.md"
START_MARKER = "<!-- CONTRIBUTIONS:START -->"
END_MARKER = "<!-- CONTRIBUTIONS:END -->"
TOKEN = os.environ.get("GITHUB_TOKEN", "")


def gh_get(url: str, accept: str = "application/vnd.github+json") -> dict:
    """GET a GitHub API URL with auth + basic retry on rate limits."""
    headers = {"Accept": accept, "User-Agent": USERNAME}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code in (403, 429) and attempt < 2:
                time.sleep(30 * (attempt + 1))  # back off on rate limit
                continue
            raise
    return {}


def search_all(base_url: str, accept: str = "application/vnd.github+json") -> list:
    """Paginate through a GitHub Search API endpoint (max 1000 results)."""
    items, page = [], 1
    while page <= 10:
        data = gh_get(f"{base_url}&per_page=100&page={page}", accept)
        batch = data.get("items", [])
        items.extend(batch)
        if not batch or len(items) >= data.get("total_count", 0):
            break
        page += 1
        time.sleep(2)  # be gentle with the Search API
    return items


def main() -> None:
    stats: dict[str, dict] = {}

    # 1) Every pull request authored by the user, anywhere on GitHub
    prs = search_all(
        f"https://api.github.com/search/issues?q=author:{USERNAME}+type:pr"
    )
    for pr in prs:
        repo = "/".join(pr["repository_url"].split("/")[-2:])
        s = stats.setdefault(repo, {"prs": 0, "commits": 0})
        s["prs"] += 1

    # 2) Every commit authored by the user, anywhere on GitHub
    commits = search_all(
        f"https://api.github.com/search/commits?q=author:{USERNAME}",
        accept="application/vnd.github.cloak-preview+json",
    )
    for c in commits:
        repo = c["repository"]["full_name"]
        s = stats.setdefault(repo, {"prs": 0, "commits": 0})
        s["commits"] += 1

    # Don't list the profile README repo itself
    stats.pop(f"{USERNAME}/{USERNAME}", None)

    if not stats:
        print("No contributions found — leaving README untouched.")
        return

    # 3) Enrich each repo with metadata (description, language, stars)
    rows = []
    for repo, s in stats.items():
        try:
            meta = gh_get(f"https://api.github.com/repos/{repo}")
        except urllib.error.HTTPError:
            meta = {}  # repo may be deleted/private — keep counts anyway
        owner = repo.split("/")[0]
        rows.append({
            "repo": repo,
            "url": meta.get("html_url", f"https://github.com/{repo}"),
            "desc": (meta.get("description") or "—").replace("|", "\\|"),
            "lang": meta.get("language") or "—",
            "stars": meta.get("stargazers_count", 0),
            "prs": s["prs"],
            "commits": s["commits"],
            "external": owner.lower() != USERNAME.lower(),
        })
        time.sleep(1)

    # External (open-source) contributions first, then by activity volume
    rows.sort(key=lambda r: (not r["external"], -(r["prs"] * 3 + r["commits"])))

    # 4) Build the markdown table
    lines = [
        "",
        "| Repository | Description | Language | ⭐ | PRs | Commits | Type |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        kind = "🌍 Open Source" if r["external"] else "🏠 Personal"
        desc = r["desc"] if len(r["desc"]) <= 60 else r["desc"][:57] + "..."
        lines.append(
            f"| [{r['repo']}]({r['url']}) | {desc} | {r['lang']} "
            f"| {r['stars']} | {r['prs']} | {r['commits']} | {kind} |"
        )
    lines.append("")
    lines.append(
        f"*Last updated: {date.today().isoformat()} "
        "(auto-refreshes daily via GitHub Actions)*"
    )
    lines.append("")
    table = "\n".join(lines)

    # 5) Splice the table into the README between the markers
    with open(README_PATH, encoding="utf-8") as f:
        readme = f.read()

    start = readme.find(START_MARKER)
    end = readme.find(END_MARKER)
    if start == -1 or end == -1 or end < start:
        print("Markers not found in README.md", file=sys.stderr)
        sys.exit(1)

    updated = (
        readme[: start + len(START_MARKER)] + "\n" + table + "\n" + readme[end:]
    )

    if updated != readme:
        with open(README_PATH, "w", encoding="utf-8") as f:
            f.write(updated)
        print(f"README updated with {len(rows)} repositories.")
    else:
        print("No changes detected.")


if __name__ == "__main__":
    main()
