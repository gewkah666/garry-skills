#!/usr/bin/env python3
"""
trip_common.py - trip-manager 各脚本共用的小工具

* 时区：所有"人看的时间"统一为北京时间（Asia/Shanghai, UTC+8）
* 元数据：Outlook 事件 body 里的 `键：值` 行（起点 / 终点 / 交通 / 项目 / 停留 / 要点 / 时限 / 费用）
  —— 这是 Outlook ↔ Notion ↔ 行程地图 之间唯一的结构化契约，写和读都走这里
* 事件：拉取 calendarView、按日分组、把一天的事件聚合成一个「Day」结构
* 高德：带本地缓存的地理编码 / 驾车耗时
"""
from __future__ import annotations

import html
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, List, Optional, Tuple

SKILL_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SKILL_DIR))

CACHE_DIR = Path.home() / ".cache" / "trip-manager"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
GEO_CACHE = CACHE_DIR / "geocode.json"

TZ_CN = timezone(timedelta(hours=8))
NOTION_DB_ID = "747e9f3b-0bbf-4f03-b678-7fc62a093790"  # 阅览世界

# ---------------------------------------------------------------- 时间

def now_cn() -> datetime:
    return datetime.now(TZ_CN)


def parse_graph_dt(date_str: str) -> datetime:
    """Graph 返回的 UTC 字符串（'2026-10-01T00:00:00.0000000' / '...Z'）→ 北京时间"""
    clean = date_str.split(".")[0]
    if clean.endswith("Z"):
        dt = datetime.fromisoformat(clean.replace("Z", "+00:00"))
    else:
        dt = datetime.fromisoformat(clean).replace(tzinfo=timezone.utc)
    return dt.astimezone(TZ_CN)


def to_graph_dt(s: str) -> dict:
    """'2026-10-01T08:00:00+08:00' 或 '2026-10-01T08:00' → Graph 的 {dateTime, timeZone}（按北京时间解释无时区输入）"""
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ_CN)
    dt = dt.astimezone(TZ_CN)
    return {"dateTime": dt.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": "China Standard Time"}


def day_range(day: str) -> Tuple[str, str]:
    """'2026-10-01' → (当天 00:00+08, 次日 00:00+08) ISO 字符串"""
    d = datetime.fromisoformat(day).replace(tzinfo=TZ_CN)
    return d.isoformat(), (d + timedelta(days=1)).isoformat()


def parse_minutes(s: str) -> Optional[int]:
    """'90' / '90分钟' / '1.5h' / '1小时30分' → 分钟"""
    if not s:
        return None
    s = s.strip().lower()
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(h|小时|hr)\s*(\d+)?\s*(分钟?|min)?", s)
    if m:
        return int(float(m.group(1)) * 60 + int(m.group(3) or 0))
    m = re.fullmatch(r"(\d+)\s*(分钟?|min|m)?", s)
    if m:
        return int(m.group(1))
    return None

# ---------------------------------------------------------------- 元数据（body 契约）

META_KEYS = ("项目", "起点", "终点", "交通", "停留", "要点", "时限", "费用")
_META_RE = re.compile(r"^\s*(项目|起点|终点|交通|停留|要点|时限|费用)\s*[：:]\s*(.*?)\s*$")

TRANSPORT_NAMES = {
    "飞机": "✈️ 飞机", "航班": "✈️ 飞机",
    "高铁": "🚞 高铁", "火车": "🚞 高铁", "动车": "🚞 高铁",
    "汽车": "🚗 汽车", "自驾": "🚗 汽车", "开车": "🚗 汽车", "打车": "🚗 汽车", "大巴": "🚗 汽车",
    "船": "🚢 船", "轮渡": "🚢 船",
    "步行": "🚶 步行", "走路": "🚶 步行",
    "骑行": "🚲 骑行", "单车": "🚲 骑行",
}
TRANSPORT_EMOJI = {
    "🚗": "🚗 汽车", "🚙": "🚗 汽车", "🚕": "🚗 汽车", "🚌": "🚗 汽车",
    "🚞": "🚞 高铁", "🚄": "🚞 高铁", "🚆": "🚞 高铁", "🚅": "🚞 高铁",
    "✈️": "✈️ 飞机", "✈": "✈️ 飞机", "🛩️": "✈️ 飞机",
    "🚢": "🚢 船", "⛴": "🚢 船", "🚤": "🚢 船",
    "🚶": "🚶 步行", "🥾": "🚶 步行",
    "🚲": "🚲 骑行", "🚴": "🚲 骑行",
}

EMOJI_RE = re.compile(
    "[\U0001F300-\U0001F5FF\U0001F600-\U0001F64F\U0001F680-\U0001F6FF"
    "\U0001F700-\U0001F77F\U0001F900-\U0001F9FF\U0001FA00-\U0001FAFF"
    "\U00002600-\U000027BF\U0001F1E0-\U0001F1FF][️]?"
)
ARROW_RE = re.compile(r"\s*(?:→|->|➡|>)\s*")
TRANSIT_TITLE_RE = re.compile(r"^(?:前往|开往|开车[去到往]|驱车|返回|返程|飞往|乘.{0,6}?[去到往]|去)")


def normalize_transport(text: Optional[str]) -> Optional[str]:
    """'汽车' / '🚗' / '✈️ 飞机 CA1234' → 规范化的 select 名；识别不了返回原文"""
    if not text:
        return None
    for emoji, name in TRANSPORT_EMOJI.items():
        if emoji in text:
            return name
    for word, name in TRANSPORT_NAMES.items():
        if word in text:
            return name
    return text.strip() or None


def first_emoji(text: str) -> str:
    m = EMOJI_RE.search(text or "")
    return m.group(0) if m else ""


def strip_emoji(text: str) -> str:
    return re.sub(r"\s{2,}", " ", EMOJI_RE.sub("", text or "")).strip()


class _TextExtractor(HTMLParser):
    BLOCK = {"br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4"}

    def __init__(self):
        super().__init__()
        self.parts: List[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("style", "script", "head"):
            self._skip += 1
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("style", "script", "head"):
            self._skip = max(0, self._skip - 1)
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_lines(content: str, content_type: str = "html") -> List[str]:
    if not content:
        return []
    if content_type.lower() == "text":
        text = content
    else:
        p = _TextExtractor()
        p.feed(content)
        text = html.unescape("".join(p.parts))
    return [ln.strip() for ln in text.replace("\r", "").split("\n") if ln.strip()]


def parse_meta(body: Optional[dict]) -> dict:
    """
    Outlook body → {"meta": {键: 值}, "notes": [自由文本行]}
    body 可以是 Graph 的 {contentType, content}，也可以是纯字符串
    """
    if isinstance(body, dict):
        lines = html_to_lines(body.get("content", ""), body.get("contentType", "html"))
    else:
        lines = html_to_lines(body or "", "text")
    meta: Dict[str, str] = {}
    notes: List[str] = []
    for ln in lines:
        m = _META_RE.match(ln)
        if m:
            if m.group(2):
                meta[m.group(1)] = m.group(2)
        else:
            notes.append(ln)
    return {"meta": meta, "notes": notes}


def build_body(notes: Optional[str] = None, **meta) -> str:
    """反向：自由描述 + 元数据 → Outlook HTML body。键名用 META_KEYS 的中文，或英文别名"""
    alias = {"project": "项目", "origin": "起点", "destination": "终点", "transport": "交通",
             "dwell": "停留", "note": "要点", "guard": "时限", "cost": "费用"}
    lines: List[str] = []
    if notes:
        lines.extend(html.escape(x) for x in notes.replace("\r", "").split("\n") if x.strip())
    for k in META_KEYS:
        v = meta.get(k)
        if v is None:
            for en, zh in alias.items():
                if zh == k and meta.get(en) is not None:
                    v = meta[en]
        if v is None or str(v).strip() == "":
            continue
        if k == "交通":
            v = normalize_transport(str(v)) or v
        if k == "停留" and isinstance(v, int):
            v = f"{v}分钟"
        lines.append(f"{k}：{html.escape(str(v))}")
    return "<br>".join(lines)

# ---------------------------------------------------------------- 事件

# 同一本 Outlook 日历上其它 skill 建的事件（按 category 识别），行程相关脚本一律忽略
IGNORE_CATEGORY_WORDS = ("权益活动", "信用卡")


def is_trip_event(ev: dict) -> bool:
    cats = " ".join(ev.get("categories") or [])
    return not any(w in cats for w in IGNORE_CATEGORY_WORDS)


def fetch_events(start_iso: str, end_iso: str, only_trips: bool = True) -> List[dict]:
    """calendarView（含 body，用于读元数据），按开始时间排序，自动翻页；默认过滤掉非行程事件"""
    from outlook_event import graph_request  # 延迟导入：避免循环

    params = urllib.parse.urlencode({
        "startDateTime": start_iso,
        "endDateTime": end_iso,
        "$orderby": "start/dateTime",
        "$top": "100",
        "$select": "id,subject,start,end,location,body,categories,isAllDay",
    })
    path = f"/me/calendarView?{params}"
    events: List[dict] = []
    while path:
        result = graph_request("GET", path)
        events.extend(result.get("value", []))
        nxt = result.get("@odata.nextLink")
        path = nxt.split("/v1.0", 1)[1] if nxt and "/v1.0" in nxt else None
    return [ev for ev in events if is_trip_event(ev)] if only_trips else events


DAY_LABEL_RE = re.compile(r"^\s*(Day\s*\d+)(?:-\d+)?\s*[-:：]\s*(.+)$", re.IGNORECASE)


def clean_title(subject: str) -> Tuple[str, Optional[str]]:
    """'Day2-1: 双桥沟' → ('双桥沟', 'Day2')；'Day2 - 双桥沟' → ('双桥沟', 'Day2')"""
    m = DAY_LABEL_RE.match(subject or "")
    if m:
        return m.group(2).strip(), m.group(1).replace(" ", "")
    return (subject or "").strip(), None


def event_to_stop(ev: dict) -> dict:
    """单个 Outlook 事件 → 结构化站点（契约在这一处定义，其它脚本只消费）"""
    start = parse_graph_dt(ev["start"]["dateTime"])
    end = parse_graph_dt(ev["end"]["dateTime"]) if ev.get("end") else None
    parsed = parse_meta(ev.get("body"))
    meta, notes = parsed["meta"], parsed["notes"]
    subject = ev.get("subject", "")
    cleaned, day_label = clean_title(subject)
    location = (ev.get("location") or {}).get("displayName", "") or ""

    origin = meta.get("起点") or None
    destination = meta.get("终点") or None
    # 标题里 "A→B" 也当作起终点（无 body 元数据时的兜底）
    if not (origin and destination):
        plain = strip_emoji(cleaned)
        parts = [p for p in ARROW_RE.split(plain) if p]
        if len(parts) >= 2:
            origin = origin or parts[0]
            destination = destination or parts[-1]

    transport = normalize_transport(meta.get("交通"))
    if not transport:
        for cat in ev.get("categories") or []:
            transport = normalize_transport(cat)
            if transport:
                break
    if not transport:
        for emoji, name in TRANSPORT_EMOJI.items():
            if emoji in subject:
                transport = name
                break

    is_transit = bool(origin and destination)
    if not is_transit and TRANSIT_TITLE_RE.match(strip_emoji(cleaned)):
        is_transit, destination = True, destination or location or None
    place = destination if is_transit else (location or destination or origin or strip_emoji(cleaned))
    dwell = parse_minutes(meta.get("停留", ""))
    if dwell is None and end and not is_transit and not ev.get("isAllDay"):
        dwell = int((end - start).total_seconds() // 60) or None

    icon = first_emoji(subject)
    if not icon:
        icon = transport.split()[0] if (transport and is_transit) else "📍"

    return {
        "id": ev.get("id"),
        "subject": subject,
        "title": strip_emoji(cleaned),
        "day_label": day_label,
        "start": start,
        "end": end,
        "time": start.strftime("%H:%M"),
        "end_time": end.strftime("%H:%M") if end else "",
        "all_day": bool(ev.get("isAllDay")),
        "icon": icon,
        "location": location,
        "origin": origin,
        "destination": destination,
        "place": place,
        "is_transit": is_transit,
        "transport": transport,
        "dwell_min": dwell,
        "note": meta.get("要点"),
        "guard": meta.get("时限"),
        "cost": meta.get("费用"),
        "project": meta.get("项目"),
        "notes": notes,
    }


def group_by_day(events: List[dict]) -> Dict[str, List[dict]]:
    """events → {'2026-10-01': [stop, ...]}（北京日期，按时间排序）"""
    by_day: Dict[str, List[dict]] = defaultdict(list)
    for ev in events:
        stop = event_to_stop(ev)
        by_day[stop["start"].strftime("%Y-%m-%d")].append(stop)
    return {k: sorted(v, key=lambda s: s["start"]) for k, v in sorted(by_day.items())}


def aggregate_day(day_key: str, stops: List[dict]) -> dict:
    """一天的站点 → Day 结构（标题 / icon / 路线 / 交通 / 项目），供 Notion 归档和地图共用"""
    route: List[str] = []

    def push(name: Optional[str]):
        if name and name not in route:
            route.append(name)

    for s in stops:
        if s["is_transit"]:
            push(s["origin"])
            push(s["destination"])
        else:
            push(s["location"] or s["place"])

    day_label = next((s["day_label"] for s in stops if s["day_label"]), None)
    project = next((s["project"] for s in stops if s["project"]), None)
    transports = []
    for s in stops:
        if s["transport"] and s["transport"] not in transports:
            transports.append(s["transport"])
    icon = next((s["icon"] for s in stops if s["icon"] and s["icon"] not in TRANSPORT_EMOJI), None) \
        or (stops[0]["icon"] if stops else "📍")

    prefix = day_label or day_key[5:]
    if not route:
        title = f"{prefix} - 出行"
    elif len(route) == 1:
        title = f"{prefix} - {route[0]}"
    elif len(route) == 2:
        title = f"{prefix} - {route[0]}→{route[-1]}"
    else:
        title = f"{prefix} - {route[0]}→{route[-1]} ({len(route)}站)"

    return {
        "day_key": day_key,
        "day_label": day_label,
        "title": title,
        "icon": icon,
        "route": route,
        "origin": route[0] if route else None,
        "destination": route[-1] if route else None,
        "transport": transports[0] if transports else None,
        "transports": transports,
        "project": project,
        "stops": stops,
    }

# ---------------------------------------------------------------- 高德（带缓存）

AMAP_BASE = "https://restapi.amap.com/v3"


def amap_key() -> str:
    key = os.environ.get("AMAP_API_KEY", "")
    if key:
        return key
    env_file = Path.home() / ".hermes" / "trip-env.sh"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("export AMAP_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


_last_call = [0.0]


def amap_get(endpoint: str, params: dict, timeout: int = 12) -> dict:
    """个人 key 有 QPS 限制（CUQPS_HAS_EXCEEDED_THE_LIMIT），两次调用之间至少隔 0.35s，限流时重试一次"""
    import time
    key = amap_key()
    if not key:
        return {"status": "0", "info": "AMAP_API_KEY 未设置"}
    params = dict(params, key=key, output="JSON")
    url = f"{AMAP_BASE}/{endpoint}?{urllib.parse.urlencode(params)}"
    for attempt in (1, 2):
        wait = 0.35 - (time.monotonic() - _last_call[0])
        if wait > 0:
            time.sleep(wait)
        _last_call[0] = time.monotonic()
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                data = json.loads(resp.read())
        except Exception as e:  # noqa: BLE001
            return {"status": "0", "info": str(e)}
        if data.get("infocode") == "10021" and attempt == 1:  # QPS 超限
            time.sleep(1.2)
            continue
        return data
    return data


def _load_geo_cache() -> dict:
    try:
        return json.loads(GEO_CACHE.read_text())
    except Exception:  # noqa: BLE001
        return {}


_ADMIN_SUFFIX = ("省", "市", "县", "区", "镇", "乡", "村", "路", "街")  # 机场 / 车站 / 酒店 走 POI 更准


def _poi_lookup(name: str, region: str) -> Optional[dict]:
    """景点 / 地名走 POI 搜索（比地址编码准得多：'双桥沟' 地址编码会落到乐山犍为）"""
    params = {"keywords": name, "offset": "5", "extensions": "base"}
    if region:
        params.update(city=region, citylimit="true")
    data = amap_get("place/text", params)
    if data.get("status") != "1":
        return {"error": data.get("info", "poi error")}
    for p in data.get("pois") or []:
        pname = p.get("name", "")
        if _name_matches(name, pname) and p.get("location"):
            lng, lat = p["location"].split(",")
            return {"lng": float(lng), "lat": float(lat), "address": f"{pname}（{p.get('type', '').split(';')[0]}）", "via": "poi"}
    return None


def _name_matches(query: str, poi_name: str) -> bool:
    """查询名须是 POI 名的子序列且 POI 名不能长太多：'成都天府机场' ≈ '成都天府国际机场'；'杭州萧山机场' ≠ '杭州'"""
    if not poi_name or len(poi_name) - len(query) > 6:
        return False
    it = iter(poi_name)
    return all(ch in it for ch in query)


def _addr_lookup(query: str, city: str, name: Optional[str] = None) -> Optional[dict]:
    data = amap_get("geocode/geo", {"address": query, "city": city})
    if data.get("status") != "1":
        return {"error": data.get("info", "geocode error")}
    for g in data.get("geocodes") or []:
        # 只给到省/市一级的结果等于没查到（'四川省墨石公园' 会退化成成都市中心）
        if g.get("level") in ("省", "市", "国家") or not g.get("location"):
            continue
        # 地址里要能按顺序找到地名的每个字（'四川省杭州萧山机场' 会被拆成盐源县的"杭州"）
        it = iter(g.get("formatted_address", ""))
        if name and not all(ch in it for ch in name):
            continue
        lng, lat = g["location"].split(",")
        return {"lng": float(lng), "lat": float(lat), "address": g.get("formatted_address", ""), "via": "geocode"}
    return None


def geocode(name: str, region: str = "", city: str = "") -> Optional[dict]:
    """
    地名 → {"lng","lat","address","via"}。查不到返回 None（不猜）；接口 / 网络错误返回 {"error": ...}。
    结果缓存在 ~/.cache/trip-manager/geocode.json（键 = region+name），歧义地名可手改缓存文件。
    策略：行政区 / 机场 / 车站 / 酒店 → 地址编码优先；其它（景点、湖、寺）→ POI 搜索优先，互为兜底。
    """
    if not name:
        return None
    cache = _load_geo_cache()
    key = name if (region and name.startswith(region)) else f"{region}{name}"
    if key in cache:
        return cache[key] or None
    admin_like = name.endswith(_ADMIN_SUFFIX) or name.startswith(region or "\0")
    in_region = [lambda: _addr_lookup(key, city, name), lambda: _poi_lookup(name, region)]
    if not admin_like:
        in_region.reverse()
    # 区域内找不到（行程起终点常在省外，如出发机场）→ 放开区域再找
    anywhere = [lambda: _poi_lookup(name, ""), lambda: _addr_lookup(name, city, name)] if region else []
    err = None
    for fn in in_region + anywhere:
        hit = fn()
        if hit and "error" in hit:
            err = hit
            continue
        if hit:
            cache[key] = hit
            GEO_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1))
            return hit
    if err:
        return err  # 网络 / 配额问题：不缓存
    cache[key] = None
    GEO_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1))
    return None


def driving_minutes(a: dict, b: dict) -> Optional[Tuple[int, float]]:
    """两个坐标间的驾车 (分钟, 公里)。路径规划未开通/失败返回 None"""
    data = amap_get("direction/driving", {
        "origin": f"{a['lng']},{a['lat']}", "destination": f"{b['lng']},{b['lat']}",
        "strategy": "0", "extensions": "base",
    }, timeout=15)
    paths = (data.get("route") or {}).get("paths") or []
    if data.get("status") != "1" or not paths:
        return None
    p = paths[0]
    return (int(p.get("duration", 0)) + 59) // 60, round(float(p.get("distance", 0)) / 1000, 1)
