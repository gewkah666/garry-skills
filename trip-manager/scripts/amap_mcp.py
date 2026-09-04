#!/usr/bin/env python3
"""
amap_mcp.py - 高德地图 MCP server（stdio 协议）

暴露 6 个工具:
  - geocode: 地理编码
  - poi_search: POI 搜索
  - route_plan: 路径规划
  - weather_query: 天气查询
  - plan_trip: 完整行程规划（整合）
  - trip_distance: 直线距离（带备用实现）
"""
from __future__ import annotations
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

AMAP_BASE = "https://restapi.amap.com/v3"


def get_api_key() -> str:
    key = os.environ.get("AMAP_API_KEY")
    if not key:
        return ""
    return key


def call_amap(endpoint: str, params: dict) -> dict:
    """调用高德 API"""
    key = get_api_key()
    if not key:
        return {"status": "0", "info": "AMAP_API_KEY 未设置", "infocode": "MISSING_KEY"}
    params["key"] = key
    params["output"] = "JSON"
    url = f"{AMAP_BASE}/{endpoint}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return {"status": "0", "info": f"HTTP {e.code}", "infocode": str(e.code)}
    except urllib.error.URLError as e:
        return {"status": "0", "info": f"网络错误: {e}", "infocode": "NETWORK_ERROR"}


# ============= 工具实现 =============

def tool_geocode(args: dict) -> dict:
    """地理编码: 地名 → 坐标"""
    address = args.get("address", "")
    city = args.get("city", "")
    if not address:
        return {"success": False, "error": "缺少 address 参数"}

    result = call_amap("geocode/geo", {"address": address, "city": city})
    if result.get("status") != "1":
        return {"success": False, "error": result.get("info", "查询失败"), "raw": result}

    geocodes = result.get("geocodes", [])
    if not geocodes:
        return {"success": False, "error": f"未找到: {address}"}

    g = geocodes[0]
    return {
        "success": True,
        "address": address,
        "location": g.get("location"),  # "lng,lat"
        "formatted_address": g.get("formatted_address"),
        "city": g.get("city"),
        "adcode": g.get("adcode"),
    }


def tool_poi_search(args: dict) -> dict:
    """POI 搜索"""
    keyword = args.get("keyword", "")
    city = args.get("city", "")
    limit = min(int(args.get("limit", 10)), 25)
    if not keyword:
        return {"success": False, "error": "缺少 keyword 参数"}

    result = call_amap("place/text", {
        "keywords": keyword,
        "city": city,
        "citylimit": "true" if city else "false",
        "extensions": "all",
        "offset": str(limit),
    })
    if result.get("status") != "1":
        return {"success": False, "error": result.get("info", "搜索失败")}

    pois = result.get("pois", [])
    return {
        "success": True,
        "count": len(pois),
        "pois": [
            {
                "name": p.get("name"),
                "address": p.get("address"),
                "location": p.get("location"),
                "type": p.get("type"),
                "rating": p.get("biz_ext", {}).get("rating", "") if "biz_ext" in p else "",
            }
            for p in pois
        ],
    }


def tool_route_plan(args: dict) -> dict:
    """路径规划 A→B"""
    origin = args.get("origin", "")
    destination = args.get("destination", "")
    mode = args.get("mode", "driving")
    if not origin or not destination:
        return {"success": False, "error": "缺少 origin 或 destination"}

    # 地理编码起终点
    o = call_amap("geocode/geo", {"address": origin})
    if not o.get("geocodes"):
        return {"success": False, "error": f"起点未找到: {origin}"}
    d = call_amap("geocode/geo", {"address": destination})
    if not d.get("geocodes"):
        return {"success": False, "error": f"终点未找到: {destination}"}

    origin_loc = o["geocodes"][0]["location"]
    dest_loc = d["geocodes"][0]["location"]
    origin_name = o["geocodes"][0].get("formatted_address", origin)
    dest_name = d["geocodes"][0].get("formatted_address", destination)

    mode_map = {
        "driving": "direction/driving",
        "walking": "direction/walking",
        "riding": "direction/riding",
        "transit": "direction/transit/integrated",
    }
    amap_mode = mode_map.get(mode, "driving")

    params = {"origin": origin_loc, "destination": dest_loc}
    if mode == "transit":
        city = o["geocodes"][0].get("citycode", "")
        params["city"] = city

    result = call_amap(amap_mode, params)
    if result.get("status") != "1":
        return {
            "success": False,
            "error": result.get("info", "路径规划失败"),
            "hint": "路径规划 API 可能未开通,前往 https://lbs.amap.com/ 申请",
        }

    paths_data = []
    if mode == "transit":
        for t in result.get("transits", [])[:3]:
            paths_data.append({
                "duration_min": (int(t.get("duration", 0)) + 59) // 60,
                "distance_km": round(float(t.get("distance", 0)) / 1000, 1),
                "cost_yuan": float(t.get("cost", 0)),
            })
    else:
        for p in result.get("route", {}).get("paths", [])[:3]:
            paths_data.append({
                "duration_min": (int(p.get("duration", 0)) + 59) // 60,
                "distance_km": round(float(p.get("distance", 0)) / 1000, 1),
                "cost_yuan": float(p.get("cost", 0)),
                "tolls_yuan": float(p.get("tolls", 0)),
            })

    return {
        "success": True,
        "mode": mode,
        "origin": {"name": origin_name, "location": origin_loc},
        "destination": {"name": dest_name, "location": dest_loc},
        "paths": paths_data,
    }


def tool_weather_query(args: dict) -> dict:
    """天气查询"""
    city = args.get("city", "")
    extensions = args.get("extensions", "all")  # base(实时) / all(预报)
    if not city:
        return {"success": False, "error": "缺少 city 参数"}

    # 地理编码
    geo = call_amap("geocode/geo", {"address": city})
    if not geo.get("geocodes"):
        return {"success": False, "error": f"未找到城市: {city}"}
    adcode = geo["geocodes"][0].get("adcode")
    if not adcode:
        return {"success": False, "error": "未获取到 adcode"}

    result = call_amap("weather/weatherInfo", {
        "city": adcode,
        "extensions": extensions,
    })
    if result.get("status") != "1":
        return {"success": False, "error": result.get("info", "天气查询失败")}

    if extensions == "base":
        return {"success": True, "type": "current", "weather": result.get("lives", [])}

    # forecast
    forecasts = result.get("forecasts", [])
    if not forecasts:
        return {"success": False, "error": "无天气预报数据"}
    f = forecasts[0]
    return {
        "success": True,
        "type": "forecast",
        "city": f"{f.get('province')} {f.get('city')}",
        "report_time": f.get("reporttime"),
        "forecast": [
            {
                "date": c.get("date"),
                "week": c.get("week"),
                "day_weather": c.get("dayweather"),
                "day_temp": c.get("daytemp"),
                "day_wind": c.get("daywind"),
                "day_power": c.get("daypower"),
                "night_weather": c.get("nightweather"),
                "night_temp": c.get("nighttemp"),
                "night_wind": c.get("nightwind"),
                "night_power": c.get("nightpower"),
            }
            for c in f.get("casts", [])
        ],
    }


def tool_plan_trip(args: dict) -> dict:
    """完整行程规划"""
    origin = args.get("origin", "")
    destination = args.get("destination", "")
    days = int(args.get("days", 3))
    if not origin or not destination:
        return {"success": False, "error": "缺少 origin 或 destination"}

    # 路径规划
    route = tool_route_plan({"origin": origin, "destination": destination, "mode": "driving"})

    # POI 搜索
    poi = tool_poi_search({"keyword": destination, "limit": 8})

    # 天气
    weather = tool_weather_query({"city": destination, "extensions": "all"})

    return {
        "success": True,
        "origin": origin,
        "destination": destination,
        "days": days,
        "route": route,
        "pois": poi,
        "weather": weather,
    }


def tool_trip_distance(args: dict) -> dict:
    """直线距离 + 驾车距离"""
    origin = args.get("origin", "")
    destination = args.get("destination", "")
    if not origin or not destination:
        return {"success": False, "error": "缺少 origin 或 destination"}

    # 直线距离（用地理编码坐标 + haversine 公式）
    o = call_amap("geocode/geo", {"address": origin})
    if not o.get("geocodes"):
        return {"success": False, "error": f"起点未找到: {origin}"}
    d = call_amap("geocode/geo", {"address": destination})
    if not d.get("geocodes"):
        return {"success": False, "error": f"终点未找到: {destination}"}

    o_lng, o_lat = map(float, o["geocodes"][0]["location"].split(","))
    d_lng, d_lat = map(float, d["geocodes"][0]["location"].split(","))

    from math import radians, sin, cos, asin, sqrt
    def haversine(lng1, lat1, lng2, lat2):
        lng1, lat1, lng2, lat2 = map(radians, [lng1, lat1, lng2, lat2])
        dlat = lat2 - lat1
        dlng = lng2 - lng1
        a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlng/2)**2
        c = 2 * asin(sqrt(a))
        r = 6371
        return c * r

    straight_km = round(haversine(o_lng, o_lat, d_lng, d_lat), 2)

    return {
        "success": True,
        "origin": origin,
        "destination": destination,
        "straight_distance_km": straight_km,
        "origin_coords": o["geocodes"][0]["location"],
        "destination_coords": d["geocodes"][0]["location"],
    }


# ============= MCP stdio 协议实现 =============

TOOLS = [
    {
        "name": "amap_geocode",
        "description": "高德地理编码:地名 → 经纬度坐标(支持城市限定)",
        "input_schema": {
            "type": "object",
            "properties": {
                "address": {"type": "string", "description": "地址/地名"},
                "city": {"type": "string", "description": "城市限定(可选)"},
            },
            "required": ["address"],
        },
    },
    {
        "name": "amap_poi_search",
        "description": "高德 POI 搜索:景点/酒店/餐厅等兴趣点",
        "input_schema": {
            "type": "object",
            "properties": {
                "keyword": {"type": "string"},
                "city": {"type": "string"},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["keyword"],
        },
    },
    {
        "name": "amap_route_plan",
        "description": "高德路径规划:A→B 距离/时间/费用 (driving/walking/transit/riding)",
        "input_schema": {
            "type": "object",
            "properties": {
                "origin": {"type": "string"},
                "destination": {"type": "string"},
                "mode": {"type": "string", "enum": ["driving", "walking", "transit", "riding"], "default": "driving"},
            },
            "required": ["origin", "destination"],
        },
    },
    {
        "name": "amap_weather",
        "description": "高德天气查询:实时(base)或预报(all,4天)",
        "input_schema": {
            "type": "object",
            "properties": {
                "city": {"type": "string"},
                "extensions": {"type": "string", "enum": ["base", "all"], "default": "all"},
            },
            "required": ["city"],
        },
    },
    {
        "name": "amap_plan_trip",
        "description": "完整行程规划:整合路径+景点+天气",
        "input_schema": {
            "type": "object",
            "properties": {
                "origin": {"type": "string"},
                "destination": {"type": "string"},
                "days": {"type": "integer", "default": 3},
            },
            "required": ["origin", "destination"],
        },
    },
    {
        "name": "amap_trip_distance",
        "description": "直线距离计算(无需路径规划 API)",
        "input_schema": {
            "type": "object",
            "properties": {
                "origin": {"type": "string"},
                "destination": {"type": "string"},
            },
            "required": ["origin", "destination"],
        },
    },
]

TOOL_HANDLERS = {
    "amap_geocode": tool_geocode,
    "amap_poi_search": tool_poi_search,
    "amap_route_plan": tool_route_plan,
    "amap_weather": tool_weather_query,
    "amap_plan_trip": tool_plan_trip,
    "amap_trip_distance": tool_trip_distance,
}


def send_message(msg: dict):
    """发送 JSON-RPC 消息"""
    body = json.dumps(msg, ensure_ascii=False)
    sys.stdout.write(f"Content-Length: {len(body.encode('utf-8'))}\r\n\r\n")
    sys.stdout.write(body)
    sys.stdout.flush()


def read_message() -> dict | None:
    """读取 JSON-RPC 消息"""
    headers = {}
    while True:
        line = sys.stdin.readline().strip()
        if not line:
            break
        if ":" in line:
            k, v = line.split(":", 1)
            headers[k.strip()] = v.strip()
    length = int(headers.get("Content-Length", 0))
    if not length:
        return None
    body = sys.stdin.read(length)
    return json.loads(body)


def handle_initialize(msg: dict) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": msg["id"],
        "result": {
            "protocolVersion": "2024-11-05",
            "serverInfo": {"name": "amap-mcp", "version": "1.0.0"},
            "capabilities": {"tools": {}},
        },
    }


def handle_list_tools(msg: dict) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": msg["id"],
        "result": {"tools": TOOLS},
    }


def handle_call_tool(msg: dict) -> dict:
    name = msg["params"]["name"]
    args = msg["params"].get("arguments", {})
    handler = TOOL_HANDLERS.get(name)
    if not handler:
        return {
            "jsonrpc": "2.0",
            "id": msg["id"],
            "error": {"code": -32601, "message": f"未知工具: {name}"},
        }
    try:
        result = handler(args)
        return {
            "jsonrpc": "2.0",
            "id": msg["id"],
            "result": {
                "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}],
                "isError": not result.get("success", False),
            },
        }
    except Exception as e:
        return {
            "jsonrpc": "2.0",
            "id": msg["id"],
            "result": {
                "content": [{"type": "text", "text": json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)}],
                "isError": True,
            },
        }


def main():
    """MCP stdio 事件循环"""
    while True:
        msg = read_message()
        if not msg:
            break
        method = msg.get("method")
        if method == "initialize":
            send_message(handle_initialize(msg))
        elif method == "notifications/initialized":
            pass  # 客户端通知,无需响应
        elif method == "tools/list":
            send_message(handle_list_tools(msg))
        elif method == "tools/call":
            send_message(handle_call_tool(msg))
        else:
            if "id" in msg:
                send_message({
                    "jsonrpc": "2.0",
                    "id": msg["id"],
                    "error": {"code": -32601, "message": f"未实现方法: {method}"},
                })


if __name__ == "__main__":
    main()