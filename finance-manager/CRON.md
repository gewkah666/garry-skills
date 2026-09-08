# finance-manager · cron 蓝图

| 名字 | 时间 | 形式 | 状态 |
|---|---|---|---|
| `finance-monthly-report` | `0 8 1 * *` | no-agent 脚本：`~/.hermes/scripts/finance-monthly-report.sh` → `_skill_cron.sh` → `scripts/monthly_report.sh` | M3，未建 |

做什么：`finance_cli.py report --month last` → 聚合上月 → 渲染 `templates/monthly.html.tmpl` → 上传 dashboards → 写阅览世界一页（类型=财务）→ `phantom_notify` 飞书一句话带链接。
重建：`hermes cron create --name finance-monthly-report --script finance-monthly-report.sh --no-agent --deliver local "0 8 1 * *"`
补跑：`scripts/finance_cli.py report --month 2026-09`。
每次运行在 Phantom 事件库留一条 `cron:finance-monthly-report`。
