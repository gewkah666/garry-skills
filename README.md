# garry-skills

个人用户级 skills 仓库 — 所有 **非 Hermes / Claude Code 自带** 的 skills 都同步到这里。

## 当前 skills

| Skill | 说明 | 路径 |
|-------|------|------|
| `dashboards` | 通用数据可视化（Notion 数据源 + Plotly + Hermes plugin 托管） | `dashboards/SKILL.md` |
| `dev-tasks` | Notion 任务管理（早晨规划 / 开始 / 完成 / 漂移检测） | `dev-tasks/SKILL.md` |
| `miloco-tts` | miloco 智能 TTS 路由（让小爱音箱/电视朗读） | `miloco-tts/SKILL.md` |
| `mmx-cli` | MiniMax `mmx` CLI（文本/图像/视频/语音/音乐生成） | `mmx-cli/SKILL.md` |
| `ride-notion` | 骑行/运动数据写入 Notion 阅览世界（手动或解析截图） | `ride-notion/SKILL.md` |
| `water-reminder` | 智能喝水提醒（miloco TTS + 飞书确认 + 升级 + Notion 跳过会议） | `water-reminder/SKILL.md` |
| `daily-report` | 每日科技/游戏日报（抓源 → LLM 归类 → Notion 阅览世界；cron 01:00） | `daily-report/SKILL.md` |
| `trip-manager` | Outlook 行程 ↔ Notion 归档、高德 MCP、攻略预览（cron 07:00 归档昨天） | `trip-manager/SKILL.md` · `CRON.md` |
| `activity-manager` | 活动库刷新 / 标记已用 / 状态 | `activity-manager/SKILL.md` |
| `anime-tracker` · `bangumi-resolve` · `dmhy-search` · `episode-renamer` | 追番：Bangumi 判连载 → DMHY 磁力 → aria2（cron 02:30）；剧集重命名 | `anime-tracker/CRON.md` |
| `phantom-consolidation` | Phantom 记忆固化（phantom-consolidate 夜间任务 / 回填时怎么读事件、记什么） | `phantom-consolidation/SKILL.md` |
| `phantom-escalate` | Phantom 坚持提醒（升级阶梯，直到确认；从 water-reminder 抽出） | `phantom-escalate/SKILL.md` |

## 安装方式

所有 skills 通过 symlink 共享：

```bash
# Claude Code（2026-09-05 起全量安装：本仓库每个带 SKILL.md 的目录都链进 ~/.claude/skills/<name>）
for d in ~/Projects/garry-skills/*/; do n=$(basename "$d"); [ -f "$d/SKILL.md" ] && ln -sfn "$HOME/Projects/garry-skills/$n" "$HOME/.claude/skills/$n"; done

# Hermes（按 frontmatter tags 分类）
~/.hermes/skills/productivity/dev-tasks  → ~/Projects/garry-skills/dev-tasks
~/.hermes/skills/productivity/ride-notion → ~/Projects/garry-skills/ride-notion
~/.hermes/skills/smart-home/miloco-tts    → ~/Projects/garry-skills/miloco-tts
~/.hermes/skills/smart-home/water-reminder → ~/Projects/garry-skills/water-reminder
~/.hermes/skills/mmx-cli                  → ~/Projects/garry-skills/mmx-cli
~/.hermes/skills/phantom-consolidation    → ~/Projects/garry-skills/phantom-consolidation
~/.hermes/skills/phantom-escalate         → ~/Projects/garry-skills/phantom-escalate
# Phantom 的 skill 只给 Hermes 用（引用 phantom_* 工具），不链进 Claude Code；
# 每个 Hermes profile 也各链一份，例如 ~/.hermes/profiles/sentinel/skills/phantom-escalate

# 迁移类（M-2，2026-09-04）：原来散在 ~/.hermes/skills 与 ~/.hermes/scripts 的都收进来了，旧路径留 symlink
~/.hermes/skills/{anime-tracker,bangumi-resolve,dmhy-search,episode-renamer} → 本仓库同名目录
~/.hermes/skills/garry-skills/{trip-manager,activity-manager}                 → 本仓库同名目录
~/.hermes/scripts/{daily-report.sh,trip_archive.sh,anime-track-and-fetch.sh} 是 3 行包装 → _skill_cron.sh → 本仓库 skill 里的脚本
（Hermes cron 只接受 ~/.hermes/scripts 下的 --script；_skill_cron.sh 跑完在 Phantom 事件库留一行 cron:<name>）

# 其他（mmx-cli 工具）
~/.agents/skills/mmx-cli → ~/Projects/garry-skills/mmx-cli
```

**单一来源**：所有改动都改 `~/Projects/garry-skills/`，symlink 自动同步。

**生活类 skill 跑在 Hermes（Phantom）上**：dev-tasks / water-reminder / ride-notion / dashboards 只在 Hermes 里，
用 Phantom 的事件库、打扰预算、escalate 做状态和提醒（旧脚本在各自 `legacy/`）。相关 cron：
`water-reminder`（9–21 点每 2 小时）、`water-report`（22:00）。

## 添加新 skill

```bash
# 1. 创建 skill 目录
mkdir -p ~/Projects/garry-skills/<skill-name>
# 2. 写 SKILL.md + 脚本/资源
# 3. 创建 symlink
ln -sfv ~/Projects/garry-skills/<skill-name> ~/.claude/skills/<skill-name>

# Hermes：按 skill 类型选分类（productivity/ smart-home/ ...），
# 或放顶层（如果跟 mmx-cli 类似无分类）
ln -sfv ~/Projects/garry-skills/<skill-name> ~/.hermes/skills/<category>/<skill-name>

# 4. 更新本 README 的"当前 skills"表格 + 安装方式块
# 5. 提交 git
cd ~/Projects/garry-skills
git add <skill-name>/
git commit -m "Add <skill-name> skill"
git push
```

## 与 Hermes 自带 skills 的区别

| 类型 | 位置 | 来源 |
|------|------|------|
| Hermes 自带 | `~/.hermes/skills/<category>/<name>/` | Hermes 仓库 |
| 用户自加 | `~/Projects/garry-skills/<name>/` (真实) + symlink | 本仓库 |

定期 `git pull` 同步这个仓库即可保持本地 skill 集合最新。