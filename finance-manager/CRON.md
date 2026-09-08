# finance-manager · cron 蓝图

| 名字 | 时间 | 形式 | 入口 |
|---|---|---|---|
| `finance-monthly-report` | `0 8 1 * *` | no-agent 脚本 | `~/.hermes/scripts/finance-monthly-report.sh` → `_skill_cron.sh` → `scripts/monthly_report.sh` → `finance_cli.py report --month last` |

做什么：同步镜像 → 聚合上月（收入 / 支出 / 结余、环比、一级二级分类、每日与累计、商户 Top 10、大额 Top 10、账户月初月末余额、30 天未对账账户）→ 渲染 `templates/monthly.html.tmpl`（在 plugin 仓库里）→ 上传 dashboards → 写阅览世界一页（类型=财务，标签 财务 / 月报，链接指向报告）→ `phantom reach.notify L1 kind=finance` 飞书一句话带链接。
同一个月只生成一次（状态记在 `finance.db` 的 `sync_state` 里，`report:<YYYY-MM>`）；要重做加 `--force`，会新传一份报告并更新同一个阅览世界页。
需要 `~/.hermes/.env` 里的 `API_SERVER_KEY`、`DASHBOARDS_PLUGIN_URL`、`DASHBOARDS_PAGE_BASE`，Notion token 按 plugin 的顺序找。日志 `~/.cache/finance-manager/monthly.log`。
重建：`hermes cron create --name finance-monthly-report --script finance-monthly-report.sh --no-agent --deliver local "0 8 1 * *"`
补跑 / 看某月：`scripts/finance_cli.py report --month 2026-08 --no-notify`。
每次运行在 Phantom 事件库留一条 `cron:finance-monthly-report`。
