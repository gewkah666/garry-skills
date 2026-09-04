#!/usr/bin/env python3
"""
amap.py - 高德地图 API CLI

子命令:
  poi        POI 搜索 (景点/酒店/餐厅)
  route      路径规划 A→B
  weather    天气查询
  geocode    地理编码 地名→坐标
  plan-trip  完整行程规划（整合）
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

AMAP_BASE = "https://restapi.amap.com/v3"


def get_api_key() -> str:
    key = os.environ.get("AMAP_API_KEY")
    if not key:
        print("❌ 请设置环境变量 AMAP_API_KEY", file=sys.stderr)
        print("   申请地址: https://lbs.amap.com/dev/key/app", file=sys.stderr)
        sys.exit(1)
    return key


def call_amap(endpoint: str, params: dict) -> dict:
    """调用高德 API"""
    params["key"] = get_api_key()
    params["output"] = "JSON"
    url = f"{AMAP_BASE}/{endpoint}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"❌ HTTP {e.code}: {e.read().decode()}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"❌ 网络错误: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_geocode(args):
    """地理编码: 地名 → 坐标"""
    result = call_amap("geocode/geo", {
        "address": args.address,
        "city": args.city or "",
    })
    if result.get("status") != "1":
        print(f"❌ {result.get('info', '未知错误')}")
        return
    geocodes = result.get("geocodes", [])
    if not geocodes:
        print(f"❌ 未找到: {args.address}")
        return
    g = geocodes[0]
    print(f"📍 {args.address}")
    print(f"   坐标: {g.get('location')}")
    print(f"   详细地址: {g.get('formatted_address')}")
    if g.get("city"):
        print(f"   城市: {g['city']} ({g.get('adcode')})")


def cmd_poi(args):
    """POI 搜索"""
    result = call_amap("place/text", {
        "keywords": args.keyword,
        "city": args.city or "",
        "citylimit": "true" if args.city else "false",
        "extensions": "all",
        "offset": str(args.limit),
    })
    if result.get("status") != "1":
        print(f"❌ {result.get('info')}")
        return
    pois = result.get("pois", [])
    if not pois:
        print(f"📭 未找到 '{args.keyword}'")
        return
    print(f"🔍 '{args.keyword}' 找到 {len(pois)} 个结果:\n")
    for i, p in enumerate(pois, 1):
        name = p.get("name", "?")
        addr = p.get("address", "")
        loc = p.get("location", "")
        ptype = p.get("type", "")
        rating = p.get("biz_ext", {}).get("rating", "") if "biz_ext" in p else ""
        print(f"  {i}. {name}")
        if addr:
            print(f"     地址: {addr}")
        if loc:
            print(f"     坐标: {loc}")
        if ptype:
            print(f"     类型: {ptype}")
        if rating:
            print(f"     评分: {rating}")
        print()


def cmd_route(args):
    """路径规划"""
    # 地理编码起终点
    origin_res = call_amap("geocode/geo", {"address": args.origin})
    if not origin_res.get("geocodes"):
        print(f"❌ 起点未找到: {args.origin}")
        return
    dest_res = call_amap("geocode/geo", {"address": args.destination})
    if not dest_res.get("geocodes"):
        print(f"❌ 终点未找到: {args.destination}")
        return

    origin = origin_res["geocodes"][0]["location"]
    dest = dest_res["geocodes"][0]["location"]
    origin_name = origin_res["geocodes"][0].get("formatted_address", args.origin)
    dest_name = dest_res["geocodes"][0].get("formatted_address", args.destination)

    # 路径规划
    # 高德 API 路径:direction/driving, direction/walking, direction/transit/integrated, direction/riding
    mode_map = {
        "driving": "direction/driving",
        "walking": "direction/walking",
        "transit": "direction/transit/integrated",
        "riding": "direction/riding",
    }
    amap_mode = mode_map.get(args.mode, "driving")

    if args.mode == "transit":
        # 公交需要 city 参数
        city = origin_res["geocodes"][0].get("citycode", "")
        params = {"origin": origin, "destination": dest, "city": city}
    else:
        params = {"origin": origin, "destination": dest}

    result = call_amap(amap_mode, params)
    if result.get("status") != "1":
        print(f"❌ {result.get('info')}")
        return

    print(f"🚗 {args.mode}: {origin_name}")
    print(f"   → {dest_name}\n")

    if args.mode == "transit":
        # 公交返回 transits
        transits = result.get("transits", [])
        for i, t in enumerate(transits[:3], 1):
            duration_min = (int(t.get("duration", 0)) + 59) // 60
            distance_km = float(t.get("distance", 0)) / 1000
            cost = float(t.get("cost", 0))
            print(f"  方案 {i}: {duration_min} 分钟, {distance_km:.1f} km, ¥{cost:.2f}")
    else:
        paths = result.get("route", {}).get("paths", [])
        for i, p in enumerate(paths[:3], 1):
            duration_min = (int(p.get("duration", 0)) + 59) // 60
            distance_km = float(p.get("distance", 0)) / 1000
            cost = float(p.get("cost", 0))
            tolls = float(p.get("tolls", 0))
            print(f"  方案 {i}: {duration_min} 分钟, {distance_km:.1f} km, ¥{cost:.2f} (路桥费 ¥{tolls:.2f})")


def cmd_weather(args):
    """天气查询"""
    # 1. 地理编码
    geo = call_amap("geocode/geo", {"address": args.city, "city": ""})
    if not geo.get("geocodes"):
        print(f"❌ 未找到城市: {args.city}")
        return
    adcode = geo["geocodes"][0].get("adcode")
    if not adcode:
        print(f"❌ 未获取到 adcode")
        return

    # 2. 天气查询
    result = call_amap("weather/weatherInfo", {
        "city": adcode,
        "extensions": args.extensions,
    })
    if result.get("status") != "1":
        print(f"❌ {result.get('info')}")
        return

    lives = result.get("lives", [])
    if lives and args.extensions == "base":
        for w in lives:
            print(f"🌤️ {w.get('province')} {w.get('city')} 当前天气:")
            print(f"   天气: {w.get('weather')}")
            print(f"   温度: {w.get('temperature')}°C")
            print(f"   风向: {w.get('winddirection')}风")
            print(f"   风力: {w.get('windpower')}级")
            print(f"   湿度: {w.get('humidity')}%")
            print(f"   发布时间: {w.get('reporttime')}")
        return

    forecasts = result.get("forecasts", [])
    if forecasts:
        for f in forecasts:
            print(f"🌤️ {f.get('province')} {f.get('city')} 天气预报:\n")
            casts = f.get("casts", [])
            for c in casts:
                print(f"  📅 {c.get('date')} ({c.get('week')})")
                print(f"     白天: {c.get('dayweather')} {c.get('daytemp')}°C {c.get('daywind')}风{c.get('daypower')}级")
                print(f"     夜间: {c.get('nightweather')} {c.get('nighttemp')}°C {c.get('nightwind')}风{c.get('nightpower')}级")
                print()


def cmd_plan_trip(args):
    """完整行程规划"""
    print(f"🗺️  规划 {args.days} 天行程: {args.origin} → {args.destination}\n")

    # 1. 路径规划（单程）
    print("=" * 50)
    print("📍 路途信息")
    print("=" * 50)
    args.mode = "driving"
    try:
        cmd_route(args)
    except SystemExit:
        print("   ⚠️  路径规划未开通,跳过")
    print()

    # 2. 目的地 POI
    print("=" * 50)
    print(f"🔍 {args.destination} 热门景点")
    print("=" * 50)
    # 复用 cmd_poi（构造 Namespace）
    poi_args = argparse.Namespace(
        keyword=args.destination,
        city="",
        limit=8,
    )
    cmd_poi(poi_args)
    print()

    # 3. 天气
    print("=" * 50)
    print(f"🌤️ {args.destination} 天气预报")
    print("=" * 50)
    weather_args = argparse.Namespace(
        city=args.destination,
        extensions="all",
    )
    cmd_weather(weather_args)


def main():
    ap = argparse.ArgumentParser(description="高德地图 CLI")
    sub = ap.add_subparsers(dest="cmd", required=True)

    # geocode
    p = sub.add_parser("geocode", help="地理编码")
    p.add_argument("--address", required=True)
    p.add_argument("--city", help="限制城市")

    # poi
    p = sub.add_parser("poi", help="POI 搜索")
    p.add_argument("--keyword", required=True)
    p.add_argument("--city", help="限制城市")
    p.add_argument("--limit", type=int, default=10)

    # route
    p = sub.add_parser("route", help="路径规划")
    p.add_argument("--origin", required=True)
    p.add_argument("--destination", required=True)
    p.add_argument("--mode", default="driving", choices=["driving", "walking", "transit", "riding"])

    # weather
    p = sub.add_parser("weather", help="天气查询")
    p.add_argument("--city", required=True)
    p.add_argument("--extensions", default="all", choices=["base", "all"])

    # plan-trip
    p = sub.add_parser("plan-trip", help="完整行程规划")
    p.add_argument("--origin", required=True)
    p.add_argument("--destination", required=True)
    p.add_argument("--days", type=int, default=3)

    args = ap.parse_args()

    cmd_map = {
        "geocode": cmd_geocode,
        "poi": cmd_poi,
        "route": cmd_route,
        "weather": cmd_weather,
        "plan-trip": cmd_plan_trip,
    }
    cmd_map[args.cmd](args)


if __name__ == "__main__":
    main()