# finance-manager · cron 蓝图

| 名字 | 时间 | 形式 | 入口 |
|---|---|---|---|
| `finance-export-reminder` | `30 7 1 * *` | agent prompt：`phantom_notify level=L1 kind=finance`「该导出上月钱迹账单了，发给我就导入并出月报」 | 提醒御主导出 |
| `finance-monthly-report` | `0 8 1 * *` | no-agent 脚本 | `~/.hermes/scripts/finance-monthly-report.sh` → `_skill_cron.sh` → `scripts/monthly_report.sh` → `finance_cli.py report --month last` |

做什么：同步镜像 → 聚合上月（收入 / 支出 / 结余、环比、一级二级分类、每日与累计、商户 Top 10、大额 Top 10、账户月初月末余额、30 天未对账账户）→ 渲染 `templates/monthly.html.tmpl`（在 plugin 仓库里）→ 上传 dashboards → 写阅览世界一页（类型=财务，标签 财务 / 月报，链接指向报告）→ `phantom reach.notify L1 kind=finance` 飞书一句话带链接。
同一个月只生成一次（状态记在 `finance.db` 的 `sync_state` 里，`report:<YYYY-MM>`）；要重做加 `--force`，会新传一份报告并更新同一个阅览世界页。
需要 `~/.hermes/.env` 里的 `API_SERVER_KEY`、`DASHBOARDS_PLUGIN_URL`、`DASHBOARDS_PAGE_BASE`，Notion token 按 plugin 的顺序找。日志 `~/.cache/finance-manager/monthly.log`。
月报里若最后一条记录早于月末 25 日，飞书消息会提示「钱迹可能还没导入」；导入后 `finance_cli.py report --month <月> --force` 重做。
重建：`hermes cron create --name finance-export-reminder --deliver local "30 7 1 * *" "用 phantom_notify level=L1 kind=finance 提醒御主：该导出上月的钱迹账单（xlsx）发给我了，收到就导入并出月报。回 [SILENT]。"`
重建：`hermes cron create --name finance-monthly-report --script finance-monthly-report.sh --no-agent --deliver local "0 8 1 * *"`
补跑 / 看某月：`scripts/finance_cli.py report --month 2026-08 --no-notify`。
每次运行在 Phantom 事件库留一条 `cron:finance-monthly-report`。
