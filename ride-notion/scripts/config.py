"""ride-notion config"""
from pathlib import Path

# === 路径配置 ===
SKILL_DIR = Path(__file__).parent.parent

# === .env 加载（共用 garry-skills 那份） ===
def _load_env():
    env = {}
    for path in [
        SKILL_DIR / ".env",
        Path.home() / ".hermes" / ".env",
        Path.home() / "Library/Application Support/cn.org.hermesagent.desktop/runtime/hermes-home/.env",
    ]:
        try:
            for line in open(path):
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip().strip('"').strip("'")
        except (FileNotFoundError, PermissionError):
            pass
    return env

ENV = _load_env()


class Config:
    NOTION_API_KEY = ENV.get("NOTION_API_KEY", "")
    NOTION_DIARY_DB_ID = ENV.get("NOTION_DIARY_DB_ID", "747e9f3b-0bbf-4f03-b678-7fc62a093790")
    SELECT_TYPE_DAILY = "日常"
    SELECT_STATUS_LOGGED = "已记录"
    DEFAULT_MAX_HR = 190
