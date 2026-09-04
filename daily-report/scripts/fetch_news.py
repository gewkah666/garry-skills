#!/usr/bin/env python3
"""
fetch_news.py - 抓取真实新闻源(无需 API key)

数据源:
  - Hacker News (top stories)
  - 微博热搜 (weibo hot search)
  - GitHub Trending
  - V2EX (tech community)

返回结构化数据,供 daily-report.sh LLM 二次加工
"""
import json
import sys
import urllib.request


def fetch_hacker_news(limit=20):
    """HN Top Stories"""
    try:
        req = urllib.request.Request("https://hacker-news.firebaseio.com/v0/topstories.json")
        with urllib.request.urlopen(req, timeout=15) as resp:
            ids = json.loads(resp.read())[:limit]
        stories = []
        for sid in ids[:15]:
            try:
                req = urllib.request.Request(f"https://hacker-news.firebaseio.com/v0/item/{sid}.json")
                with urllib.request.urlopen(req, timeout=10) as resp:
                    item = json.loads(resp.read())
                stories.append({
                    "title": item.get("title", ""),
                    "score": item.get("score", 0),
                    "url": item.get("url", f"https://news.ycombinator.com/item?id={sid}"),
                    "by": item.get("by", ""),
                })
            except Exception:
                continue
        return stories
    except Exception as e:
        print(f"⚠️ HN fetch error: {e}", file=sys.stderr)
        return []


def fetch_github_trending(limit=15):
    """GitHub Trending (via GitHub search API, no key needed)"""
    # 查过去 7 天创建、star 数最高的 repo
    try:
        import datetime
        week_ago = (datetime.datetime.now() - datetime.timedelta(days=7)).strftime("%Y-%m-%d")
        url = f"https://api.github.com/search/repositories?q=created:>{week_ago}+stars:>100&sort=stars&order=desc&per_page={limit}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/vnd.github.v3+json"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        repos = []
        for r in data.get("items", [])[:limit]:
            repos.append({
                "name": r.get("full_name", ""),
                "description": r.get("description", "") or "",
                "language": r.get("language", "") or "",
                "stars": r.get("stargazers_count", 0),
                "url": r.get("html_url", ""),
            })
        return repos
    except Exception as e:
        print(f"⚠️ GitHub trending error: {e}", file=sys.stderr)
        return []


def fetch_weibo_hot(limit=20):
    """微博热搜(公开页面解析)"""
    try:
        req = urllib.request.Request(
            "https://s.weibo.com/top/summary",
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Cookie": "",  # 公开页面无需登录
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
        # 简单正则提取热搜标题(微博热搜页面有 td-02 节点)
        import re
        matches = re.findall(r'<a[^>]*target="_blank"[^>]*>([^<]+)</a>', html)
        # 过滤太短/含 html 标签的
        clean = [m.strip() for m in matches if 4 < len(m.strip()) < 30][:limit]
        return clean
    except Exception as e:
        print(f"⚠️ Weibo hot error: {e}", file=sys.stderr)
        return []


def main():
    import os
    source = sys.argv[1] if len(sys.argv) > 1 else "all"

    out = {}
    if source in ("hn", "all"):
        out["hn"] = fetch_hacker_news()
    if source in ("github", "all"):
        out["github"] = fetch_github_trending()
    if source in ("weibo", "all"):
        out["weibo"] = fetch_weibo_hot()

    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()