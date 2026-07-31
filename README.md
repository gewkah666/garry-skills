# garry-skills

个人用户级 skills 仓库 — 所有 **非 Hermes / Claude Code 自带** 的 skills 都同步到这里。

## 当前 skills

| Skill | 说明 | 路径 |
|-------|------|------|
| `dev-tasks` | Notion 任务管理（早晨规划 / 开始 / 完成 / 漂移检测） | `dev-tasks/SKILL.md` |
| `miloco-tts` | miloco 智能 TTS 路由（让小爱音箱/电视朗读） | `miloco-tts/SKILL.md` |
| `mmx-cli` | MiniMax `mmx` CLI（文本/图像/视频/语音/音乐生成） | `mmx-cli/SKILL.md` |

## 安装方式

所有 skills 通过 symlink 共享：

```bash
# Claude Code
~/.claude/skills/dev-tasks   → ~/Projects/garry-skills/dev-tasks
~/.claude/skills/miloco-tts → ~/Projects/garry-skills/miloco-tts
~/.claude/skills/mmx-cli    → ~/Projects/garry-skills/mmx-cli

# Hermes（按 skill frontmatter name 分类）
~/.hermes/skills/productivity/dev-tasks → ~/Projects/garry-skills/dev-tasks
~/.hermes/skills/smart-home/miloco-tts → ~/Projects/garry-skills/miloco-tts
~/.hermes/skills/mmx-cli              → ~/Projects/garry-skills/mmx-cli

# 其他（mmx-cli 工具）
~/.agents/skills/mmx-cli → ~/Projects/garry-skills/mmx-cli
```

**单一来源**：所有改动都改 `~/Projects/garry-skills/`，symlink 自动同步。

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

# 4. 提交 git
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
