#!/usr/bin/env bash
# 每日科技/游戏日报 - 抓取真实新闻 + LLM 分类总结 + Notion 写入
# 不用 agent,直接 API 调用 + Python 抓取

set -e
YESTERDAY=$(date -v-1d '+%Y-%m-%d')
PRETTY=$(date -v-1d '+%Y年%-m月%-d日')
LOG_DIR="$HOME/.cache/anime-tracker"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/daily-report.log"
echo "[$(date '+%F %T')] ▶ Starting daily report for $YESTERDAY" >> "$LOG"

# 加载 hermes 环境(包含 MINIMAX_CN_API_KEY + NOTION_TOKEN)
for envfile in "$HOME/.hermes/.env" "$HOME/.hermes/trip-env.sh"; do
    if [ -f "$envfile" ]; then
        set -a
        source "$envfile"
        set +a
    fi
done

# 代理免疫：系统代理端口不可达时清空代理变量（避免 Connection refused）
source "$HOME/.hermes/scripts/proxy_guard.sh"

if [ -z "$NOTION_TOKEN" ]; then
    echo "[$(date '+%F %T')] ❌ Missing NOTION_TOKEN" >> "$LOG"
    exit 1
fi
if [ -z "$DEEPSEEK_API_KEY" ] && [ -z "$MINIMAX_CN_API_KEY" ]; then
    echo "[$(date '+%F %T')] ❌ Missing DEEPSEEK_API_KEY / MINIMAX_CN_API_KEY" >> "$LOG"
    exit 1
fi

# 全部逻辑在 Python 内,避免 shell quoting 问题
YESTERDAY="$YESTERDAY" PRETTY="$PRETTY" LOG_FILE="$LOG" python3 << 'PYEOF'
import json
import os
import re
import sys
import urllib.error
import urllib.request
import datetime

YESTERDAY = os.environ["YESTERDAY"]
PRETTY = os.environ["PRETTY"]
LOG_FILE = os.environ["LOG_FILE"]
NOTION_TOKEN = os.environ["NOTION_TOKEN"]
DB_ID = "747e9f3b-0bbf-4f03-b678-7fc62a093790"

# LLM 提供方: DeepSeek 优先 (OpenAI 兼容), MiniMax 回退 (Anthropic 兼容)
USE_DEEPSEEK = bool(os.environ.get("DEEPSEEK_API_KEY"))
API_KEY = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("MINIMAX_CN_API_KEY")
MODEL_NAME = "deepseek-v4-flash" if USE_DEEPSEEK else "MiniMax-M3"

# 强制直连：忽略任何继承的代理环境变量（cron 环境可能携带死代理 → Connection refused）
urllib.request.install_opener(urllib.request.build_opener(urllib.request.ProxyHandler({})))


def log(msg):
    with open(LOG_FILE, 'a') as f:
        f.write(f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}\n")
    print(msg)


log(f"   LLM 提供方: {'DeepSeek (' + MODEL_NAME + ')' if USE_DEEPSEEK else 'MiniMax (' + MODEL_NAME + ')'}")


def fetch_hn_top(limit=20):
    """HN Top Stories (无需 key)"""
    try:
        req = urllib.request.Request("https://hacker-news.firebaseio.com/v0/topstories.json")
        with urllib.request.urlopen(req, timeout=15) as resp:
            ids = json.loads(resp.read())[:limit]
        stories = []
        for sid in ids:
            try:
                req2 = urllib.request.Request(f"https://hacker-news.firebaseio.com/v0/item/{sid}.json")
                with urllib.request.urlopen(req2, timeout=10) as resp:
                    item = json.loads(resp.read())
                if item.get("type") == "story":
                    stories.append({
                        "title": item.get("title", ""),
                        "score": item.get("score", 0),
                        "url": item.get("url", f"https://news.ycombinator.com/item?id={sid}"),
                    })
            except Exception:
                continue
        return stories
    except Exception as e:
        log(f"   ⚠️ HN error: {e}")
        return []


def fetch_github_weekly(limit=15):
    """GitHub 过去7天最热门新 repo"""
    try:
        week_ago = (datetime.datetime.now() - datetime.timedelta(days=7)).strftime("%Y-%m-%d")
        url = f"https://api.github.com/search/repositories?q=created:>{week_ago}+stars:>50&sort=stars&order=desc&per_page={limit}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/vnd.github.v3+json"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        return [{
            "name": r.get("full_name", ""),
            "description": r.get("description", "") or "",
            "stars": r.get("stargazers_count", 0),
            "url": r.get("html_url", ""),
        } for r in data.get("items", [])[:limit]]
    except Exception as e:
        log(f"   ⚠️ GitHub error: {e}")
        return []


def fetch_rss_items(url, limit=15):
    """通用 RSS 抓取器"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            xml = resp.read().decode("utf-8", errors="ignore")
        items = re.findall(r'<item>(.*?)</item>', xml, re.DOTALL)
        news = []
        for item in items[:limit]:
            title_m = re.search(r'<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>', item, re.DOTALL)
            link_m = re.search(r'<link>(.*?)</link>', item, re.DOTALL)
            pub_m = re.search(r'<pubDate>(.*?)</pubDate>', item, re.DOTALL)
            if title_m and link_m:
                news.append({
                    "title": title_m.group(1).strip(),
                    "url": link_m.group(1).strip(),
                    "pub": pub_m.group(1).strip() if pub_m else "",
                })
        return news
    except Exception as e:
        log(f"   ⚠️ RSS error ({url}): {e}")
        return []


def fetch_ign_news(limit=15):
    """IGN 官方 RSS（feeds.ign.com，2026-08 实测可用，含最新 20 篇）"""
    return fetch_rss_items("https://feeds.ign.com/ign/all", limit)


def fetch_gematsu_news(limit=15):
    """Gematsu — 日系游戏新闻（新作/厂商动态密集，中文圈常用）"""
    return fetch_rss_items("https://www.gematsu.com/feed", limit)


# 1. 抓取多个数据源
log("   Fetching HN Top...")
hn = fetch_hn_top(20)
log(f"   HN: {len(hn)} stories")

log("   Fetching GitHub trending...")
gh = fetch_github_weekly(15)
log(f"   GitHub: {len(gh)} repos")

log("   Fetching IGN news...")
ign = fetch_ign_news(20)
log(f"   IGN: {len(ign)} news")

log("   Fetching Gematsu news...")
gematsu = fetch_gematsu_news(20)
log(f"   Gematsu: {len(gematsu)} news")

# 合并游戏源（去重，按标题去重保留先出现的）
game_all = ign + gematsu
seen_titles = set()
game_dedup = []
for n in game_all:
    t = n["title"].strip().lower()
    if t and t not in seen_titles:
        seen_titles.add(t)
        game_dedup.append(n)
game = game_dedup
log(f"   游戏新闻合计(去重后): {len(game)}")

if not game:
    log("   ⚠️ 所有游戏源均为空，游戏日报将输出空数组")

# 2. 拼接成 prompt (含真实新闻供 LLM 分类)
hn_text = "\n".join(f"- [{s['score']}] {s['title']}  ({s['url']})" for s in hn[:15])
gh_text = "\n".join(f"- ⭐{r['stars']} {r['name']}: {r['description'][:80]}  ({r['url']})" for r in gh[:12])
game_text = "\n".join(f"- [{n.get('pub','')[:16]}] {n['title']}  ({n['url']})" for n in game[:20])

PROMPT = f"""生成 {PRETTY} 的两条日报(每条 5 条要点)。

基于以下真实新闻数据源,**从中挑选最具价值的事件**生成内容。

# 科技日报候选(Hacker News + GitHub):
{hn_text}
{gh_text}

# 游戏日报候选(IGN + Gematsu):
{game_text}

要求:
- 每条要点严格基于上述候选,禁止凭空捏造;候选不足时宁缺毋滥
- 每条要点必须包含具体细节: 数字/日期/平台/厂商/金额等硬信息,不要泛泛而谈
- headline: 具体事件命名,20-40 字,含核心信息(如"XX公司发布YY芯片,性能提升40%")
- source: 来源名称(如 "Hacker News" / "IGN" / "Gematsu" / "GitHub: 作者/仓库")
- why: 为什么重要,60-120 字,说明影响对象与潜在后果
- 科技日报:AI/芯片/开源/大公司动态优先
- 游戏日报:新作发布/重大并购/电竞赛事优先,与游戏无关的候选不得入选
- 若某类候选为空,输出空数组 [],不要用其他类目凑数
- 输出 JSON (不要 ``` 包装),url 必须从候选括号中的链接原样复制,禁止编造:
{{"tech": [{{"headline": "...", "source": "...", "why": "...", "url": "https://..."}}, ...],
  "gaming": [{{"headline": "...", "source": "...", "why": "...", "url": "https://..."}}, ...]}}"""

def build_request(use_deepseek):
    if use_deepseek:
        # deepseek-v4-flash 是推理模型。2026-09-03/04 两晚都因为思考把 12000 token 预算
        # 用光、content 为空而失败 —— 日报是格式化提取，不需要思考，关掉。
        payload = json.dumps({
            "model": "deepseek-v4-flash",
            "max_tokens": 12000,
            "temperature": 0.7,
            "stream": False,
            "thinking": {"type": "disabled"},
            "messages": [{"role": "user", "content": PROMPT}],
        }).encode()
        return urllib.request.Request(
            "https://api.deepseek.com/v1/chat/completions", data=payload, method="POST",
            headers={"Authorization": f"Bearer {os.environ['DEEPSEEK_API_KEY']}", "Content-Type": "application/json"},
        )
    payload = json.dumps({
        "model": "MiniMax-M3",
        "max_tokens": 4000,
        "messages": [{"role": "user", "content": PROMPT}],
    }).encode()
    return urllib.request.Request(
        "https://api.minimaxi.com/anthropic/v1/messages", data=payload, method="POST",
        headers={"x-api-key": os.environ["MINIMAX_CN_API_KEY"], "anthropic-version": "2023-06-01", "Content-Type": "application/json"},
    )


def call(use_deepseek):
    req = build_request(use_deepseek)
    with urllib.request.urlopen(req, timeout=120) as resp:
        raw = resp.read().decode()
    with open(f"/Users/garry/.cache/anime-tracker/daily-report-raw-{YESTERDAY}.json", 'w') as f:
        f.write(raw)
    log(f"   API response {len(raw)} chars ({'deepseek' if use_deepseek else 'minimax'})")
    data = json.loads(raw)
    if data.get("error"):
        raise RuntimeError(str(data["error"])[:200])
    if use_deepseek:
        choice = (data.get("choices") or [{}])[0]
        text = choice.get("message", {}).get("content", "") or ""
        if not text.strip():
            raise RuntimeError("empty content (finish_reason=%s)" % choice.get("finish_reason"))
        return text
    text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
    if not text.strip():
        raise RuntimeError("empty content")
    return text


content = ""
attempts = ([True] if USE_DEEPSEEK else []) + ([False] if os.environ.get("MINIMAX_CN_API_KEY") else [])
for use_deepseek in attempts:
    try:
        content = call(use_deepseek)
        break
    except Exception as e:
        log(f"   ⚠️ {'deepseek' if use_deepseek else 'minimax'} failed: {e}")
if not content:
    log("   ❌ every provider failed")
    sys.exit(1)

# 3. 解析 JSON (支持 fence)
def parse_json_block(s):
    """从字符串中提取最外层 JSON 对象"""
    # fence 优先
    m = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', s, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except:
            pass
    # 平衡括号匹配
    start = s.find('{')
    if start < 0:
        return None
    depth = 0
    end = -1
    in_str = False
    escape = False
    for i in range(start, len(s)):
        c = s[i]
        if escape:
            escape = False
            continue
        if c == '\\':
            escape = True
            continue
        if c == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                end = i
                break
    if end > start:
        try:
            return json.loads(s[start:end+1])
        except:
            return None
    return None

parsed = parse_json_block(content)
if not parsed:
    log(f"   ⚠️ Parse failed, content: {content[:200]}")
    sys.exit(1)

tech = parsed.get("tech", [])
gaming = parsed.get("gaming", [])
log(f"   Parsed: tech={len(tech)}, gaming={len(gaming)}")

# 4. 写入 Notion
def write_page(name, items, tag):
    if not items:
        return None
    children = [
        {"object": "block", "type": "heading_2",
         "heading_2": {"rich_text": [{"type": "text", "text": {"content": f"🔥 {tag}头条"}}]}},
    ]
    bullets_text_parts = []
    for i, item in enumerate(items[:5]):
        # 兼容新旧格式
        if isinstance(item, dict):
            headline = item.get("headline", item.get("event", ""))
            source = item.get("source", "")
            why = item.get("why", "")
            url = item.get("url", "")
        else:
            headline = str(item)
            source = ""
            why = ""
            url = ""

        headline_rt = [{"type": "text", "text": {"content": headline[:100]}}]
        if url and url.startswith("http"):
            headline_rt = [{"type": "text", "text": {"content": headline[:100], "link": {"url": url[:2000]}}}]
        children.append({"object": "block", "type": "heading_3",
                         "heading_3": {"rich_text": headline_rt}})
        if source:
            src_rt = [{"type": "text", "text": {"content": "来源: "}, "annotations": {"bold": True}}]
            if url and url.startswith("http"):
                src_rt.append({"type": "text", "text": {"content": source[:100], "link": {"url": url[:2000]}}})
            else:
                src_rt.append({"type": "text", "text": {"content": source[:100]}})
            children.append({"object": "block", "type": "bulleted_list_item",
                             "bulleted_list_item": {"rich_text": src_rt}})
        if why:
            children.append({"object": "block", "type": "bulleted_list_item",
                             "bulleted_list_item": {"rich_text": [
                                 {"type": "text", "text": {"content": "为什么重要: "}, "annotations": {"bold": True}},
                                 {"type": "text", "text": {"content": why[:200]}}
                             ]}})

        bullets_text_parts.append(f"{i+1}. {headline}")

    short_review = "\n".join(bullets_text_parts)

    payload = {
        "parent": {"database_id": DB_ID},
        "properties": {
            "名字": {"title": [{"text": {"content": name}}]},
            "类型": {"select": {"name": "新闻"}},
            "状态": {"select": {"name": "已完成"}},
            "标签": {"multi_select": [{"name": "日报"}, {"name": tag}]},
            "上映/发布时间": {"date": {"start": YESTERDAY}},
            "时间线": {"date": {"start": YESTERDAY}},
            "短评": {"rich_text": [{"text": {"content": short_review[:2000]}}]},
        },
        "children": children,
    }
    req = urllib.request.Request(
        "https://api.notion.com/v1/pages",
        data=json.dumps(payload, ensure_ascii=False).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {NOTION_TOKEN}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            p = json.loads(resp.read())
            return p.get('url', 'OK')
    except urllib.error.HTTPError as e:
        return f"ERROR: {e.code} {e.read().decode()[:200]}"


if tech:
    url = write_page(f"科技日报 — {PRETTY}", tech, "科技")
    log(f"   科技: {url}")
    print(f"科技: {url}")
if gaming:
    url = write_page(f"游戏日报 — {PRETTY}", gaming, "游戏")
    log(f"   游戏: {url}")
    print(f"游戏: {url}")

log("✓ Daily report complete")
PYEOF

# 显式传递 python 阶段退出码（防止 set -e 对 heredoc 失效导致 cron 误判成功）
_rc=$?
if [ $_rc -ne 0 ]; then
    echo "[$(date '+%F %T')] ✗ python 阶段失败 (rc=$_rc)" >> "$LOG"
    exit $_rc
fi

echo "✓ Done"