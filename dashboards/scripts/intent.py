"""自然语言 → 结构化报表需求.

这是一个规则 + 启发式解析器（v0.1）。

设计原则：
  - 不依赖任何 LLM 调用，纯本地规则
  - 解析失败时返回 best-effort，调用方决定是否回退到 LLM 自由生成
  - 时间/分组/图表类型都能从关键词推断

复杂需求（自由生成代码路径）由 render.py 在 intent 不确定时主动调用 LLM。
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from typing import Any


# ---------- 数据结构 ----------

@dataclass
class Intent:
    """结构化报表需求."""
    query: str
    metric: str = ""             # 度量字段: 金额/时长/数量/...
    group_by: str = ""           # 分组维度: 品类/星期/项目/...
    time_range: str = ""         # 自然语言描述: 上月/本周/过去 7 天
    time_start: str = ""         # ISO 日期 YYYY-MM-DD
    time_end: str = ""
    granularity: str = "auto"    # 日/周/月/年/auto
    chart_type: str = "auto"     # pie/bar/line/scatter/table/auto
    compare: bool = False        # 是否对比（vs 上期/去年同期）
    filters: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0      # 解析置信度 0..1
    needs_llm: bool = False      # 复杂需求 → 走 LLM 自由生成

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------- 关键词映射 ----------

# 度量关键词 → 字段名猜测（需配合 Notion schema 解析，这里是 hint）
METRIC_KEYWORDS = {
    "金额": ["金额", "钱", "花费", "支出", "收入", "cost", "price", "amount", "money", "支出", "消费"],
    "时长": ["时长", "时间", "耗时", "duration", "time", "分钟", "小时"],
    "距离": ["距离", "公里", "km", "distance"],
    "数量": ["数量", "次数", "count", "qty"],
    "心率": ["心率", "hr", "bpm"],
    "卡路里": ["卡路里", "热量", "cal", "calorie"],
}

# 分组关键词
GROUP_KEYWORDS = {
    "品类": ["品类", "类别", "分类", "category", "type"],
    "星期": ["星期", "礼拜", "周几", "weekday", "工作日", "周末"],
    "项目": ["项目", "任务", "project", "task"],
    "人": ["人", "用户", "user", "person"],
    "地点": ["地点", "位置", "location", "城市"],
    "标签": ["标签", "tag"],
}

# 图表类型关键词
CHART_KEYWORDS = {
    "pie": ["占比", "分布", "构成", "百分比", "share"],
    "bar": ["对比", "排行", "排名", "compare", "排名", "top"],
    "line": ["趋势", "走势", "变化", "随时间", "trend", "随", "每天", "每月"],
    "scatter": ["散点", "相关性", "correlation"],
    "table": ["表格", "明细", "列表", "table"],
}

# 时间范围
TIME_RANGES = {
    "今天": 0,
    "昨天": 1,
    "本周": 7,
    "上周": 14,
    "本月": 30,
    "上月": 60,
    "本季度": 90,
    "上季度": 180,
    "本年": 365,
    "去年": 730,
}


# ---------- 主入口 ----------

def parse(query: str) -> Intent:
    """解析自然语言查询为结构化 Intent."""
    q = query.strip()
    intent = Intent(query=q)

    # 1. 时间范围
    intent.time_range, days_back = _detect_time_range(q)
    intent.time_end = date.today().isoformat()
    intent.time_start = (date.today() - timedelta(days=days_back)).isoformat() if days_back else ""

    # 2. 度量
    intent.metric = _detect_metric(q)

    # 3. 分组
    intent.group_by = _detect_group_by(q)

    # 4. 图表类型
    intent.chart_type = _detect_chart_type(q)

    # 5. 粒度（根据时间跨度推断）
    if days_back > 0:
        intent.granularity = _infer_granularity(days_back)

    # 6. 对比
    intent.compare = bool(re.search(r"对比|vs|versus|比较|同期|上期|去年同期", q, re.I))

    # 7. 置信度 + 是否需要 LLM
    hits = sum([
        bool(intent.metric),
        bool(intent.group_by),
        bool(intent.time_range),
        intent.chart_type != "auto",
    ])
    intent.confidence = min(1.0, hits / 3.0)
    intent.needs_llm = intent.confidence < 0.4 or _is_complex(q)

    return intent


# ---------- 内部 ----------

def _detect_time_range(q: str) -> tuple[str, int]:
    """返回 (描述, 往前推的天数). 0 表示无明确时间范围."""
    # 优先匹配中文时间词
    for kw in ["今天", "昨天", "本周", "上周", "本月", "上月", "本季度", "上季度", "本年", "去年"]:
        if kw in q:
            return kw, TIME_RANGES[kw]

    # 匹配 "过去 N 天/周/月"
    m = re.search(r"过去\s*(\d+)\s*(天|周|月|年)", q)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        mult = {"天": 1, "周": 7, "月": 30, "年": 365}[unit]
        return f"过去{n}{unit}", n * mult

    # 匹配 "最近 N 天" 同上
    m = re.search(r"最近\s*(\d+)\s*(天|周|月|年)", q)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        mult = {"天": 1, "周": 7, "月": 30, "年": 365}[unit]
        return f"最近{n}{unit}", n * mult

    return "", 0


def _detect_metric(q: str) -> str:
    for name, kws in METRIC_KEYWORDS.items():
        for kw in kws:
            if kw in q.lower():
                return name
    return ""


def _detect_group_by(q: str) -> str:
    for name, kws in GROUP_KEYWORDS.items():
        for kw in kws:
            if kw in q.lower():
                return name
    return ""


def _detect_chart_type(q: str) -> str:
    q_lower = q.lower()
    for ctype, kws in CHART_KEYWORDS.items():
        for kw in kws:
            if kw in q_lower:
                return ctype
    return "auto"


def _infer_granularity(days: int) -> str:
    if days <= 7:
        return "日"
    if days <= 31:
        return "日"
    if days <= 90:
        return "周"
    if days <= 365:
        return "月"
    return "年"


def _is_complex(q: str) -> bool:
    """判断是否超出规则覆盖范围，需 LLM 自由生成."""
    # 包含复杂关键词
    complex_kws = [
        "桑基图", "地图", "热力图", "散点矩阵", "雷达图", "平行坐标",
        "相关性", "回归", "聚类", "sankey", "heatmap", "radar",
    ]
    q_lower = q.lower()
    return any(kw in q_lower for kw in complex_kws)


# ---------- CLI ----------

def main() -> None:
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser(description="Parse natural language report query.")
    parser.add_argument("--query", "-q", required=True, help="Natural language query")
    args = parser.parse_args()

    intent = parse(args.query)
    print(json.dumps(intent.to_dict(), ensure_ascii=False, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
