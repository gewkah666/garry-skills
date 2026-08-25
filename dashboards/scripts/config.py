"""Dashboards skill 配置.

集中管理所有可调参数。环境变量可覆盖默认值。
"""
from __future__ import annotations

import os
from pathlib import Path


def _env(name: str, default: str) -> str:
    v = os.environ.get(name)
    return v if v is not None and v != "" else default


# Hermes 本地服务地址（dashboard 默认端口）
PLUGIN_URL = _env("DASHBOARDS_PLUGIN_URL", "http://localhost:8000/api/plugins/dashboards")

# 报表页面 base URL（生成报表后拼接 dash_id 得到 public_url）
PAGE_BASE = _env("DASHBOARDS_PAGE_BASE", "/api/plugins/dashboards/page")

# plugin 上传鉴权 — Hermes dashboard session token
# 在 Hermes 会话里运行时，从环境变量 HERMES_SESSION_TOKEN 读
HERMES_TOKEN = _env("HERMES_SESSION_TOKEN", "")

# Notion API key（可选，仅在脚本独立运行时需要；Hermes 会话内通过 MCP 调 Notion）
NOTION_API_KEY = _env("NOTION_API_KEY", "")

# skill 自身路径
SKILL_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = SKILL_DIR / "templates"
EXAMPLES_DIR = SKILL_DIR / "examples"


# ---------- 上传/渲染辅助 ----------

def upload_headers() -> dict[str, str]:
    """构造调 plugin API 用的 headers."""
    if not HERMES_TOKEN:
        # 独立跑脚本时没有 token，plugin 会 401 — 这是预期行为
        return {"Content-Type": "application/json"}
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {HERMES_TOKEN}",
    }
